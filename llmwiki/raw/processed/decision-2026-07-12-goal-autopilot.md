# Prompt-only goal autopilot for Agent Harness

Date: 2026-07-12

Decision: add a prompt-only goal autopilot as MCP tool `goal_autopilot`, backed by `.harness_goal_state.json`, and integrate active-goal alignment checks into `auto_trigger`.

Intent:
- User enters one coding prompt.
- Claude/Gemini rules call `goal_autopilot(mode="init", goal="<prompt>")` before coding.
- `goal_autopilot(init)` splits the goal into smaller parts and stores the current part.
- Auto-Watch/Auto-Pilot call `auto_trigger(mode="max")` after edits; `auto_trigger` runs normal checks in parallel and adds `goal_alignment` when a goal is active.
- Before final response, the primary agent calls `goal_autopilot(mode="complete", changed_files=[...], diff=...)`; the tool runs a final overall `auto_trigger(stage="final", mode="max")` before closing the goal.
- If the task is genuinely stuck, the primary agent calls `goal_autopilot(mode="block")`.

Rejected:
- Harness directly editing source files in a long autonomous loop.
- New UI.
- External daemon beyond existing Auto-Watch.
- SQLite/queue for the first version.

Source files:
- `tools/goal.py`
- `tools/auto.py`
- `mcp_server.py`
- `merge_settings.py`
- `README.md`
