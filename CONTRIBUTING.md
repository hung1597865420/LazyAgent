# Contributing

Thanks for helping improve Agent Harness. This project is Windows-first and
agent-focused, so changes should keep setup predictable, profiles explicit, and
runtime data out of git.

## Development Setup

1. Install Python 3.10+ and Git.
2. Create a local `.env` from `.env.example`.
3. Run `python -m pip install -r requirements.txt`.
4. Keep `harness.features.json` on a low profile unless you intentionally need
   LLM-backed checks.
5. Run `python smoke_test.py` before opening a pull request.

## Pull Requests

- Keep changes scoped to one feature or fix.
- Do not commit `.env`, API keys, exported cost reports, local lesson DBs, logs,
  or `.harness_*` runtime artifacts.
- Update README or CHANGELOG when behavior, setup, profiles, or MCP tools change.
- Preserve compatibility shims when removing public MCP tools or import paths.
- Prefer static/local validation for routine checks; use LLM-backed review only
  when the selected runtime profile allows it.

## Verification

For code changes, run:

```powershell
python -m py_compile agents.py config.py harness_hook.py mcp_server.py merge_settings.py smoke_test.py support_tools.py tools\*.py
python smoke_test.py
```

For documentation-only changes, at minimum check formatting and run a focused
grep for secrets in the staged diff.
