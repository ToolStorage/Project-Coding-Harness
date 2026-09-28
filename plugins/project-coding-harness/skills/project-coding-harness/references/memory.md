# Project memory contract

## Storage and authority

The only active memory file is `<project-root>/.coding-harness/memory.md`. It is UTF-8 Markdown with a small JSON metadata comment and named Markdown sections: `project`, `architecture`, `verification`, and `note_<id>`. Use the storage tools to preserve its schema and concurrency checks. The app never modifies built-in assistant memories or AGENTS.md.

`state.json` contains settings, queued requests, pending/declined proposals, and review bookkeeping. It is not project knowledge. `history/<revision>.md` contains previous snapshots. Archived notes remain in memory with `status=archived` for traceability but are excluded from active guidance. Uncertain notes require investigation before use. Do not physically erase history during refresh. These local files can contain project-private information: do not copy them into the public plugin repository or commit them without the project's normal authorization.

Only the model analyzes code. The tools validate structure and store the resulting Markdown; a successful save is not a certificate of correctness. Evidence fingerprints flag known-source drift; unchanged fingerprints do not prove the entire project is unchanged. Non-Git projects are supported. A cloned project may reuse its memory, but recheck facts against its current sources.

## First analysis

Obtain a request from `harness_request_analysis` with `payload.mode=analyze` only after an explicit user request. A button may already have created it; inspect status and reuse that pending request.

Inspect project instructions, manifests/lockfiles, representative modules, runtime entry points, tests, and build scripts. Use targeted search and samples rather than loading every file. Skip secrets, dependency caches, generated build output, and unrelated repositories. No architecture template is mandatory. Record unknowns explicitly.

Write three concise Markdown sections:

- `project`: purpose, project boundaries, stack with verified versions when available, important paths, where to start for common work, analysis coverage and gaps.
- `architecture`: actual module responsibilities and dependency flow, code conventions with examples, state/data flow and lifecycle where relevant, explicit decisions vs observed patterns, exceptions and conflicting approaches.
- `verification`: exact commands with working directories, prerequisites, what each validates, checks actually run vs discovered but not run, known limitations. Analysis need not execute expensive builds; never invent a successful result.

Call `harness_save_analysis` with this payload shape:

```json
{
  "request_id": "pending request ID",
  "name": "Project display name",
  "project": "# Project\n...",
  "architecture": "# Architecture\n...",
  "verification": "# Verification\n...",
  "evidence": ["README.md", "src/main.py"],
  "note_decisions": {}
}
```

Evidence must be existing project-relative files actually read, not a made-up example copied above. Include relevant instruction/manifests and representative source/test files (1..100 files, each <=2 MB). Reread evidence if code changed during analysis. Avoid secrets or unrelated personal data in Markdown. The metadata stores file hashes, not file contents.

## Explicit refresh

Use a pending `refresh` request. Compare old sections and all notes against current sources and project instructions. Update the affected portions and check whether broader structural changes require a wider analysis. Do not overwrite human design intent with a guessed policy inferred from code.

`note_decisions` MUST contain every existing note ID, including archived and uncertain notes. Each needs `action` and a concrete `reason`:

| Action | When | Extra fields |
|---|---|---|
| `keep` | Still supported; may reactivate a previously archived note when evidence warrants it | `evidence`: existing paths |
| `update` | The durable fact remains useful but its content changed | `body`: complete replacement Markdown; `evidence` |
| `archive` | Superseded, disproved, or no longer applicable | Explain the contradictory/superseding evidence in `reason` |
| `uncertain` | Insufficient evidence or unresolved conflict | Describe what would resolve it; preserve the text |

Missing evidence alone does not justify deletion: inspect renamed/moved code and distinguish an unimplemented human decision from an obsolete claim. Explicit refresh authorizes these evidence-based lifecycle decisions; do not ask for approval of every mechanical update. Ask only when an unresolved product/design choice belongs to the user. Finish by reporting which notes were maintained, changed, archived, or left uncertain and why. Prior snapshots remain available.

Example decision entry:

```json
{
  "existing-note-id": {
    "action": "update",
    "reason": "The validated entry point moved from a synchronous handler to the queue worker.",
    "body": "# Payment completion\nThe queue worker confirms payment after the provider response.",
    "evidence": ["src/payment_worker.py", "tests/test_payment_worker.py"]
  }
}
```

If a file is malformed, report it and use history for deliberate recovery; never silently reset the project. If a stale `.lock` remains after a crash, first ensure no harness writer is running, then ask the user to remove that exact lock or do so under their explicit recovery instruction.
