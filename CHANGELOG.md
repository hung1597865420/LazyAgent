# Changelog

All notable project changes should be recorded here before public releases.

## Unreleased

- Added LazyAgent public branding, launch playbook, issue templates, and pull request template.
- Added logo/social preview SVG assets and a 60-second demo script.

## 0.1.0 - 2026-07-20

- Reworked runtime profile policy for Claude, Codex, Gemini/Antigravity and
  other agents from a shared rule source.
- Added public-safe setup defaults with profile `off`.
- Added Hallmark, Spec Kit, UI skill, workflow, and bug reproduction routing.
- Added lesson quality gates, prompt-injection sanitization, and global lesson
  fallback validation.
- Removed router quota/costguard behavior; kept `router_quota_status` as a
  deprecated compatibility shim.
- Added public documentation: security policy, contributing guide, code of
  conduct, and changelog.
- Added MIT license and GitHub release metadata for public launch.

## Release Process

1. Run `python smoke_test.py`.
2. Confirm `harness.features.json` is not staged with a local high-cost profile.
3. Confirm staged diff contains no secrets.
4. Tag the commit, then create a GitHub release from the changelog summary.
