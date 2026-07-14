"""Internal autonomy intelligence layer.

No MCP tool is exposed here; auto_trigger/prod/runner call it automatically.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .core import _get_active_workspace, load_relevant_lessons_context

ORCH_FILE = ".harness_orchestrator.jsonl"


def _root() -> Path:
    return Path(_get_active_workspace()).resolve()


def _hash(text: str, n: int = 16) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()[:n]


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace(str(Path.home()), "~")[:3000]
    if isinstance(value, list):
        return [_redact(v) for v in value[:100]]
    if isinstance(value, dict):
        return {str(k)[:80]: _redact(v) for k, v in value.items()}
    return value


def _append(entry: dict[str, Any]) -> None:
    path = _root() / ORCH_FILE
    payload = {"ts": time.time(), **_redact(entry)}
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def _has_any(text: str, words: set[str]) -> bool:
    low = (text or "").lower()
    return any(w in low for w in words)


def _classify(files: list[str], text: str) -> list[str]:
    tags: list[str] = []
    lower_files = " ".join(f.lower() for f in files)
    groups = {
        "security": {"auth", "jwt", "token", "secret", "password", "cors", "crypto", ".env"},
        "api": {"api", "route", "endpoint", "openapi", "request", "response"},
        "db": {"sql", "migration", "alembic", "schema", "transaction", "orm"},
        "ui": {".tsx", ".jsx", ".html", ".css", "a11y", "i18n"},
        "release": {"release", "deploy", "production", "prod", "rollback"},
        "debug": {"trace", "exception", "timeout", "error", "500", "failed"},
        "refactor": {"refactor", "rename", "delete", "remove", "breaking"},
    }
    hay = f"{text}\n{lower_files}"
    for name, terms in groups.items():
        if _has_any(hay, terms):
            tags.append(name)
    return tags or ["general"]


def _route(tags: list[str], stage: str) -> dict[str, Any]:
    tools = ["context_auditor", "ask_codebase_health"]
    if "security" in tags:
        tools += ["secret_scanner", "config_security_audit", "data_flow_taint_analyzer"]
    if "api" in tags:
        tools += ["openapi_spec_sync", "api_contract_tester"]
    if "db" in tags:
        tools += ["migration_validator", "sql_query_analyzer", "schema_drift"]
    if "ui" in tags:
        tools += ["a11y_auditor", "i18n_auditor"]
    if "release" in tags or stage in {"final", "pre_complete"}:
        tools += ["prod_readiness_gate", "release_orchestrator", "provenance_checker"]
    if "debug" in tags:
        tools += ["harness_trace_viewer", "telemetry_debugger"]
    if "refactor" in tags:
        tools += ["incremental_refactor_guard", "dead_code_scanner", "duplicate_code_scanner"]
    return {"tags": tags, "recommended_tools": list(dict.fromkeys(tools))}


def _policy(tags: list[str], mode: str) -> dict[str, Any]:
    ask_user = sorted(set(tags) & {"security", "release", "db"})
    forbidden = ["raw .env content in LLM context", "destructive git reset/checkout without explicit user request"]
    return {
        "profile": mode,
        "ask_user_required_for": ask_user,
        "forbidden": forbidden,
        "sandbox": {"network": "allowed_by_tool_policy", "filesystem": "workspace-first", "secrets": "redact"},
        "quota": {"azure": "bounded by per-tool timeouts", "context": "inject summaries before raw logs"},
    }


def _context_budget(files: list[str], diff: str, task: str) -> dict[str, Any]:
    diff_bytes = len((diff or "").encode("utf-8", errors="replace"))
    return {
        "diff_bytes": diff_bytes,
        "files_count": len(files),
        "strategy": "full" if diff_bytes < 80_000 and len(files) <= 12 else "summarize_then_slice",
        "keep": ["goal_summary", "prior_lessons", "direct file:line evidence", "latest failures"],
        "drop": ["old logs", "duplicate generated artifacts"],
    }


def _golden_eval(tags: list[str], results: Any) -> dict[str, Any]:
    checks = ["registered_tools", "smoke", "panel_review"]
    if "api" in tags:
        checks.append("api_contract")
    if "security" in tags:
        checks.append("secret/config scan")
    if "release" in tags:
        checks.append("prod_readiness")
    blockers = 0
    if isinstance(results, dict):
        blockers = int(results.get("blockers_count") or 0)
    return {"checks": checks, "score": max(0, 100 - blockers * 25), "promote_when": "smoke + panel/prod gate pass"}


def _handoff(blockers: list[str], tags: list[str]) -> dict[str, Any]:
    return {
        "needed": bool(blockers),
        "question": "Developer decision required" if blockers else "",
        "blockers": blockers[:10],
        "options": ["fix blockers and rerun checks", "accept risk with explicit note"] if blockers else [],
        "risk_tags": tags,
    }


def _rollback(stage: str, files: list[str], diff_hash: str) -> dict[str, Any]:
    return {
        "needed": stage in {"final", "pre_complete"},
        "manifest": {"files": files, "diff_hash": diff_hash, "verify": ["rerun smoke", "rerun prod gate"], "rollback": "use git diff/revert or harness backups if present"},
    }


def _model_governance() -> dict[str, Any]:
    return {
        "ask_codebase": ["gpt-5.4-4", "gpt-5.4-3", "gpt-5.3-codex-4"],
        "timeouts": "bounded; fallback/degraded must be explicit",
        "anti_pattern": "do not report green when Azure times out",
    }


def orchestrate(
    *,
    stage: str,
    files: list[str] | None = None,
    diff: str | None = None,
    task: str | None = None,
    mode: str = "balanced",
    results: Any = None,
) -> dict[str, Any]:
    files = [str(f) for f in (files or [])]
    text = "\n".join([task or "", diff or "", "\n".join(files)])
    tags = _classify(files, text)
    diff_hash = _hash(diff or "")
    blockers: list[str] = []
    if isinstance(results, dict):
        for item in results.get("results", []) if isinstance(results.get("results"), list) else []:
            if isinstance(item, dict) and (item.get("ok") is False or item.get("error")):
                blockers.append(str(item.get("tool") or item.get("error") or "unknown"))
    summary = {
        "status": "completed",
        "stage": stage,
        "mode": mode,
        "causal_trace": {"batch_id": _hash(f"{time.time()}:{text}", 12), "diff_hash": diff_hash, "files": files, "likely_causes": files[:8]},
        "skill_route": _route(tags, stage),
        "policy": _policy(tags, mode),
        "context_budget": _context_budget(files, diff or "", task or ""),
        "golden_eval": _golden_eval(tags, results),
        "handoff": _handoff(blockers, tags),
        "artifacts": {"ci_status": f".harness/status-{diff_hash}.json", "pr_summary": "available via pr_generator", "rollback": _rollback(stage, files, diff_hash)},
        "model_governance": _model_governance(),
        "prior_lessons": load_relevant_lessons_context(text),
    }
    _append({"tool": "orchestrator", **summary})
    return summary
