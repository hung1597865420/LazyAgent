"""
Auto-pilot orchestration for contextual harness checks.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any


DOC_EXTS = {".md", ".txt", ".rst", ".adoc"}
CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".go", ".rs",
    ".cs", ".php", ".rb", ".swift", ".kt", ".kts", ".sql", ".html", ".css",
}
SENSITIVE_NAMES = {".env", ".env.local", ".env.production", ".env.development", ".env.test"}


def _auto_enabled() -> bool:
    return os.getenv("HARNESS_AUTO_PILOT", "1").strip().lower() not in {"0", "false", "no", "off"}


def _norm_files(files: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in files or []:
        if not isinstance(item, str):
            continue
        f = item.strip().replace("\\", "/")
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _ext(path: str) -> str:
    name = _basename(path)
    if name in SENSITIVE_NAMES:
        return name
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _basename(path: str) -> str:
    return path.strip().replace("\\", "/").rsplit("/", 1)[-1].lower()


def _docs_only(files: list[str]) -> bool:
    return bool(files) and all(_ext(f) in DOC_EXTS for f in files)


def _safe_panel_files(files: list[str]) -> list[str]:
    return [f for f in files if _ext(f) not in SENSITIVE_NAMES]


def _safe_scan_files(files: list[str]) -> list[str]:
    return [f for f in files if _ext(f) not in SENSITIVE_NAMES]


def _has_any(text: str, words: set[str]) -> bool:
    lower = text.lower()
    return any(w in lower for w in words)


def _summarize_result(result: Any) -> dict:
    if not isinstance(result, dict):
        return {"ok": True, "result_type": type(result).__name__}
    summary: dict[str, Any] = {"ok": "error" not in result}
    for key in (
        "error", "status", "message", "verdict", "part_status", "summary", "score", "findings_count", "errors_count",
        "dead_symbols_count", "issues_count", "secrets_found", "warnings",
    ):
        if key in result:
            summary[key] = result[key]
    if "findings" in result and isinstance(result["findings"], list):
        summary["findings_count"] = len(result["findings"])
    return summary


async def _run_named(name: str, coro) -> dict:
    try:
        result = await coro
        return {"tool": name, **_summarize_result(result)}
    except Exception as e:
        return {"tool": name, "ok": False, "error": str(e)}


async def auto_trigger(
    changed_files: list[str] | None = None,
    diff: str | None = None,
    task: str | None = None,
    stage: str = "post_edit",
    mode: str | None = None,
) -> dict:
    """Run contextual checks automatically after edits.

    mode:
    - max: run aggressive default checks for code changes.
    - safe: skip panel/devops unless clear risk keywords are present.
    """
    if not _auto_enabled():
        return {"status": "skipped", "reason": "HARNESS_AUTO_PILOT=0"}

    from .goal import check_goal, get_active_goal, goal_progress_summary
    from .review import panel_review
    from .analysis import (
        complexity_analyzer,
        dead_code_scanner,
        env_parity_checker,
        secret_scanner,
    )
    from .devops import devops_pipeline
    from .quality import duplicate_code_scanner
    from .security import config_security_audit
    from .gap_tools import (
        auth_matrix_auditor,
        harness_trace_viewer,
        incremental_refactor_guard,
        provenance_checker,
        release_orchestrator,
    )

    files = _norm_files(changed_files)
    mode = (mode or os.getenv("HARNESS_AUTO_MODE", "max")).strip().lower()
    stage = (stage or "post_edit").strip().lower()
    active_goal = get_active_goal()
    goal_text = active_goal.goal if active_goal else ""
    goal_summary = goal_progress_summary(active_goal) if active_goal else ""
    task_with_goal = f"{goal_summary}\n\n{task or ''}".strip() if goal_summary else task
    text = "\n".join([goal_text, task or "", diff or "", "\n".join(files)])

    if _docs_only(files) and mode != "max" and not active_goal:
        return {"status": "skipped", "reason": "docs-only change", "files": files}

    code_files = [f for f in files if _ext(f) in CODE_EXTS]
    panel_files = _safe_panel_files(code_files or files)
    has_env = any(_ext(f) in SENSITIVE_NAMES or _basename(f) == ".env.example" for f in files)
    has_config = has_env or any(
        f.lower().endswith((
            "dockerfile", "docker-compose.yml", ".yaml", ".yml", ".toml", ".ini", ".json",
        ))
        for f in files
    )
    has_security = _has_any(text, {"auth", "jwt", "session", "token", "secret", "password", "cors", "rls", "crypto"})
    has_db = _has_any(text, {"sql", "migration", "alembic", "schema", "transaction", "query", "orm"})
    has_refactor = _has_any(text, {"refactor", "rename", "delete", "remove", "dead code", "duplicate"})
    has_api = _has_any(text, {"route", "endpoint", "api", "request", "response", "pydantic", "openapi"})
    has_release = _has_any(text, {"release", "deploy", "production", "prod-ready", "tag", "changelog"})
    has_trace = _has_any(text, {"trace", "stack trace", "timeout", "rate-limit", "latency", "slow", "500", "exception"})
    risky = has_security or has_db or has_api or has_refactor or len(code_files) > 1

    selected: list[str] = []
    jobs = []

    def add(name: str, coro) -> None:
        selected.append(name)
        jobs.append(_run_named(name, coro))

    scan_files = _safe_scan_files(files)

    if active_goal:
        add("goal_alignment", check_goal(changed_files=files, diff=diff, task=task_with_goal))
    if (mode == "max" or has_config or has_security) and scan_files:
        add("secret_scanner", secret_scanner(paths=scan_files))
    if mode == "max" or has_env:
        add("env_parity_checker", env_parity_checker())
    if mode == "max" or has_config or has_security:
        add("config_security_audit", config_security_audit())
    if code_files and (mode == "max" or risky):
        add("complexity_analyzer", complexity_analyzer(paths=code_files))
    if mode == "max" and code_files:
        add("devops_pipeline", devops_pipeline())
    if has_refactor or (mode == "max" and len(code_files) >= 2):
        add("dead_code_scanner", dead_code_scanner())
        add("duplicate_code_scanner", duplicate_code_scanner())
        add("incremental_refactor_guard", incremental_refactor_guard(files=code_files, diff=diff, mode=mode))
    if (mode == "max" and has_security and has_api) or _has_any(text, {"auth matrix", "permission matrix", "ownership check"}):
        add("auth_matrix_auditor", auth_matrix_auditor(files=code_files or files, diff=diff, context=task_with_goal, mode=mode))
    if has_release or (mode == "max" and stage in {"final", "pre_complete"}):
        add("release_orchestrator", release_orchestrator(changed_files=files, diff=diff, context=task_with_goal, mode=mode))
    if has_release and mode == "max":
        add("provenance_checker", provenance_checker(files=files, context=task_with_goal, mode=mode))
    if has_trace:
        add("harness_trace_viewer", harness_trace_viewer(limit=20, mode=mode))
    if panel_files and (mode == "max" or stage in {"final", "pre_complete"} or risky):
        focus_bits = []
        if has_security:
            focus_bits.append("security")
        if has_db:
            focus_bits.append("data integrity / database")
        if has_api:
            focus_bits.append("API contract")
        if active_goal:
            focus_bits.append(f"goal alignment: {goal_summary or goal_text}")
        add("panel_review", panel_review(files=panel_files, focus=", ".join(focus_bits) or None))

    if not jobs:
        return {"status": "skipped", "reason": "no matching automatic checks", "files": files}

    results = await asyncio.gather(*jobs)
    goal_changed_mid_run = any(
        r.get("tool") == "goal_alignment" and r.get("status") == "idle"
        for r in results
    )
    if goal_changed_mid_run:
        results = [r for r in results if r.get("tool") != "goal_alignment"]
        selected = [name for name in selected if name != "goal_alignment"]
    blockers = [
        r for r in results
        if r.get("ok") is False or str(r.get("verdict", "")).lower() == "fix_first"
    ]
    warnings = []
    if panel_files != (code_files or files) or scan_files != files:
        warnings.append(".env-like files were kept out of content scanners/review to avoid exposing secret values")
    if goal_changed_mid_run:
        warnings.append("active goal changed or completed while auto_trigger was running; dropped stale goal_alignment result")
    return {
        "status": "completed",
        "mode": mode,
        "stage": stage,
        "files": files,
        "goal_active": bool(active_goal),
        "goal": goal_text or None,
        "selected_tools": selected,
        "results": results,
        "blockers_count": len(blockers),
        "warnings": warnings,
    }
