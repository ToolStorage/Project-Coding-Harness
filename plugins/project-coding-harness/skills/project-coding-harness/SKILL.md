---
name: project-coding-harness
description: Develop and review code using project-local Markdown memory, regression checks, and bounded adversarial review. Use for substantive natural-language programming tasks, project analysis, harness controls, or project memory updates. Skip routine planning, documentation, and small low-risk edits unless explicitly requested. Learns the project's actual architecture; no framework or KDI dependency.
---

# Project Coding Harness

Help the user develop their own project in natural language. Follow the user's requirements and applicable project instructions. Discover architecture from current code, tests, and explicit project decisions; do not import an architecture from another project or impose a preferred framework.

## Connect to the correct project

Use the current task's actual project root, never this skill's installation directory. For a workspace containing several repositories, use the repository relevant to the task; ask which project only when ambiguous. All harness tools require an absolute `project_root`; do not silently reuse another task's root.

### Decide whether to use the harness

Explicit harness controls and configuration requests are always available, even while normal harness use is off. First honor the current conversation's choice. “이번 대화에서는 끄기” disables this workflow and further onboarding questions for this conversation only, until the user explicitly turns it back on; never write that choice to project files. A one-task opt-out applies only to that task. Preserve conversation choices across context summaries, not across unrelated conversations.

For light planning, documentation, or small low-risk edits, skip harness tool calls, memory loading, onboarding, and review by default. For substantive development, call `harness_preferences` once before loading memory (CLI action `preferences` also works). This returns usage settings and analysis presence without memory content or source scans. Recheck on the next substantive task or after a settings change; do not poll during work.

- `usage_mode=on_request`: skip the workflow unless the user explicitly requests harness use for this task. A one-task request does not change the project default.
- `usage_mode=auto` with analysis present: use relevant project memory and the proportional verification policy below.
- No analysis, automatic mode, and `offer_setup=true`: before development, ask once in this conversation: “이 프로젝트는 아직 분석되지 않았습니다. 하네스 설정 페이지를 열까요?” Offer **설정 페이지 열기 / 이번 대화에서는 사용하지 않기 / 이 프로젝트에서는 요청할 때만 사용하기**. First choice opens `harness_dashboard`, without starting analysis. Second choice records only the conversation opt-out. Third choice calls `harness_configure` with `{"usage_mode":"on_request"}` and skips the workflow.
- No analysis and `offer_setup=false`: skip onboarding and harness use until explicitly requested. Never silently analyze to compensate.

Do not repeat an unanswered or already handled onboarding question in the same conversation. Silence is not consent; ordinary requested work may proceed without the harness. Opening settings alone does not authorize analysis; if none is requested, proceed without the harness. An explicit request to open settings or analyze goes directly to that action without this onboarding question. Explicit harness use without analysis can use current source inspection, but must not create memory automatically.

When harness use is active, call `harness_status` once. It reads `.coding-harness/memory.md` and local settings. Read relevant sections, then inspect the current source and tests for the area you will change. Memory is a navigation aid, not an authority over source or user instructions. Pending proposals, archived notes, and uncertain notes are not established rules. Explicit human decisions can describe intended behavior not yet implemented: distinguish that intent from implementation instead of deleting it as a contradiction.

If tools are unavailable, use the bundled CLI at `<plugin-root>/scripts/harness.py`:

```text
python <plugin-root>/scripts/harness.py call status --project <absolute-project-root>
python <plugin-root>/scripts/harness.py call <action> --project <absolute-project-root> --payload <json-file>
```

Pass multiline payloads through a UTF-8 JSON file or stdin (`--payload -`), not shell interpolation. Use the installed Python interpreter. Do not install dependencies or change host settings just to perform a normal coding task.

## Controls and analysis

Recognize natural-language intent to open harness settings, not an exact command: “하네스 설정 좀 보여줘”, “이 플러그인 옵션 바꾸고 싶어”, “검수 횟수 설정 어디서 해?”, or equivalent wording opens `harness_dashboard` directly. When context identifies this harness, do not demand its exact name or ask again whether to open it. Only clarify if the target plugin is genuinely ambiguous. If the user supplies a concrete setting value, save it directly with `harness_configure`; also open the dashboard if requested. These controls remain available while harness use is disabled. If the host does not render the component, open or link the returned loopback URL. It is served by the local MCP process and expires when that process exits. Browser controls can save settings and queue analysis, but cannot independently start an AI turn: the displayed request must be sent in the current project conversation. Never claim a queued request is completed analysis.

Project settings can be changed in conversation through `harness_configure` using only the requested fields. “이 프로젝트에서는 요청할 때만 써” → `{"usage_mode":"on_request"}`; “이 프로젝트는 자동 판단으로 바꿔” → `{"usage_mode":"auto"}`; “미분석 안내는 끄고/다시 켜줘” → `{"offer_setup":false/true}`. A clear project-setting change is authorization to save, with no extra confirmation. Confirm the saved value from the result; the page shows it on refresh. Ambiguous “꺼줘” defaults to the current conversation, not permanent project disablement. Persistent settings are in `.coding-harness/state.json`; no built-in memory or unrelated project settings are changed.

