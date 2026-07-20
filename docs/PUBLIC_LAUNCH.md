# Public Launch Playbook

This repository is branded as **LazyAgent**.

## Positioning

Short description:

> LazyAgent is an MCP control plane for coding agents: runtime profiles, memory,
> review gates, and automation for Claude Code, Codex, Gemini/Antigravity, and
> compatible clients.

Longer pitch:

> Coding agents are powerful, but they often run as isolated sessions with
> inconsistent memory, unclear model usage, and ad hoc safety checks. LazyAgent adds
> a local control plane: profiles decide what agents may do, MCP tools provide
> shared review/static/security workflows, and lesson memory carries fixes and
> decisions across sessions.

## Audiences

- Developers using Claude Code, Codex, Gemini, or Antigravity on Windows.
- Teams that want agent reviews and static checks without giving every agent
  unlimited model access.
- Power users who want local/global lessons, MCP tools, and runtime toggles.

## Launch Checklist

- Pin a short demo GIF or screenshot near the top of README.
- Add a "30 second install" section once the installer is stable for fresh VMs.
- Submit to MCP/Claude/Codex awesome lists.
- Post a short launch note to GitHub Discussions, Reddit, X/LinkedIn, and Hacker News.
- Keep the first public issue queue tidy: setup bugs, model/provider config, and docs gaps should get fast responses.

## Suggested Posts

GitHub/Reddit short post:

> I built LazyAgent, a Windows-first MCP control plane for coding agents. It gives
> Claude Code, Codex, Gemini/Antigravity, and compatible clients shared runtime
> profiles, lesson memory, review gates, static/security tools, and setup
> automation. The goal is simple: stop treating coding agents as isolated chat
> sessions and start running them with explicit profiles and reusable context.

Show HN style:

> Show HN: LazyAgent, an MCP control plane for coding agents
>
> LazyAgent is a local MCP harness for Claude Code, Codex, Gemini/Antigravity, and
> other coding agents. It adds runtime profiles, lesson memory, panel review,
> static/security checks, workflow routing, and Windows setup/toggle scripts.
> It starts safe by default with profile `off`; users opt in to higher
> automation levels when they want model-backed checks.

## Names

Chosen public name: **LazyAgent**.

Why this name works:

- memorable and short enough for a repo name
- describes the actual architecture
- leaves room for Claude, Codex, Gemini, and future agents
- contrasts nicely with the product promise: the user can be lazy because the agent system handles the checks

Avoid old/internal names in public-facing docs.
