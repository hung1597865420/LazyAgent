"""
Production readiness gate orchestration.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

from .auto import (
    CODE_EXTS,
    _basename,
    _docs_only,
    _ext,
    _norm_files,
    _safe_panel_files,
    _safe_scan_files,
    _summarize_result,
)


VERDICTS = {
    "ready_to_deploy",
    "fix_required",
    "blocked_needs_user",
    "deploy_then_verify",
    "rollback_required",
}
_SEVERITY = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
DEFAULT_TOOL_TIMEOUT_SECONDS = 300.0


def _has_any(text: str, words: set[str]) -> bool:
    lower = text.lower()
    return any(w in lower for w in words)


def _migration_files(files: list[str]) -> list[str]:
    out: list[str] = []
    for path in files:
        lower = path.replace("\\", "/").lower()
        if any(part in lower for part in ("migration", "migrations/", "migrate", "alembic/versions")):
            if lower.endswith((".py", ".sql")):
                out.append(path)
    return out


def _severity(value: Any) -> str:
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _SEVERITY:
            return v
    return "info"


def _findings(result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    findings = result.get("findings")
    return [f for f in findings if isinstance(f, dict)] if isinstance(findings, list) else []


def _highest_severity(result: Any) -> str:
    highest = "info"
    for finding in _findings(result):
        sev = _severity(finding.get("severity"))
        if _SEVERITY[sev] > _SEVERITY[highest]:
            highest = sev
    return highest


def _compact(name: str, result: Any, ok: bool) -> dict[str, Any]:
    summary = _summarize_result(result)
    summary["tool"] = name
    summary["ok"] = ok
    highest = _highest_severity(result)
    if highest != "info":
        summary["highest_severity"] = highest
    return summary


async def _run_check(name: str, coro) -> dict[str, Any]:
    actual_timeout = DEFAULT_TOOL_TIMEOUT_SECONDS
    task = asyncio.create_task(coro)
    try:
        try:
            timeout = float(os.getenv("HARNESS_PROD_TOOL_TIMEOUT", str(DEFAULT_TOOL_TIMEOUT_SECONDS)))
        except ValueError:
            timeout = DEFAULT_TOOL_TIMEOUT_SECONDS
        actual_timeout = max(0.01, min(timeout, 1800.0))
        result = await asyncio.wait_for(task, timeout=actual_timeout)
        ok = not (isinstance(result, dict) and result.get("error"))
        return {"tool": name, "ok": ok, "raw": result, "summary": _compact(name, result, ok)}
    except asyncio.TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return {
            "tool": name,
            "ok": False,
            "raw": {"error": "timeout", "timeout_seconds": actual_timeout},
            "summary": {"tool": name, "ok": False, "error": "timeout"},
        }
    except Exception as exc:
        return {
            "tool": name,
            "ok": False,
            "raw": {"error": str(exc)},
            "summary": {"tool": name, "ok": False, "error": str(exc)},
        }


async def _run_gate_jobs(jobs: list[Any]) -> list[dict[str, Any]]:
    if not jobs:
        return []
    return await asyncio.gather(*jobs)


def _hard_flags(checks: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    blockers: list[str] = []
    needs_user: list[str] = []
    warnings: list[str] = []

    for check in checks:
        tool = str(check.get("tool", "unknown"))
        raw = check.get("raw")
        if check.get("ok") is False:
            blockers.append(f"{tool}: check failed or errored")
            continue
        if not isinstance(raw, dict):
            continue

        verdict = str(raw.get("verdict", "")).lower()
        status = str(raw.get("status", "")).lower()
        if verdict in {"fix_first", "fix_required", "error"} or status == "failed":
            blockers.append(f"{tool}: verdict={verdict or status}")
        if verdict in {"breaking", "deprecated"}:
            needs_user.append(f"{tool}: public contract change is {verdict}")

        if raw.get("ok") is False:
            blockers.append(f"{tool}: ok=false")
        if raw.get("secrets_found"):
            blockers.append(f"{tool}: secrets_found")
        if raw.get("missing_in_env") or raw.get("missing_in_example"):
            blockers.append(f"{tool}: env parity drift")

        for finding in _findings(raw):
            sev = _severity(finding.get("severity"))
            category = str(finding.get("category") or finding.get("type") or "").lower()
            triage = str(finding.get("triage") or "").lower()
            if triage == "ask_user":
                needs_user.append(f"{tool}: {finding.get('file') or finding.get('location') or 'finding'} needs decision")
            if sev in {"critical", "high"}:
                blockers.append(f"{tool}: {sev} finding")
            elif sev == "medium":
                warnings.append(f"{tool}: medium finding")
            if category in {"non_reversible", "data_loss", "breaking"}:
                needs_user.append(f"{tool}: {category} risk")

    return blockers, needs_user, warnings


async def prod_readiness_gate(
    changed_files: list[str] | None = None,
    diff: str | None = None,
    task: str | None = None,
    context: str | None = None,
    staged: bool = False,
    since_commit: str = "",
    mode: str = "safe",
) -> dict[str, Any]:
    """Run a deploy gate and return a hard production readiness verdict."""
    from .analysis import env_parity_checker, secret_scanner, schema_drift
    from .auto import auto_trigger
    from .intel import a11y_auditor, i18n_auditor, license_scanner
    from .intel import sbom_generator
    from .quality import (
        breaking_change_detector,
        ci_pipeline_validator,
        container_linter,
        data_flow_taint_analyzer,
        dependency_graph_visualizer,
        migration_validator,
        openapi_spec_sync,
        performance_regression_detector,
        sql_query_analyzer,
    )
    from .review import panel_review
    from .security import config_security_audit
    from .testing import coverage_analyzer
    from .gap_tools import provenance_checker, release_orchestrator

    mode = (mode or "safe").strip().lower()
    if mode not in {"safe", "max"}:
        return {"error": "invalid_argument", "detail": "mode must be one of: safe, max"}
    since_commit = str(since_commit or "").strip()

    files = _norm_files(changed_files)
    text = "\n".join([task or "", context or "", diff or "", "\n".join(files)])
    code_files = [f for f in files if _ext(f) in CODE_EXTS]
    ui_files = [f for f in files if _ext(f) in {".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".vue"}]
    migration_files = _migration_files(files)
    scan_files = _safe_scan_files(files)
    panel_files = _safe_panel_files(code_files or files)
    docs_only = _docs_only(files)
    removed_safe_files = sorted(set(files) - set(scan_files))
    sensitive_only = bool(files) and len(removed_safe_files) == len(files)
    has_api = _has_any(text, {"api", "route", "endpoint", "openapi", "request", "response", "pydantic"})
    has_container = any(_basename(f) in {"dockerfile", "docker-compose.yml", "docker-compose.yaml"} for f in files)
    has_ci = any(".github/workflows" in f.replace("\\", "/").lower() or _basename(f) == ".gitlab-ci.yml" for f in files)
    selected: list[str] = []
    jobs = []

    def add(name: str, coro) -> None:
        selected.append(name)
        jobs.append(_run_check(name, coro))

    prod_managed_tools = {
        "a11y_auditor",
        "breaking_change_detector",
        "ci_pipeline_validator",
        "config_security_audit",
        "container_linter",
        "coverage_analyzer",
        "data_flow_taint_analyzer",
        "dependency_graph_visualizer",
        "env_parity_checker",
        "i18n_auditor",
        "license_scanner",
        "migration_validator",
        "openapi_spec_sync",
        "panel_review",
        "performance_regression_detector",
        "provenance_checker",
        "release_orchestrator",
        "schema_drift",
        "sbom_generator",
        "secret_scanner",
        "sql_query_analyzer",
    }
    if not (docs_only and mode == "safe"):
        add("auto_trigger", auto_trigger(
            changed_files=files,
            diff=diff,
            task=task,
            stage="final",
            mode=mode,
            exclude_tools=prod_managed_tools,
        ))
    if not (docs_only and mode == "safe"):
        add("config_security_audit", config_security_audit())
        add("env_parity_checker", env_parity_checker())
    if scan_files and not docs_only:
        add("secret_scanner", secret_scanner(paths=scan_files))
    if (panel_files or staged or since_commit or diff) and not docs_only:
        panel_kwargs: dict[str, Any] = {
            "diff": diff,
            "focus": "production readiness gate",
            "staged": staged,
            "since_commit": since_commit,
        }
        if panel_files:
            panel_kwargs["files"] = panel_files
        add("panel_review", panel_review(**panel_kwargs))
    if mode == "max":
        add("sbom_generator", sbom_generator())
        add("license_scanner", license_scanner())
        add("coverage_analyzer", coverage_analyzer())
        add("breaking_change_detector", breaking_change_detector(base_ref=since_commit or ""))
        add("performance_regression_detector", performance_regression_detector())
        if code_files:
            add("dependency_graph_visualizer", dependency_graph_visualizer(paths=code_files))
        if code_files and (has_api or "auth" in text.lower() or "request" in text.lower()):
            add("data_flow_taint_analyzer", data_flow_taint_analyzer(files=code_files))
        if code_files and ("sql" in text.lower() or "query" in text.lower() or migration_files):
            add("sql_query_analyzer", sql_query_analyzer(files=code_files))
        if code_files and ("basemodel" in text.lower() or "pydantic" in text.lower() or has_api):
            add("schema_drift", schema_drift())
        if ui_files:
            add("a11y_auditor", a11y_auditor(files=ui_files))
            add("i18n_auditor", i18n_auditor(files=ui_files))
        if code_files or has_api:
            add("openapi_spec_sync", openapi_spec_sync())
        if migration_files:
            add("migration_validator", migration_validator(paths=migration_files))
        if has_container or not files:
            add("container_linter", container_linter(paths=files if has_container else None))
        if has_ci or not files:
            add("ci_pipeline_validator", ci_pipeline_validator(paths=files if has_ci else None))
    checks = await _run_gate_jobs(jobs)
    blockers, needs_user, soft_warnings = _hard_flags(checks)
    critical = [
        c for c in checks
        if _highest_severity(c.get("raw")) == "critical"
        or (isinstance(c.get("raw"), dict) and c["raw"].get("secrets_found"))
    ]

    warnings = soft_warnings
    if docs_only and mode == "safe":
        warnings.append("docs-only safe gate skipped heavy deploy checks; use mode=max before a real production release")
    if diff and not files:
        warnings.append("diff was provided without changed_files; file-scoped checks may be incomplete")
    if removed_safe_files:
        warnings.append(f"Sensitive files excluded from LLM review/content scanners: {removed_safe_files[:10]}")
    if sensitive_only:
        warnings.append("sensitive-only change: content review skipped; rely on secret/env/config checks and inspect metadata manually")

    if critical:
        verdict = "rollback_required"
    elif needs_user:
        verdict = "blocked_needs_user"
    elif blockers:
        verdict = "fix_required"
    elif warnings:
        verdict = "deploy_then_verify"
    else:
        verdict = "ready_to_deploy"
    try:
        from .orchestrator import orchestrate
        orchestrator = orchestrate(
            stage="prod_gate",
            files=files,
            diff=diff,
            task="\n".join([task or "", context or ""]),
            mode=mode,
            results={"results": checks, "blockers_count": len(set(blockers)), "verdict": verdict},
        )
    except Exception as exc:
        orchestrator = {"status": "skipped", "error": str(exc)}

    return {
        "status": "completed",
        "verdict": verdict,
        "mode": mode,
        "files": files,
        "selected_tools": selected,
        "blockers": sorted(set(blockers)),
        "blockers_count": len(set(blockers)),
        "needs_user_decision": sorted(set(needs_user)),
        "needs_user_count": len(set(needs_user)),
        "next_actions": _next_actions(verdict),
        "results": [c["summary"] for c in checks],
        "warnings": sorted(set(warnings)),
        "staged": bool(staged),
        "since_commit": since_commit or "",
        "orchestrator": orchestrator,
    }


def _next_actions(verdict: str) -> list[str]:
    if verdict == "ready_to_deploy":
        return ["Deploy is allowed; keep normal post-deploy monitoring."]
    if verdict == "deploy_then_verify":
        return ["Deploy only with explicit post-deploy verification and rollback plan."]
    if verdict == "blocked_needs_user":
        return ["Ask the user to decide the listed production risk before deploying."]
    if verdict == "rollback_required":
        return ["Stop deploy; if already deployed, rollback before continuing."]
    return ["Fix blockers, rerun prod_readiness_gate, then deploy only after a non-blocking verdict."]
