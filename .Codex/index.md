## File map
- README.md — Deep technical guide for install, architecture, automation, memory, multi-agent setup, and tools.
- mcp_server.py — MCP server registry and tool dispatch for all exposed harness tools.
- agents.py — 12-agent Azure model orchestration, retries, timeouts, FinOps logging.
- config.py — Environment variables, model defaults, Azure clients, workspace root.
- tools/ — Modular tool implementations for review, security, testing, devops, wiki, analysis, quality.
- tools/goal.py — Prompt-only goal autopilot state machine and alignment check.
- tools/runner.py — Direct prompt runner that drives goal, agent CLI, checks, supervisor, and final gate.
- tools/ops.py — Harness ops tools for doctor, context audit, ledger, profiles, adapters, benchmark, and patch safety.
- tools/prod.py — Production readiness gate that aggregates final checks into a hard deploy verdict.
- tools/gap_tools.py — Static-first production gap tools with Azure enrichment in max mode.
- install.ps1 — Windows installer: dependencies, MCP registration, global Claude config, smoke test.
- merge_settings.py — Global Claude/Gemini/Codex instruction merge with RULES_VERSION stamp.
- smoke_test.py — Offline smoke checks for MCP registry and support tools.
- llmwiki_tool.py — Local/global llmwiki ingest, query, and lint.
- auto_watch.py — File watcher that triggers Auto-Pilot outside model calls.

## Architecture
Claude/Codex/Gemini MCP client -> mcp_server.py -> tools/* + agents.py -> Azure AI Foundry / static analyzers.
Goal flow: prompt -> goal_runner or goal_autopilot(init) -> .harness_goal_state.json -> agent/check/supervisor loop.
Prod flow: release/prod prompt -> prod_readiness_gate -> final auto/security/review/release/provenance checks -> hard verdict.

## Constraints / Gotchas
- `.env` contains secrets and must not be committed.
- MCP is registered with `--scope user`; `WORKSPACE_ROOT=` should usually stay empty so runtime project detection works.
- Some clients lazy-load MCP tools, so a tool may not appear until capability discovery/search.
- `.harness_goal_state.json` is local runtime state for one active workspace goal.
- Restart MCP clients after adding tools; cached sessions will not see new schemas.
- MCP server lazy-merges global rules on `list_tools`/first tool call, but existing client sessions may still need restart.
- Gap tools keep `mode=safe` offline for smoke, but `mode=max` uses Azure enrichment by default.
