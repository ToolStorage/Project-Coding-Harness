# Validation scope — 0.1.0

Validated on Windows on 2026-09-28 with Python 3.13 and the locally installed Codex CLI. Python 3.10+ is the implementation target; macOS/Linux execution has not yet been exercised.

## Automated checks

`python -m unittest discover -s tests -v`: **18 passed, 1 skipped** (19 cases). The skipped case needs permission to create a symbolic link on Windows.

Covered behaviors:

- Status reads do not create memory; projects do not share state.
- Analysis requires a pending explicit request and in-project source evidence.
- Pending/declined proposals do not become memory; acceptance is idempotent.
- Changed evidence blocks stale acceptance; revalidated proposals supersede stale duplicates.
- Refresh must account for every remembered entry; keep/update/archive/uncertain preserve history.
- Revision conflicts and malformed memory fail without overwriting the accepted snapshot.
- Interrupted analysis commit can recover without duplicating its snapshot.
- Review stops early on a verified clean round, preserves its configured cap, rejects duplicate rounds, and does not equate unavailable verification with success.
- MCP stdio initialization, tool invocation, and HTML resource delivery.
- Loopback UI reads/writes, random URL token and cross-origin request rejection.

`tests/ui.cjs` passed in headless Microsoft Edge using Playwright. It exercised settings persistence, analysis request creation, rendered project name, memory acceptance, refresh/cancel, and a 390px viewport without horizontal overflow. No JavaScript runtime errors were observed. A simulated MCP Apps parent also exercised initialization, tool results, tool calls, and the follow-up message bridge.

Official local plugin and skill validators passed. Their development-only PyYAML dependency is not a runtime dependency of this plugin.

## Installation

`install.py` succeeded twice in an isolated temporary `CODEX_HOME`. The test confirmed local marketplace registration, cached skill installation, and absolute-path local MCP registration. It did not enable the plugin in the author's normal Codex settings or initialize any KDI project memory.

## Limits that remain explicit

- An actual Codex/ChatGPT host's embedded MCP Apps rendering and model-turn handoff have **not** been end-to-end tested. The simulated bridge is not proof of host support. The local browser UI is the tested fallback; it requires sending the prepared analysis request into the current conversation.
- No independent LLM behavioral evaluation was run. The coding/review workflow is skill-guided; storage tools enforce data transitions and counters, not model compliance or semantic truth.
- Test evidence entered by the model is not independently attested by this server. A stored `passed` status records the submitted report, not proof that a compiler or tests ran.
- Source fingerprint changes suggest refresh; they do not detect every possible new file or architectural change. The agent must inspect relevant current code on each task.
- `user_confirmed` is a tool contract checked by the runtime, not a cryptographic proof of conversational consent. The agent must obey the skill's explicit-consent rule. UI acceptance is an explicit button action.
- The project directory and its local files must be trusted. The local lock prevents concurrent cooperating writers; it is not an OS sandbox against a malicious local process.

## Reproduce

```text
python -m unittest discover -s tests -v
```

For optional browser verification install Playwright in a development environment, then run `node tests/ui.cjs`. It defaults to the installed Microsoft Edge channel. `HARNESS_BROWSER=chrome` selects Chrome, and `HARNESS_PYTHON` selects the Python executable. Generated screenshots go to ignored `.test-output/`.

## Bundled MCP update

Validated marketplace installation and actual MCP startup using an isolated Codex app-server (no model turn). The portable manifest requires its Agent Plugins schema; `${PLUGIN_ROOT}` resolves to the install cache. All 10 harness tools were discovered. `--project` now binds the server to one canonical project root and rejects read/write requests for other roots. The existing embedded UI limitation above still applies.

## Proportional verification policy update

Updated skill instructions and dashboard help so substantial changes prompt for optional regression/review choices and explicit task instructions take precedence. Skill/plugin validators, `git diff --check`, and the existing browser smoke suite passed. No storage or review-counter behavior changed. Instruction compliance, including natural-language choice handling, has not been evaluated through an independent model run.

## Project usage controls update

Python suite: **20 passed, 1 skipped** (Windows symlink permission). Added read-only preferences checks, legacy setting defaults, partial update preservation, invalid value rejection, and no implicit memory creation. Browser suite passed with usage controls saved/reloaded and changes through the conversation tool contract reflected after refresh. Natural-language onboarding and intent routing remain skill-guided, not independently model-evaluated.
