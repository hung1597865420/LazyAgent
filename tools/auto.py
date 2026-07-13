"""
Auto-pilot orchestration for contextual harness checks.
"""
from __future__ import annotations

import asyncio
import ast
import os
import re
import contextlib
from typing import Any


DOC_EXTS = {".md", ".txt", ".rst", ".adoc"}
CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".go", ".rs",
    ".cs", ".php", ".rb", ".swift", ".kt", ".kts", ".sql", ".html", ".css",
}
UI_EXTS = {".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".vue"}
DEP_FILES = {"requirements.txt", "package.json", "pyproject.toml", "poetry.lock", "package-lock.json", "pnpm-lock.yaml"}
SENSITIVE_NAMES = {".env", ".env.local", ".env.production", ".env.development", ".env.test"}
DEFAULT_TOOL_TIMEOUT_SECONDS = 180.0


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


def _migration_files(files: list[str]) -> list[str]:
    out = []
    for path in files:
        lower = path.replace("\\", "/").lower()
        if any(part in lower for part in ("migration", "migrations/", "migrate", "alembic/versions")):
            if lower.endswith((".py", ".sql")):
                out.append(path)
    return out


def _ci_files(files: list[str]) -> list[str]:
    return [
        f for f in files
        if ".github/workflows" in f.replace("\\", "/").lower() or _basename(f) == ".gitlab-ci.yml"
    ]


def _container_files(files: list[str]) -> list[str]:
    return [
        f for f in files
        if _basename(f) in {"dockerfile", "docker-compose.yml", "docker-compose.yaml"}
        or _basename(f).startswith("dockerfile.")
        or _basename(f).endswith(".dockerfile")
    ]


def _dependency_files(files: list[str]) -> list[str]:
    return [f for f in files if _basename(f) in DEP_FILES]


def _ui_files(files: list[str]) -> list[str]:
    return [f for f in files if _ext(f) in UI_EXTS]


def _test_files(files: list[str]) -> list[str]:
    return [f for f in files if _basename(f).startswith("test_") or "_test" in _basename(f)]


def _extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s)>'\"]+", text or "")[:3]


def _discover_api_endpoints(files: list[str]) -> list[dict[str, str]]:
    try:
        from .core import _get_active_workspace
        root = os.path.realpath(_get_active_workspace())
    except Exception:
        return []
    endpoints: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    methods = {"get", "post", "put", "patch", "delete", "options", "head"}

    def add_endpoint(method: str, path: str, file_path: str) -> None:
        item = (method.upper(), path)
        if item not in seen:
            seen.add(item)
            endpoints.append({"method": item[0], "path": item[1], "file": file_path.replace("\\", "/")})

    for rel in files[:20]:
        try:
            candidate = rel
            if os.path.isabs(candidate):
                full_abs = os.path.realpath(candidate)
                if os.path.commonpath([root, full_abs]) != root:
                    continue
                candidate = os.path.relpath(full_abs, root)
            full = os.path.realpath(os.path.join(root, candidate))
            if os.path.commonpath([root, full]) != root or not os.path.isfile(full):
                continue
            stat_before = os.stat(full)
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(80_000)
            stat_after = os.stat(full)
            if (stat_before.st_mtime_ns, stat_before.st_size) != (stat_after.st_mtime_ns, stat_after.st_size):
                continue
        except (OSError, ValueError):
            continue
        for match in re.finditer(r"@\w+\.(get|post|put|patch|delete|options|head)\(\s*['\"]([^'\"]+)", content):
            add_endpoint(match.group(1), match.group(2), candidate)
            if len(endpoints) >= 20:
                return endpoints
        try:
            tree = ast.parse(content)
        except SyntaxError:
            tree = None
        if tree:
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for dec in node.decorator_list:
                    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                        continue
                    if dec.func.attr not in methods or not dec.args:
                        continue
                    first = dec.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        add_endpoint(dec.func.attr, first.value, candidate)
                    elif isinstance(first, ast.JoinedStr):
                        add_endpoint(dec.func.attr, "<dynamic>", candidate)
                    if len(endpoints) >= 20:
                        return endpoints
    return endpoints


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
    task = asyncio.create_task(coro)
    try:
        try:
            timeout = float(os.getenv("HARNESS_AUTO_TOOL_TIMEOUT", str(DEFAULT_TOOL_TIMEOUT_SECONDS)))
        except ValueError:
            timeout = DEFAULT_TOOL_TIMEOUT_SECONDS
        result = await asyncio.wait_for(task, timeout=max(0.01, min(timeout, 1800.0)))
        return {"tool": name, **_summarize_result(result)}
    except asyncio.TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return {"tool": name, "ok": False, "error": "timeout"}
    except Exception as e:
        return {"tool": name, "ok": False, "error": type(e).__name__, "detail": str(e) or repr(e)}


