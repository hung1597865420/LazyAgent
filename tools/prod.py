"""
Production readiness gate orchestration.
"""
from __future__ import annotations

import asyncio
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
    try:
        result = await coro
        ok = not (isinstance(result, dict) and result.get("error"))
        return {"tool": name, "ok": ok, "raw": result, "summary": _compact(name, result, ok)}
    except Exception as exc:
        return {
            "tool": name,
            "ok": False,
            "raw": {"error": str(exc)},
            "summary": {"tool": name, "ok": False, "error": str(exc)},
        }


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
    from .analysis import env_parity_checker, secret_scanner
    from .auto import auto_trigger
    from .intel import sbom_generator
    from .quality import (
        breaking_change_detector,
        ci_pipeline_validator,
        container_linter,
        migration_validator,
        openapi_spec_sync,
    )
    from .review import panel_review
    from .security import config_security_audit

    mode = (mode or "safe").strip().lower()
    if mode not in {"safe", "max"}:
        return {"error": "invalid_argument", "detail": "mode must be one of: safe, max"}
    since_commit = str(since_commit or "").strip()

    files = _norm_files(changed_files)
    text = "\n".join([task or "", context or "", diff or "", "\n".join(files)])
    code_files = [f for f in files if _ext(f) in CODE_EXTS]
    migration_files = _migration_files(files)
    scan_files = _safe_scan_files(files)
    panel_files = _safe_panel_files(code_files or files)
    docs_only = _docs_only(files)
    has_api = _has_any(text, {"api", "route", "endpoint", "openapi", "request", "response", "pydantic"})
    has_container = any(_basename(f) in {"dockerfile", "docker-compose.yml", "docker-compose.yaml"} for f in files)
    has_ci = any(".github/workflows" in f.replace("\\", "/").lower() or _basename(f) == ".gitlab-ci.yml" for f in files)
    has_env = any(_basename(f) in {".env", ".env.example"} for f in files)

    selected: list[str] = []
    jobs = []

    def add(name: str, coro) -> None:
        selected.append(name)
        jobs.append(_run_check(name, coro))

    add("auto_trigger", auto_trigger(changed_files=files, diff=diff, task=task, stage="final", mode=mode))
    if not (docs_only and mode == "safe"):
        add("config_security_audit", config_security_audit())
        add("env_parity_checker", env_parity_checker())
    if scan_files and not docs_only:
        add("secret_scanner", secret_scanner(paths=scan_files))
    if (panel_files or staged or since_commit or diff) and not docs_only:
        add("panel_review", panel_review(
            files=panel_files,
            diff=diff,
            focus="production readiness gate",
            staged=staged,
            since_commit=since_commit,
        ))
    if mode == "max":
        add("sbom_generator", sbom_generator())
        add("breaking_change_detector", breaking_change_detector(base_ref=since_commit or ""))
        if code_files or has_api:
            add("openapi_spec_sync", openapi_spec_sync())
        if migration_files:
            add("migration_validator", migration_validator(paths=migration_files))
        if has_container or not files:
            add("container_linter", container_linter(paths=files if has_container else None))
        if has_ci or not files:
            add("ci_pipeline_validator", ci_pipeline_validator(paths=files if has_ci else None))
    checks = await asyncio.gather(*jobs) if jobs else []
    blockers, needs_user, soft_warnings = _hard_flags(checks)
    critical = [
        c for c in checks
        if _highest_severity(c.get("raw")) == "critical"
        or (isinstance(c.get("raw"), dict) and c["raw"].get("secrets_found"))
    ]

    warnings = soft_warnings
    if docs_only and mode == "safe":
        warnings.append("docs-only safe gate skipped heavy deploy checks; use mode=max before a real production release")
    if panel_files != (code_files or files) or scan_files != files:
        warnings.append(".env-like files were not sent to LLM review/content scanners")

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
