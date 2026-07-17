# 170726-runtime-feature-flags
**Type:** draft
**Status:** proposed
**Tags:** source-command-safe-change, output-report
**Proposed:** 2026-07-17

## What
Added a repo/project runtime feature control file for background Agent Harness automation.

## Output
- `harness.features.json` controls Auto-Pilot, Auto-Watch, and optional LLM enrichment.
- `harness-toggle.bat` provides Windows profiles plus per-feature toggles for LLM, FinOps, hooks, lessons, Auto-Pilot, Auto-Watch, static LLM enrichment, wiki/index preferences, and dashboard actions.
- `runtime_flags.py` resolves project file first, then harness install file, with env fallback.
- Auto-Watch can now exit when the feature file disables it.

## Files
| File | Action |
|------|--------|
| `runtime_flags.py` | created |
| `harness.features.json` | created |
| `harness-toggle.bat` | created |
| `auto_watch.py` | modified |
| `mcp_server.py` | modified |
| `tools/auto.py` | modified |
| `tools/analysis.py` | modified |
| `tools/devops.py` | modified |
| `tools/gap_tools.py` | modified |
| `smoke_test.py` | modified |
| `README.md` | modified |
| `.env.example` | modified |

## Notes
- Invoked via: `/safe-change` skill

## Origin
- **Draft:** `wiki/sources/draft/170726-runtime-feature-flags.md`
- **Commit:** _(filled by verify-before-commit)_
- **Date promoted:** _(filled by verify-before-commit)_
