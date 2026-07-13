### 2026-07-09 — Project Navigation Initialized
**Decision:** Add minimal `.Codex` navigation files for this Agent Harness repo before editing docs.
**Alternatives bỏ:** Full onboarding/wiki rebuild; unnecessary for a targeted documentation update.

### 2026-07-09 — Zero-Manual Harness Automation
**Decision:** Auto-bootstrap project llmwiki from safe docs and auto-spawn per-project Auto-Watch from MCP calls, with Windows logon task as fallback.
**Alternatives bỏ:** Requiring users to run `wiki_ingest` or `auto_watch.py` manually; conflicts with prompt-only workflow.

### 2026-07-12 — Prompt-only goal autopilot for Agent Harness
**Decision:** Add a prompt-only goal autopilot to Agent Harness as a single MCP tool `goal_autopilot` plus a hidden JSON state file `.harness_goal_state.json`, integrated into `auto_trigger` goal_alignment checks. The tool splits goals into parts, lets `auto_trigger(mode=max)` run full parallel checks per edit/part, and runs a final overall check before complete. The harness will orchestrate and verify around primary agents Claude/Gemini instead of directly editing files.
**Alternatives bỏ:** Full autonomous edit loop inside the harness; external daemon/UI; SQLite/queue for the first version.

### 2026-07-13 — Production readiness gate
**Decision:** Add standalone MCP tool `prod_readiness_gate` in `tools/prod.py` to aggregate final Auto-Pilot, security/env/secret, review, and release checks into one hard deploy verdict.
**Alternatives bỏ:** Folding production policy into `auto_trigger` or `goal_supervisor`; those stay edit-loop and goal-loop focused.

### 2026-07-13 — Lazy global rules merge
**Decision:** MCP server calls `merge_settings.lazy_merge_if_needed()` on `list_tools` and first tool call, guarded by `RULES_VERSION` stamp at `~/.claude/.harness_rules_version`, so Claude/Gemini/Codex rules update automatically after harness upgrades.
**Alternatives bỏ:** Requiring users to run `python merge_settings.py` manually after every tool/rule change; unconditional startup writes that slow or dirty every MCP launch.

### 2026-07-13 — Autonomous gap tools with Azure enrichment
**Decision:** Add `release_orchestrator`, `provenance_checker`, `auth_matrix_auditor`, `harness_trace_viewer`, and `incremental_refactor_guard` as static-first MCP tools that call Azure enrichment in `mode=max` or when `HARNESS_STATIC_LLM=1`.
**Alternatives bỏ:** Pure-offline gap tools; user explicitly wants harness to exploit Azure as much as possible while keeping smoke/fallback deterministic.

### 2026-07-13 — Direct prompt goal runner
**Decision:** Add `goal_runner` plus `goal_runner.py` so the harness can receive one prompt directly, initialize goal state, delegate implementation to an agent CLI, run Auto-Pilot checks, ask `goal_supervisor`, and finalize through `prod_readiness_gate`.
**Alternatives bỏ:** Relying only on Claude/Gemini/Codex rules to call `goal_autopilot(init)`; this leaves prompt startup dependent on the client session.

### 2026-07-13 — Harness ops layer
**Decision:** Add ops tools for context audit, ask_codebase preflight, run ledger, policy profiles, agent adapter inventory, benchmark dry-run, isolated patch safety, and harness doctor/status.
**Alternatives bỏ:** Keeping these checks as README-only manual steps; user wants the harness to own these lifecycle areas automatically.

### 2026-07-13 — Runtime-auto context and swarm hardening
**Decision:** Hard-wire lightweight context health into `ask_codebase`, doctor/ledger into `goal_runner`, redact ops paths before persistence/output, and validate swarm `target_files` with CAS-protected cancel.
**Alternatives bỏ:** Depending only on client-side rules to remember ops tools; allowing swarm sessions to proceed with empty or unsafe file scopes.

### 2026-07-13 — Contextual auto-trigger coverage
**Decision:** Expand `auto_trigger` and `prod_readiness_gate` from a small default check set to contextual DB/API/UI/CI/container/dependency/test/performance selectors, while skipping tools that lack required input.
**Alternatives bỏ:** Calling all 76 tools every time; too slow, expensive, noisy, and unsafe for URL/load/visual/doc-writing tools.