Analysis and persistent memory refresh require the user to click the corresponding button or explicitly request them in conversation. Ordinary coding authorization is not authorization to regenerate memory. If memory is absent, proceed by inspecting relevant code and respect the onboarding choice above; do not block requested work on onboarding.

For a pending `analyze` or `refresh` request, read [memory.md](references/memory.md). Complete actual codebase analysis and every remembered-note decision before calling `harness_save_analysis`. Do not modify application code as part of an analysis-only request. If the request is stale because memory changed, cancel the stale request and replace it under the same explicit refresh authorization, then reread current memory.

## Coding and verification

Read the project's own instructions, manifests, entry points, representative neighboring code, and affected tests. Resolve the requested behavior before choosing an implementation. Respect existing boundaries, naming, dependencies and error handling unless the task calls for changing them. A repeated pattern is evidence, not proof that it is desirable. Report conflicting patterns rather than inventing uniformity.

Implement the requested behavior with a focused diff. Avoid opportunistic rewrites. Use the project's existing build/test tools and commands from memory only after checking that they still apply. Add regression coverage when it meaningfully protects the changed behavior; avoid tests that only mirror implementation. Use inexpensive, relevant diff/syntax checks by default. Choose additional verification using the policy below; distinguish pre-existing failures, new failures, and checks that could not run.

### Choose verification proportionately

User instructions for this task take precedence over default review behavior. Track regression tests, runtime tests, and adversarial review separately: “적대적 검수 해줘” authorizes review without another question; “적대적 검수 안 해도 됨” skips that review; “런타임 테스트는 내가 할게” leaves runtime testing to the user without cancelling other requested checks. Apply an explicit combined instruction as given. Do not persist task-specific choices as project defaults unless requested.

Small, low-risk edits need only focused checks; do not ask about or start a formal adversarial loop by default. Judge impact rather than line count: changes to public behavior, architecture, state/data handling, lifetimes, concurrency, or multiple interacting components may warrant review even with a short diff.

For a substantial or risky change with no applicable user decision, first finish the implementation and inexpensive checks. Then briefly explain the concrete change and proposed verification scope and ask: “이번 변경은 [구체적인 영향]이 있어 회귀테스트와 적대적 검수를 시행할까요?” Offer these choices (a selection tool if available, otherwise a numbered question):

1. 회귀테스트 + 적대적 검수 (권장)
2. 회귀테스트만
3. 이번에는 생략 / 직접 검증

Allow a custom answer, including review-only or user-owned runtime tests. If one part is already decided, ask only about the undecided part when needed; never ask again for authorization already given. Repository-required checks still apply unless the user's instruction overrides them; identify any mandatory checks separately rather than offering to skip something you cannot skip. Continue independent authorized work while awaiting the choice. Silence or elapsed time is not consent: leave optional verification pending and report the gap without starting it. Do not repeatedly prompt for an unchanged scope.

Only when adversarial review is requested or selected, read [review.md](references/review.md) and start its bounded loop. Saved depth and round limits configure an authorized review; saving them does not authorize review of every change. Never change settings to make work pass. No automatic commit, push, deployment, or external messages are authorized merely by this skill.

## Finish and propose useful memory

Report the delivered behavior, actual verification, and remaining issues in plain language. Then consider whether the task established durable knowledge missing from project memory: an architectural decision, a non-obvious constraint, a verified build workaround, or a recurring failure and its cause. Do not propose transient progress, generic advice, unverified guesses, secrets, or every changed file.

If analyzed memory exists, call `harness_propose` with a concise title, exact proposed Markdown and source evidence. The proposal is pending and must not be treated as memory. At the END of the final response ask a concrete question in the user's language, for example:

> “결제 상태는 서버 응답으로만 확정한다”는 결정을 메모리에 기억해둘까요?

For several related facts, propose one concise grouped entry. Do not wait indefinitely, repeat declined identical proposals, or ask before finishing the already-authorized work. Do not call `harness_decide_proposal` until the user explicitly agrees to the specific proposal. Silence, a new coding request, and general approval of the completed code do not count. The UI's “기억하기” button is explicit consent. If a reply is ambiguous among multiple pending proposals, clarify which entry. Explicit decline records decline. On acceptance call `harness_decide_proposal` with `user_confirmed: true`; changed evidence requires revalidation and renewed consent for materially changed wording.

If memory has not yet been analyzed, explain the useful fact in the final response and offer project analysis; do not secretly initialize persistent memory. Never write to ChatGPT/Codex built-in memory directories. Only this project's `.coding-harness` storage belongs to this workflow.