async def auto_trigger(
    changed_files: list[str] | None = None,
    diff: str | None = None,
    task: str | None = None,
    stage: str = "post_edit",
    mode: str | None = None,
    exclude_tools: list[str] | set[str] | None = None,
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
        load_tester,
        secret_scanner,
        schema_drift,
    )
    from .devops import api_contract_tester, devops_pipeline
    from .intel import a11y_auditor, i18n_auditor, license_scanner
    from .quality import (
        breaking_change_detector,
        ci_pipeline_validator,
        container_linter,
        data_flow_taint_analyzer,
        dependency_graph_visualizer,
        duplicate_code_scanner,
        flaky_test_detector,
        migration_validator,
        mutation_tester,
        openapi_spec_sync,
        performance_regression_detector,
        sql_query_analyzer,
    )
    from .security import config_security_audit
    from .testing import coverage_analyzer
    from .gap_tools import (
        auth_matrix_auditor,
        harness_trace_viewer,
        incremental_refactor_guard,
        provenance_checker,
        release_orchestrator,
    )

    files = _norm_files(changed_files)
    mode = str(mode if mode is not None else os.getenv("HARNESS_AUTO_MODE", "max")).strip().lower()
    if mode not in {"safe", "max"}:
        return {"error": "invalid_argument", "detail": "mode must be one of: safe, max"}
    stage = str(stage or "post_edit").strip().lower()
    if stage not in {"post_edit", "final", "pre_complete"}:
        return {"error": "invalid_argument", "detail": "stage must be one of: post_edit, final, pre_complete"}
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
    migration_files = _migration_files(files)
    ci_files = _ci_files(files)
    container_files = _container_files(files)
    dependency_files = _dependency_files(files)
    ui_files = _ui_files(files)
    test_files = _test_files(files)
    has_security = _has_any(text, {"auth", "jwt", "session", "token", "secret", "password", "cors", "rls", "crypto"})
    has_db = _has_any(text, {"sql", "migration", "alembic", "schema", "transaction", "query", "orm"})
    has_refactor = _has_any(text, {"refactor", "rename", "delete", "remove", "dead code", "duplicate"})
    has_api = _has_any(text, {"route", "endpoint", "api", "request", "response", "pydantic", "openapi"})
    has_release = _has_any(text, {"release", "deploy", "production", "prod-ready", "tag", "changelog"})
    has_trace = _has_any(text, {"trace", "stack trace", "timeout", "rate-limit", "latency", "slow", "500", "exception"})
    if _docs_only(files) and not active_goal and not has_release:
        return {"status": "skipped", "reason": "docs-only change", "files": files}
    has_ui = bool(ui_files) or _has_any(text, {"a11y", "accessibility", "i18n", "translation", "wcag"})
    has_deps = bool(dependency_files)
    has_tests = bool(test_files) or _has_any(text, {"pytest", "coverage", "flaky", "mutation test", "benchmark"})
    has_perf = _has_any(text, {"performance", "regression", "slow", "latency", "throughput", "load test", "benchmark"})
    risky = (
        has_security or has_db or has_api or has_refactor or len(code_files) > 1
        or bool(migration_files or ci_files or container_files or dependency_files)
    )

    selected: list[str] = []
    jobs = []
    excluded = {str(name) for name in (exclude_tools or [])}

    def add(name: str, coro) -> None:
        if name in excluded:
            close = getattr(coro, "close", None)
            if callable(close):
                close()
            return
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
    if mode == "max" and code_files and (
        stage in {"final", "pre_complete"}
        or bool(ci_files or container_files or dependency_files)
        or has_release
        or _has_any(text, {"ci", "build", "lint", "typecheck", "pipeline"})
    ):
        add("devops_pipeline", devops_pipeline())
    if has_db or migration_files:
        if migration_files:
            add("migration_validator", migration_validator(paths=migration_files))
        if code_files:
            add("sql_query_analyzer", sql_query_analyzer(files=code_files))
    if code_files and (has_security or has_api or (mode == "max" and risky)):
        add("data_flow_taint_analyzer", data_flow_taint_analyzer(files=code_files))
    if has_api or (mode == "max" and any(_basename(f) in {"openapi.json", "openapi.yaml", "openapi.yml"} for f in files)):
        add("openapi_spec_sync", openapi_spec_sync())
        endpoints = _discover_api_endpoints(code_files)
        if endpoints:
            add("api_contract_tester", api_contract_tester(endpoints=endpoints))
    if container_files:
        add("container_linter", container_linter(paths=container_files or files))
    if ci_files:
        add("ci_pipeline_validator", ci_pipeline_validator(paths=ci_files))
    if has_ui:
        add("a11y_auditor", a11y_auditor(files=ui_files or files))
        if mode == "max" or _has_any(text, {"i18n", "translation"}):
            add("i18n_auditor", i18n_auditor(files=ui_files or files))
    if has_deps:
        add("license_scanner", license_scanner())
    if code_files and (mode == "max" or _has_any(text, {"importerror", "circular import", "dependency graph"})):
        add("dependency_graph_visualizer", dependency_graph_visualizer(paths=code_files))
    if has_tests or (mode == "max" and stage in {"final", "pre_complete"}):
        add("coverage_analyzer", coverage_analyzer())
    if _has_any(text, {"flaky", "non-deterministic"}):
        add("flaky_test_detector", flaky_test_detector(runs=3, test_path=test_files[0] if test_files else ""))
    if _has_any(text, {"mutation test", "mutation score"}):
        add("mutation_tester", mutation_tester(files=code_files or None))
    if mode == "max" and (has_api or has_db or "basemodel" in text.lower()):
        add("schema_drift", schema_drift())
    if mode == "max" and stage in {"final", "pre_complete"} and (has_refactor or has_perf or len(code_files) >= 2):
        add("breaking_change_detector", breaking_change_detector())
        add("performance_regression_detector", performance_regression_detector())
    urls = _extract_urls(text)
    if urls and _has_any(text, {"load test", "throughput", "rps"}):
        add("load_tester", load_tester(url=urls[0]))
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
