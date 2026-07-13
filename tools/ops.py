"""Operational tools for harness self-management and evaluation."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from .core import _assemble_context, _get_active_workspace, _run_cmd_safe
from .goal import load_goal_state
from .runner import RUNNER_LOCK_FILE, _read_lock

LEDGER_FILE = ".harness_run_ledger.jsonl"

POLICY_PROFILES: dict[str, dict[str, Any]] = {
    "fast": {"mode": "safe", "max_iterations": 3, "final_prod_gate": False, "azure": "minimal"},
    "balanced": {"mode": "max", "max_iterations": 8, "final_prod_gate": True, "azure": "contextual"},
    "prod": {"mode": "max", "max_iterations": 12, "final_prod_gate": True, "azure": "heavy"},
    "paranoid": {"mode": "max", "max_iterations": 20, "final_prod_gate": True, "azure": "max"},
}


def _root() -> Path:
    return Path(_get_active_workspace()).resolve()


def _display_path(value: str) -> str:
    text = str(value)
    root = str(_root())
    home = str(Path.home())
    if root and text.startswith(root):
        text = "<workspace>" + text[len(root):]
    if home and text.startswith(home):
        text = "~" + text[len(home):]
    return text.replace("\\", "/")


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        text = _display_path(value)
        return text[:4000]
    if isinstance(value, list):
        return [_redact_value(item) for item in value[:200]]
    if isinstance(value, dict):
        return {str(k)[:120]: _redact_value(v) for k, v in value.items()}
    return value


def append_run_ledger(entry: dict[str, Any]) -> None:
    payload = {"ts": time.time(), **_redact_value(entry)}
    path = _root() / LEDGER_FILE
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def _read_ledger(limit: int = 20) -> list[dict[str, Any]]:
    path = _root() / LEDGER_FILE
    if not path.exists():
        return []
    rows = []
    try:
        wanted = max(1, min(200, int(limit)))
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, ValueError):
        return []
    for line in reversed(lines):
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
                if len(rows) >= wanted:
                    break
        except json.JSONDecodeError:
            continue
    return list(reversed(rows))


async def run_ledger(limit: int = 20) -> dict[str, Any]:
    """Return recent goal/benchmark runner ledger entries."""
    rows = _read_ledger(limit)
    return {"status": "completed", "entries": rows, "entries_count": len(rows), "file": _display_path(str(_root() / LEDGER_FILE))}


async def policy_profile(profile: str = "balanced") -> dict[str, Any]:
    """Return policy profile defaults for runner/check intensity."""
    key = (profile or "balanced").strip().lower()
    if key not in POLICY_PROFILES:
        return {"error": "invalid_argument", "detail": f"profile must be one of: {', '.join(POLICY_PROFILES)}"}
    return {"status": "completed", "profile": key, "settings": POLICY_PROFILES[key], "profiles": POLICY_PROFILES}


def _lock_status() -> dict[str, Any]:
    path = _root() / RUNNER_LOCK_FILE
    data = _read_lock(path) if path.exists() else {}
    return {"locked": path.exists(), "path": _display_path(str(path)), "owner": _redact_value(data)}


async def goal_runner_control(action: str = "status", prompt: str | None = None, mode: str = "max", dry_run: bool = False) -> dict[str, Any]:
    """Status/resume/cancel-stale wrapper for direct goal runner."""
    action = (action or "status").strip().lower()
    state = load_goal_state()
    if action == "status":
        return {"status": "completed", "goal": state.to_dict() if state else None, "lock": _lock_status(), "ledger": _read_ledger(5)}
    if action == "cancel_stale":
        lock = _lock_status()
        lock_path = _root() / RUNNER_LOCK_FILE
        owner = lock.get("owner") or {}
        pid = int(owner.get("pid") or 0) if isinstance(owner, dict) else 0
        if lock["locked"] and pid > 0:
            from .runner import _pid_alive

            if _pid_alive(pid):
                return {"status": "noop", "reason": "lock owner is still alive", "lock": lock}
            try:
                lock_path.unlink()
                return {"status": "cancelled_stale_lock", "lock": lock}
            except OSError as exc:
                return {"status": "failed", "error": str(exc), "lock": lock}
        return {"status": "noop", "reason": "lock has owner metadata or is not present", "lock": lock}
    if action == "resume":
        if not state and not prompt:
            return {"error": "invalid_argument", "detail": "No active goal to resume; provide prompt."}
        from .runner import goal_runner

        return await goal_runner(prompt or state.goal, mode=mode, dry_run=dry_run, resume=True)
    return {"error": "invalid_argument", "detail": "action must be one of: status, resume, cancel_stale"}


async def agent_adapters() -> dict[str, Any]:
    """List supported coding-agent CLI adapters and detection state."""
    adapters = {
        "claude": {"command": ["claude", "-p", "{prompt}"], "available": bool(shutil.which("claude"))},
        "gemini": {"command": ["gemini", "-p", "{prompt}"], "available": bool(shutil.which("gemini"))},
        "codex": {"command": ["codex", "exec", "{prompt}"], "available": bool(shutil.which("codex"))},
        "custom": {"env": "HARNESS_GOAL_AGENT_CMD", "available": bool(os.getenv("HARNESS_GOAL_AGENT_CMD"))},
    }
    return {"status": "completed", "adapters": adapters}


async def context_auditor(question: str = "", files: list[str] | None = None, context: str | None = None) -> dict[str, Any]:
    """Audit assembled context size, warning count, and likely usefulness without calling Azure."""
    ctx, warnings = _assemble_context(files=files, context=context or question)
    size = len(ctx.encode("utf-8", errors="replace"))
    has_citations = ":1:" in ctx or any(f"`{f}`" in ctx for f in files or [])
    verdict = "lean"
    if size > 350_000:
        verdict = "too_large"
    elif files and not ctx:
        verdict = "missing"
    elif warnings:
        verdict = "review_warnings"
    return {
        "status": "completed",
        "verdict": verdict,
        "bytes": size,
        "warnings": warnings,
        "warnings_count": len(warnings),
        "files": files or [],
        "has_goal_context": "=== GOAL PROGRESS ===" in ctx,
        "has_line_context": has_citations,
    }


async def ask_codebase_health(question: str = "harness codebase health", files: list[str] | None = None, context: str | None = None) -> dict[str, Any]:
    """Dry-run the local ask_codebase context path to catch overlarge/weak context before Azure."""
    audit = await context_auditor(question=question, files=files, context=context)
    advice = []
    if audit["verdict"] == "too_large":
        advice.append("Narrow files or rely on ask_codebase auto-selection before Azure.")
    if audit["warnings_count"]:
        advice.append("Review warnings; skipped files may remove needed evidence.")
    if not advice:
        advice.append("Context path looks usable; Azure timeout risk is mostly model/quota, not local context assembly.")
    return {"status": "completed", "audit": audit, "advice": advice}


async def patch_safety_check(patch: str, files: list[str] | None = None) -> dict[str, Any]:
    """Apply a patch in an isolated git worktree and run local tests; never mutates the main tree."""
    if not isinstance(patch, str) or not patch.strip():
        return {"error": "invalid_argument", "detail": "patch is required"}
    from .core import _apply_and_test_isolated

    ok, message, test_log = _apply_and_test_isolated(patch, files)
    return {"status": "completed", "safe": ok, "message": message, "test_log": test_log[-4000:]}


async def benchmark_runner(tasks: list[str] | None = None, mode: str = "safe", dry_run: bool = True) -> dict[str, Any]:
    """Run a tiny benchmark suite through goal_runner; dry-run by default."""
    from .runner import goal_runner

    mode = (mode or "safe").strip().lower()
    if mode not in {"safe", "max"}:
        return {"error": "invalid_argument", "detail": "mode must be one of: safe, max"}
    tasks = [str(t).strip() for t in (tasks or []) if str(t).strip()] or [
        "Audit context injection for one file",
        "Run production readiness smoke",
        "Check goal runner status",
    ]
    results = []
    started = time.time()
    for task in tasks[:50]:
        res = await goal_runner(task, mode=mode, dry_run=dry_run, max_iterations=1, final_prod_gate=False)
        results.append({"task": task, "status": res.get("status")})
    summary = {
        "tasks": len(results),
        "completed": sum(1 for r in results if r["status"] == "completed"),
        "blocked": sum(1 for r in results if str(r["status"]).startswith("blocked")),
        "duration_ms": int((time.time() - started) * 1000),
        "effective_mode": mode,
        "dry_run": dry_run,
    }
    append_run_ledger({"tool": "benchmark_runner", "summary": summary, "results": results})
    return {"status": "completed", "summary": summary, "results": results}


async def harness_doctor() -> dict[str, Any]:
    """Self-check harness install/runtime readiness."""
    rc, head, git_err = _run_cmd_safe(["git", "rev-parse", "--short", "HEAD"], cwd=str(_root()))
    adapters = await agent_adapters()
    checks = {
        "workspace": _display_path(str(_root())),
        "git": {"ok": rc == 0, "head": head.strip(), "error": git_err},
        "azure_env": bool(os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_API_KEY")),
        "responses_env": bool(os.getenv("AZURE_RESPONSES_ENDPOINT")),
        "rules_version": _rules_version(),
        "goal_state": bool(load_goal_state()),
        "runner_lock": _lock_status(),
        "agent_adapters": adapters["adapters"],
    }
    problems = []
    if not checks["git"]["ok"]:
        problems.append("workspace is not a git repo")
    if not checks["azure_env"]:
        problems.append("Azure env is missing; LLM tools will degrade/fail")
    if not any(v.get("available") for v in checks["agent_adapters"].values() if isinstance(v, dict)):
        problems.append("no agent CLI adapter detected; goal_runner needs HARNESS_GOAL_AGENT_CMD or claude/gemini/codex")
    return {"status": "completed", "ready": not problems, "checks": checks, "problems": problems}


def _rules_version() -> dict[str, Any]:
    try:
        import merge_settings

        return {"current": merge_settings.RULES_VERSION, "installed": merge_settings.installed_rules_version()}
    except Exception as exc:
        return {"error": str(exc)}
