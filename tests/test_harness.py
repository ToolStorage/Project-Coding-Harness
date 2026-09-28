import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins/project-coding-harness/scripts"
sys.path.insert(0, str(SCRIPTS))
from store import Store, decode_memory
from harness import Dashboard, MCP, URI


class ProjectCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "main.py").write_text("print('hello')\n", encoding="utf-8")
        self.store = Store(str(self.root))

    def tearDown(self):
        self.temp.cleanup()

    def payload(self, req, decisions=None):
        return {"request_id": req["id"], "name": "친구의 앱", "project": "# 목적\n샘플 앱", "architecture": "# 구조\nmain.py가 진입점", "verification": "# 검증\n아직 실행하지 않음", "evidence": ["main.py"], "note_decisions": decisions or {}}

    def analyze(self):
        return self.store.save_analysis(self.payload(self.store.request_analysis({"mode": "analyze"})))

    def propose(self):
        return self.store.propose({"title": "단일 진입점", "body": "진입점은 main.py다.", "evidence": ["main.py"]})

    def accept(self, p):
        return self.store.decide_proposal({"proposal_id": p["id"], "decision": "accept", "user_confirmed": True})

    def test_bound_mcp_rejects_other_project(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "harness_status", "arguments": {"project_root": str(self.root)}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "harness_status", "arguments": {"project_root": str(self.root.parent)}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "harness_configure", "arguments": {"project_root": str(self.root.parent), "payload": {"review_depth": "deep", "max_rounds": 3}}}},
        ]
        result = subprocess.run([sys.executable, str(SCRIPTS / "harness.py"), "mcp", "--project", str(self.root)], input="\n".join(map(json.dumps, requests))+"\n", text=True, encoding="utf-8", capture_output=True, check=True)
        responses = list(map(json.loads, result.stdout.splitlines()))
        self.assertNotIn("isError", responses[0]["result"])
        for response in responses[1:]:
            self.assertTrue(response["result"]["isError"])
            self.assertIn("Project boundary", response["result"]["content"][0]["text"])

    def test_read_only_status_and_project_isolation(self):
        self.assertEqual(self.store.status()["analysis_status"], "not_analyzed")
        self.assertFalse(self.store.base.exists())
        self.analyze()
        other = self.root / "other"
        other.mkdir()
        self.assertEqual(Store(str(other)).status()["analysis_status"], "not_analyzed")

    def test_analysis_requires_request_and_valid_evidence(self):
        with self.assertRaises(ValueError):
            self.store.save_analysis(self.payload({"id": "fake"}))
        req = self.store.request_analysis({"mode": "analyze"})
        payload = self.payload(req)
        payload["evidence"] = ["../outside.py"]
        with self.assertRaises(ValueError):
            self.store.save_analysis(payload)
        self.assertFalse((self.store.base / "memory.md").exists())

    def test_pending_declined_and_silence_never_become_memory(self):
        self.analyze()
        old = (self.store.base / "memory.md").read_bytes()
        p = self.propose()
        self.assertEqual(self.store.status()["notes"], [])
        with self.assertRaises(ValueError):
            self.store.decide_proposal({"proposal_id": p["id"], "decision": "accept"})
        self.store.decide_proposal({"proposal_id": p["id"], "decision": "decline", "user_confirmed": True})
        self.assertEqual((self.store.base / "memory.md").read_bytes(), old)
        self.assertEqual(self.propose()["status"], "declined")

    def test_accept_once_with_readable_markdown_and_history(self):
        self.analyze()
        p = self.propose()
        result = self.accept(p)
        self.assertEqual(result["notes"][0]["body"], p["body"])
        self.assertEqual(self.accept(p)["revision"], result["revision"])
        self.assertEqual(len(list((self.store.base / "history").glob("*.md"))), 1)
        raw = (self.store.base / "memory.md").read_text(encoding="utf-8")
        self.assertIn("# 구조", raw)
        self.assertEqual(len(decode_memory(raw)[0]["notes"]), 1)

    def test_revalidated_identical_proposal_supersedes_stale_one(self):
        self.analyze()
        old = self.propose()
        (self.root / "main.py").write_text("print('new implementation')")
        new = self.propose()
        self.assertNotEqual(old["id"], new["id"])
        self.assertEqual(self.store.state()["proposals"][old["id"]]["status"], "superseded")
        self.assertEqual(self.accept(new)["notes"][0]["body"], new["body"])

    def test_analysis_recovers_commit_before_state_write_interruption(self):
        req = self.store.request_analysis({"mode": "analyze"})
        with patch.object(self.store, "save_state", side_effect=OSError("simulated interruption")):
            with self.assertRaises(OSError):
                self.store.save_analysis(self.payload(req))
        committed_revision = self.store.status()["revision"]
        result = self.store.save_analysis(self.payload(req))
        self.assertEqual(result["revision"], committed_revision)
        self.assertEqual(result["requests"][0]["status"], "completed")

    def test_stale_proposal_blocked(self):
        self.analyze()
        p = self.propose()
        (self.root / "main.py").write_text("print('changed')")
        with self.assertRaises(ValueError):
            self.accept(p)
        self.assertEqual(self.store.status()["analysis_status"], "refresh_recommended")

    def test_refresh_must_account_for_every_note(self):
        self.analyze()
        p = self.propose()
        self.accept(p)
        req = self.store.request_analysis({"mode": "refresh"})
        with self.assertRaises(ValueError):
            self.store.save_analysis(self.payload(req))
        r = self.store.save_analysis(self.payload(req, {p["id"]: {"action": "archive", "reason": "Superseded by a new entry point."}}))
        self.assertEqual(r["notes"][0]["status"], "archived")
        self.assertEqual(r["notes"][0]["body"], p["body"])
        self.assertEqual(len(list((self.store.base / "history").glob("*.md"))), 2)

    def test_refresh_update_uncertain_and_keep(self):
        self.analyze()
        p = self.propose()
        self.accept(p)
        for action, status in [("update", "active"), ("uncertain", "uncertain"), ("keep", "active")]:
            req = self.store.request_analysis({"mode": "refresh"})
            d = {"action": action, "reason": "Revalidated source and intent", "body": "main.py is the CLI entry point.", "evidence": ["main.py"]}
            result = self.store.save_analysis(self.payload(req, {p["id"]: d}))
            self.assertEqual(result["notes"][0]["status"], status)
            self.assertEqual(result["notes"][0]["body"], d["body"])

    def test_revision_conflict_preserves_newly_accepted_note(self):
        self.analyze()
        req = self.store.request_analysis({"mode": "refresh"})
        self.accept(self.propose())
        with self.assertRaises(ValueError):
            self.store.save_analysis(self.payload(req))
        self.assertEqual(len(self.store.status()["notes"]), 1)

    def test_lock_and_corruption_fail_closed(self):
        self.analyze()
        with self.store.lock():
            with self.assertRaises(ValueError):
                self.store.configure({"review_depth": "deep", "max_rounds": 2})
        (self.store.base / "memory.md").write_text("corrupt")
        with self.assertRaises(ValueError):
            self.store.status()

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            try:
                self.store.base.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("OS does not permit unprivileged symlinks")
            with self.assertRaises(ValueError):
                Store(str(self.root))

    def review_payload(self, run):
        return {"run_id": run["id"], "round": 1, "review_complete": True, "verification_passed": True, "unresolved_issues": 0, "evidence": "Scoped regression tests passed on reviewed code."}

    def test_clean_review_stops_early(self):
        run = self.store.start_review({"scope": "CLI behavior"})
        p = self.review_payload(run)
        self.assertEqual(self.store.record_review(p)["status"], "passed")
        with self.assertRaises(ValueError):
            self.store.record_review(p)

    def test_cap_frozen_settings_and_duplicate_round(self):
        self.store.configure({"review_depth": "deep", "max_rounds": 2})
        run = self.store.start_review({"scope": "Retry behavior"})
        self.store.configure({"review_depth": "standard", "max_rounds": 5})
        p = self.review_payload(run)
        p.update(verification_passed=False, unresolved_issues=1)
        self.assertEqual(self.store.record_review(p)["status"], "running")
        with self.assertRaises(ValueError):
            self.store.record_review(p)
        p["round"] = 2
        self.assertEqual(self.store.record_review(p)["status"], "limit_reached")

    def test_incomplete_or_unverified_review_never_passes(self):
        self.store.configure({"review_depth": "standard", "max_rounds": 1})
        for complete, expected in [(False, "blocked"), (True, "limit_reached")]:
            run = self.store.start_review({"scope": "Unavailable integration environment"})
            p = self.review_payload(run)
            p.update(review_complete=complete, verification_passed=False)
            self.assertEqual(self.store.record_review(p)["status"], expected)

    def test_preferences_avoid_memory_and_source_reads(self):
        with patch.object(Store, "memory", side_effect=AssertionError("memory read")), patch.object(Store, "git_head", side_effect=AssertionError("git read")):
            self.assertFalse(self.store.preferences()["has_analysis"])
            self.assertFalse(self.store.base.exists())
            self.store.base.mkdir()
            (self.store.base / "memory.md").write_text("not parsed by preferences", encoding="utf-8")
            self.assertTrue(self.store.preferences()["has_analysis"])

    def test_legacy_settings_and_partial_updates(self):
        self.store.configure({"review_depth": "deep", "max_rounds": 2})
        path = self.store.base / "state.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["settings"] = {"review_depth": "deep", "max_rounds": 2}
        path.write_text(json.dumps(data), encoding="utf-8")
        before = path.read_bytes()
        self.assertEqual(self.store.preferences()["settings"]["usage_mode"], "auto")
        self.assertEqual(path.read_bytes(), before)
        self.store.configure({"usage_mode": "on_request", "offer_setup": False})
        self.store.configure({"max_rounds": 4})
        settings = Store(str(self.root)).preferences()["settings"]
        self.assertEqual(settings, {"review_depth": "deep", "max_rounds": 4, "usage_mode": "on_request", "offer_setup": False})
        self.assertFalse((self.store.base / "memory.md").exists())
        for payload in ({"usage_mode": "off"}, {"offer_setup": "false"}, {"offer_setup": 0}, {"session_disabled": True}):
            with self.assertRaises(ValueError):
                self.store.configure(payload)
            self.assertEqual(self.store.preferences()["settings"], settings)

    def test_settings_validation(self):
        for value in (0, 11, True, 1.5, "3"):
            with self.assertRaises(ValueError):
                self.store.configure({"review_depth": "standard", "max_rounds": value})

    def test_mcp_stdio_and_ui_resource(self):
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}, {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "harness_status", "arguments": {"project_root": str(self.root)}}}]
        result = subprocess.run([sys.executable, str(SCRIPTS / "harness.py"), "mcp"], input="\n".join(map(json.dumps, messages)) + "\n", text=True, encoding="utf-8", capture_output=True, timeout=10, check=True)
        responses = list(map(json.loads, result.stdout.splitlines()))
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(responses[1]["result"]["structuredContent"]["analysis_status"], "not_analyzed")
        resource = MCP().handle({"method": "resources/read", "params": {"uri": URI}})
        self.assertEqual(resource["contents"][0]["mimeType"], "text/html;profile=mcp-app")

    def test_browser_api_and_cross_origin_protection(self):
        dashboard = Dashboard(str(self.root))
        try:
            with urllib.request.urlopen(dashboard.url) as response:
                self.assertIn("프로젝트 분석하기", response.read().decode())
            origin = dashboard.url.split("/" + dashboard.token)[0]
            data = json.dumps({"review_depth": "deep", "max_rounds": 4}).encode()
            req = urllib.request.Request(dashboard.url + "configure", data=data, headers={"Content-Type": "application/json", "Origin": origin})
            with urllib.request.urlopen(req) as response:
                self.assertEqual(json.load(response)["settings"]["max_rounds"], 4)
            req = urllib.request.Request(dashboard.url + "configure", data=data, headers={"Content-Type": "application/json", "Origin": "https://attacker.invalid"})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req)
            self.assertEqual(caught.exception.code, 403)
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(origin + "/bad-token/status")
        finally:
            dashboard.close()


if __name__ == "__main__":
    unittest.main()
