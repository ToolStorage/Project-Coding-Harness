"""Project-local harness persistence. Python 3.10+, no third-party packages."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

DEFAULTS = {"review_depth": "standard", "max_rounds": 3}
SECTIONS = ("project", "architecture", "verification")


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


def text(value, name, limit=60000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name}: nonempty text (max {limit}) required")
    if "<!-- harness-section:" in value or "<!-- harness-meta" in value:
        raise ValueError("Reserved memory delimiter in text")
    return value.strip()


def atomic(path, value):
    temp = path.with_name(path.name + "." + uid() + ".tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def encode_memory(meta, sections):
    head = "<!-- harness-meta\n" + json.dumps(meta, ensure_ascii=False, indent=2) + "\n-->\n"
    return head + "\n".join(f"\n<!-- harness-section:{key} -->\n{body.strip()}\n" for key, body in sections.items())


def decode_memory(raw):
    match = re.match(r"<!-- harness-meta\n(.*?)\n-->\n", raw, re.S)
    if not match:
        raise ValueError("Memory format damaged; restore history instead of overwriting")
    meta = json.loads(match.group(1))
    chunks = re.split(r"\n<!-- harness-section:([a-z0-9_-]+) -->\n", raw[match.end():])
    sections = dict(zip(chunks[1::2], (s.strip() for s in chunks[2::2])))
    if meta.get("schema") != 1 or not all(k in sections for k in SECTIONS):
        raise ValueError("Unsupported or incomplete memory")
    return meta, sections


class Store:
    allowed_root = None

    def __init__(self, root):
        path = Path(root).expanduser()
        if self.allowed_root is not None and path.resolve() != self.allowed_root:
            raise ValueError("Project boundary: this harness is restricted to its configured project")
        if not path.is_absolute() or not path.is_dir():
            raise ValueError("project_root must be an existing absolute directory")
        self.root = path.resolve()
        self.base = self.root / ".coding-harness"
        self.check_paths()

    def check_paths(self):
        if self.base.exists():
            for path in [self.base, *self.base.rglob("*")]:
                if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                    raise ValueError("Links/junctions inside .coding-harness are unsupported")
                if not path.resolve().is_relative_to(self.root):
                    raise ValueError("Harness path escapes project")

    @contextmanager
    def lock(self):
        self.check_paths()
        self.base.mkdir(exist_ok=True)
        lock = self.base / ".lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise ValueError("Another harness write is active. A crashed process may leave .coding-harness/.lock; inspect it before removing.")
        try:
            os.write(fd, json.dumps({"pid": os.getpid(), "at": now()}).encode())
            os.close(fd)
            yield
        finally:
            lock.unlink(missing_ok=True)

    def state(self):
        path = self.base / "state.json"
        if not path.exists():
            return {"schema": 1, "settings": DEFAULTS.copy(), "requests": {}, "proposals": {}, "runs": {}}
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("schema") != 1:
            raise ValueError("Unsupported state schema")
        return state

    def save_state(self, state):
        atomic(self.base / "state.json", json.dumps(state, ensure_ascii=False, indent=2) + "\n")

    def memory(self):
        path = self.base / "memory.md"
        return decode_memory(path.read_text(encoding="utf-8")) if path.exists() else (None, {})

    def write_memory(self, meta, sections):
        path = self.base / "memory.md"
        if path.exists():
            old = path.read_text(encoding="utf-8")
            old_meta, _ = decode_memory(old)
            history = self.base / "history"
            history.mkdir(exist_ok=True)
            target = history / (old_meta["revision"] + ".md")
            if not target.exists():
                atomic(target, old)
        meta["revision"] = uid()
        meta["updated_at"] = now()
        atomic(path, encode_memory(meta, sections))

    def evidence(self, values):
        if not isinstance(values, list) or not 1 <= len(values) <= 100:
            raise ValueError("Provide 1..100 project-relative evidence file paths")
        result = {}
        for value in values:
            value = text(value, "evidence path", 500)
            path = self.root / value
            if Path(value).is_absolute() or not path.resolve().is_relative_to(self.root):
                raise ValueError("Evidence must stay in the project")
            if ".coding-harness" in Path(value).parts or not path.is_file():
                raise ValueError(f"Evidence must be an existing source/document file: {value}")
            if path.stat().st_size > 2_000_000:
                raise ValueError("Evidence file too large; choose a narrower source")
            result[path.relative_to(self.root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def changed(self, evidence):
        changed = []
        for name, digest in evidence.items():
            try:
                current = self.evidence([name])[name]
            except (ValueError, OSError):
                current = None
            if current != digest:
                changed.append(name)
        return changed

    def git_head(self):
        try:
            return subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip() or None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def status(self):
        meta, sections = self.memory()
        state = self.state()
        changed = self.changed(meta["evidence"]) if meta else []
        notes = []
        if meta:
            for key, entry in meta.get("notes", {}).items():
                notes.append({"id": key, **entry, "body": sections["note_" + key], "changed_evidence": self.changed(entry["evidence"])})
        stale = bool(changed or any(n["changed_evidence"] for n in notes) or (meta and meta.get("git_head") != self.git_head()))
        return {"project_root": str(self.root), "project_name": meta["name"] if meta else self.root.name,
                "analysis_status": "refresh_recommended" if stale else "analyzed" if meta else "not_analyzed",
                "revision": meta["revision"] if meta else None, "updated_at": meta.get("updated_at") if meta else None,
                "settings": state["settings"], "sections": {k: sections[k] for k in SECTIONS if k in sections},
                "changed_evidence": changed, "notes": notes,
                "proposals": list(state["proposals"].values()), "requests": list(state["requests"].values()),
                "runs": list(state["runs"].values())[-10:], "memory_path": str(self.base / "memory.md")}

    def configure(self, payload):
        depth, rounds = payload.get("review_depth"), payload.get("max_rounds")
        if depth not in ("standard", "deep") or type(rounds) is not int or not 1 <= rounds <= 10:
            raise ValueError("review_depth=standard|deep; max_rounds must be integer 1..10")
        with self.lock():
            state = self.state()
            state["settings"] = {"review_depth": depth, "max_rounds": rounds}
            self.save_state(state)
        return self.status()

    def request_analysis(self, payload):
        mode = payload.get("mode")
        if mode not in ("analyze", "refresh"):
            raise ValueError("mode=analyze|refresh required; invoke only on explicit user request")
        with self.lock():
            state = self.state()
            meta, _ = self.memory()
            if mode == "analyze" and meta:
                raise ValueError("Already analyzed; use explicit refresh")
            if mode == "refresh" and not meta:
                raise ValueError("Analyze the project first")
            active = next((v for v in state["requests"].values() if v["status"] == "pending"), None)
            if active:
                return active
            req = {"id": uid(), "mode": mode, "status": "pending", "created_at": now(), "base_revision": meta["revision"] if meta else None}
            req["prompt"] = f"Use $project-coding-harness to process {mode} request {req['id']} for project {json.dumps(str(self.root), ensure_ascii=False)}. Read its current sources and instructions, then commit the analysis; revalidate every remembered decision when refreshing."
            state["requests"][req["id"]] = req
            self.save_state(state)
        return req

    def save_analysis(self, payload):
        with self.lock():
            state = self.state()
            req = state["requests"].get(payload.get("request_id"))
            if not req or req["status"] != "pending":
                raise ValueError("A pending explicit analysis/refresh request is required")
            meta, old_sections = self.memory()
            # Recovery if the memory was committed but the state write was interrupted.
            if meta and meta.get("request_id") == req["id"]:
                req["status"] = "completed"
                self.save_state(state)
                return self.status()
            if req["base_revision"] != (meta["revision"] if meta else None):
                raise ValueError("Memory changed since this request; cancel and request refresh again")
            sections = {key: text(payload.get(key), key) for key in SECTIONS}
            evidence = self.evidence(payload.get("evidence"))
            notes = copy.deepcopy(meta.get("notes", {}) if meta else {})
            decisions = payload.get("note_decisions", {})
            if not isinstance(decisions, dict) or set(decisions) != set(notes):
                raise ValueError("Revalidate EVERY note with keep/update/archive/uncertain, including archived notes")
            for key, entry in notes.items():
                decision = decisions[key]
                action = decision.get("action")
                if action not in ("keep", "update", "archive", "uncertain"):
                    raise ValueError("Invalid note decision")
                entry["last_review"] = {"at": now(), "action": action, "reason": text(decision.get("reason"), "reason", 4000)}
                if action in ("keep", "update"):
                    entry["evidence"] = self.evidence(decision.get("evidence"))
                    entry["status"] = "active"
                else:
                    entry["status"] = "archived" if action == "archive" else "uncertain"
                sections["note_" + key] = text(decision.get("body"), "updated note") if action == "update" else old_sections["note_" + key]
            new_meta = {"schema": 1, "name": text(payload.get("name"), "name", 200), "evidence": evidence,
                        "git_head": self.git_head(), "notes": notes, "request_id": req["id"]}
            self.write_memory(new_meta, sections)
            req["status"] = "completed"
            self.save_state(state)
        return self.status()

    def cancel_request(self, payload):
        with self.lock():
            state = self.state()
            req = state["requests"][payload["request_id"]]
            if req["status"] != "pending":
                raise ValueError("Request is not pending")
            req["status"] = "cancelled"
            self.save_state(state)
        return self.status()

    def propose(self, payload):
        with self.lock():
            meta, _ = self.memory()
            if not meta:
                raise ValueError("Analyze before proposing persistent memories")
            state = self.state()
            proposal = {"id": uid(), "title": text(payload.get("title"), "title", 200),
                        "body": text(payload.get("body"), "body", 10000),
                        "evidence": self.evidence(payload.get("evidence")), "status": "pending", "created_at": now()}
            # Proposals are not active memory. Do not repeatedly ask an identical question.
            existing = next((v for v in state["proposals"].values() if v["title"] == proposal["title"] and v["body"] == proposal["body"] and v["evidence"] == proposal["evidence"]), None)
            if existing:
                return existing
            for prior in state["proposals"].values():
                if prior["status"] == "pending" and prior["title"] == proposal["title"] and prior["body"] == proposal["body"]:
                    prior["status"] = "superseded"
            state["proposals"][proposal["id"]] = proposal
            self.save_state(state)
        return proposal

    def decide_proposal(self, payload):
        if payload.get("decision") not in ("accept", "decline"):
            raise ValueError("decision=accept|decline")
        if payload.get("user_confirmed") is not True:
            raise ValueError("Explicit user consent is required; silence is not consent")
        with self.lock():
            state = self.state()
            prop = state["proposals"][payload["proposal_id"]]
            if prop["status"] != "pending":
                return self.status()
            if payload["decision"] == "accept":
                meta, sections = self.memory()
                if not meta:
                    raise ValueError("Analysis memory missing")
                key = prop["id"]
                if key not in meta["notes"]:
                    if self.changed(prop["evidence"]):
                        raise ValueError("Proposal evidence changed. Revalidate and create a new proposal before accepting")
                    meta["notes"][key] = {"title": prop["title"], "status": "active", "evidence": prop["evidence"], "accepted_at": now()}
                    sections["note_" + key] = prop["body"]
                    self.write_memory(meta, sections)
            prop["status"] = "accepted" if payload["decision"] == "accept" else "declined"
            prop["decided_at"] = now()
            self.save_state(state)
        return self.status()

    def start_review(self, payload):
        with self.lock():
            state = self.state()
            run = {"id": uid(), "scope": text(payload.get("scope"), "scope", 4000), "settings": state["settings"].copy(),
                   "status": "running", "rounds": [], "started_at": now()}
            state["runs"][run["id"]] = run
            self.save_state(state)
        return run

    def record_review(self, payload):
        with self.lock():
            state = self.state()
            run = state["runs"][payload["run_id"]]
            if run["status"] != "running":
                raise ValueError("Review has already stopped")
            complete, verified = payload.get("review_complete"), payload.get("verification_passed")
            count = payload.get("unresolved_issues")
            if type(complete) is not bool or type(verified) is not bool or type(count) is not int or count < 0:
                raise ValueError("Provide boolean completion/verification and nonnegative unresolved_issues")
            number = len(run["rounds"]) + 1
            if payload.get("round") != number:
                raise ValueError(f"Expected round {number}; duplicate/out-of-order result rejected")
            report = {"round": number, "review_complete": complete, "verification_passed": verified, "unresolved_issues": count,
                      "evidence": text(payload.get("evidence"), "review evidence", 16000), "at": now()}
            run["rounds"].append(report)
            if not complete:
                run["status"] = "blocked"
            elif count == 0 and verified:
                run["status"] = "passed"
            elif number >= run["settings"]["max_rounds"]:
                run["status"] = "limit_reached"
            self.save_state(state)
        return run


ACTIONS = ("status", "configure", "request_analysis", "save_analysis", "cancel_request", "propose", "decide_proposal", "start_review", "record_review")


def dispatch(action, root, payload=None):
    if action not in ACTIONS:
        raise ValueError("Unknown action")
    store = Store(root)
    return store.status() if action == "status" else getattr(store, action)(payload or {})
