# Security Policy

## Reporting

Please do not open public issues that contain credentials, private endpoints, exported cost reports, logs with API keys, or local machine paths. Report sensitive findings privately to the repository owner and include:

- affected file/tool
- reproduction steps
- expected vs actual behavior
- whether credentials, user data, or local runtime files may be exposed

## Secrets

This repository is designed to keep real credentials outside git:

- `.env` is ignored and must stay local.
- `.env.example` uses placeholder values only.
- `ROUTER_API_KEY`, cookies, bearer tokens, 9Router dashboard credentials, and provider keys must never be committed.
- If a real key is committed or pasted into a public issue, rotate it immediately.

## Runtime Data

Local runtime artifacts are not intended for publication:

- `.harness_*.db`
- `.harness_*.jsonl`
- `.harness_*.log`
- `.harness_*.pid`
- `.harness_*.lock`
- `.harness_smoke/`
- `.harness_worktree_*/`
- local cost reports or exported spreadsheets

Lesson and wiki context is treated as untrusted retrieval before injection into LLM prompts. Prompt-control phrases and secret-like values are scrubbed, but users should still avoid storing sensitive data in memory files.

## Safe Defaults

Public installs should start from profile `off`. Higher profiles enable more automation and may call LLM providers or background checks:

- `off`: no model calls, lessons, hooks runtime, FinOps writes, Auto-Pilot, or watcher.
- `light`/`standard`: static-first daily use.
- `balanced`/`review`/`heavy`/`max`: progressively more LLM and background automation.

Agents must not change `harness.features.json` unless the current user explicitly asks, and CLI writes require `HARNESS_ALLOW_PROFILE_WRITE=1`.
