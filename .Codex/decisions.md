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
