"""
Auto-pilot orchestration for contextual harness checks.
"""
from __future__ import annotations

import asyncio
import ast
import hashlib
import inspect
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from runtime_flags import bool_flag, choice_flag
from .core import _get_active_workspace, append_lesson, load_relevant_lessons_context
from .integrations import integration_router
from .workflow import workflow_router


DOC_EXTS = {".md", ".txt", ".rst", ".adoc"}
CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".go", ".rs",
    ".cs", ".php", ".rb", ".swift", ".kt", ".kts", ".sql", ".html", ".css",
}
UI_EXTS = {".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".vue"}
DEP_FILES = {
    "requirements.txt", "package.json", "pyproject.toml", "poetry.lock",
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
    "pipfile.lock", "uv.lock", "cargo.lock", "composer.lock", "go.sum",
}
SENSITIVE_NAMES = {".env", ".env.local", ".env.production", ".env.development", ".env.test"}
DEFAULT_TOOL_TIMEOUT_SECONDS = 180.0
MAX_TOOL_TIMEOUT_SECONDS = 240.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 240.0
MAX_TOTAL_TIMEOUT_SECONDS = 270.0
DEFAULT_MAX_TOOLS = 10
DEFAULT_SAFE_TOOLS = 6


def _auto_enabled() -> bool:
    return bool_flag("HARNESS_AUTO_PILOT", True, root=_get_active_workspace())


def _auto_llm_enabled() -> bool:
    return bool_flag("HARNESS_AUTO_LLM", False, root=_get_active_workspace())


def _auto_tool_timeout_seconds() -> float:
    try:
        timeout = float(os.getenv("HARNESS_AUTO_TOOL_TIMEOUT", str(DEFAULT_TOOL_TIMEOUT_SECONDS)))
    except ValueError:
        timeout = DEFAULT_TOOL_TIMEOUT_SECONDS
    return max(0.01, min(timeout, MAX_TOOL_TIMEOUT_SECONDS))


def _auto_total_timeout_seconds() -> float:
    try:
        timeout = float(os.getenv("HARNESS_AUTO_TOTAL_TIMEOUT", str(DEFAULT_TOTAL_TIMEOUT_SECONDS)))
    except ValueError:
        timeout = DEFAULT_TOTAL_TIMEOUT_SECONDS
    return max(1.0, min(timeout, MAX_TOTAL_TIMEOUT_SECONDS))


def _auto_subprocess_concurrency() -> int:
    try:
        value = int(os.getenv("HARNESS_AUTO_SUBPROCESS_CONCURRENCY", "4"))
    except ValueError:
        value = 4
    return max(1, min(value, 8))


def _auto_max_tools(mode: str) -> int:
    default = DEFAULT_MAX_TOOLS if mode == "max" else DEFAULT_SAFE_TOOLS
    try:
        value = int(os.getenv("HARNESS_AUTO_MAX_TOOLS", str(default)))
    except ValueError:
        value = default
    return max(1, min(value, 24))


def _tool_priority(name: str) -> int:
    priorities = {
        "goal_alignment": 0,
        "review_context_graph": 5,
        "secret_scanner": 10,
        "config_security_audit": 11,
        "env_parity_checker": 12,
        "devops_pipeline": 20,
        "release_orchestrator": 25,
        "panel_review": 30,
        "security_autofix": 35,
        "data_flow_taint_analyzer": 40,
        "api_contract_tester": 41,
        "openapi_spec_sync": 42,
        "migration_validator": 43,
        "sql_query_analyzer": 44,
        "complexity_analyzer": 50,
        "coverage_analyzer": 51,
        "breaking_change_detector": 52,
        "performance_regression_detector": 53,
        "dead_code_scanner": 60,
        "duplicate_code_scanner": 61,
        "incremental_refactor_guard": 62,
    }
    return priorities.get(name, 80)


LLM_AUTO_TOOLS = {
    "panel_review",
    "a11y_auditor",
    "i18n_auditor",
    "polyglot_reviewer",
    "license_scanner",
    "incident_responder",
    "migration_validator",
    "sql_query_analyzer",
    "openapi_spec_sync",
    "api_contract_tester",
    "breaking_change_detector",
    "performance_regression_detector",
    "data_flow_taint_analyzer",
    "container_linter",
    "ci_pipeline_validator",
    "auth_matrix_auditor",
    "release_orchestrator",
    "provenance_checker",
}

RUNTIME_ARTIFACT_NAMES = {"REVIEW_REPORT.md"}
RUNTIME_ARTIFACT_DIRS = {".harness", ".harness_cache", ".harness_sandbox", ".harness_smoke"}
RUNTIME_ARTIFACT_PATHS = {("llmwiki", "raw", ".bootstrapped")}
RUNTIME_ARTIFACT_PREFIXES = (
    ".harness_sandbox_",
    ".harness_smoke_",
    ".harness_targeted_test_",
    ".harness_registry_test_",
    ".harness_worktree_",
)
RUNTIME_ROOT_FILE_RE = re.compile(r"^\.harness_[A-Za-z0-9_.-]+\.(?:db|jsonl|pid|lock|log)(?:\.\d+)?$")


def _is_runtime_artifact(path: str) -> bool:
    norm = str(path or "").replace("\\", "/").strip("/")
    if not norm:
        return True
    parts = tuple(p for p in norm.split("/") if p)
    name = parts[-1] if parts else norm
    if any(parts == artifact or parts[:len(artifact)] == artifact for artifact in RUNTIME_ARTIFACT_PATHS):
        return True
    if name in RUNTIME_ARTIFACT_NAMES:
        return True
    if len(parts) >= 2 and parts[0] == ".claude" and parts[1] == "audit":
        return True
    if len(parts) > 1 and parts[0].startswith(".harness_"):
        return True
    if any(part in RUNTIME_ARTIFACT_DIRS or part.startswith(RUNTIME_ARTIFACT_PREFIXES) for part in parts):
        return True
    lower_name = name.lower()
    if lower_name in DEP_FILES:
        return False
    if len(parts) == 1 and RUNTIME_ROOT_FILE_RE.match(name):
        return True
    if lower_name.endswith((".log", ".lock", ".pid", ".tmp", ".temp", ".swp", ".swo", ".pyc", ".pyo", ".processing")) or re.match(r".+\.log\.\d+$", lower_name):
        return True
    return False


def _consume_task_exception(task: asyncio.Task) -> None:
    try:
        if not task.cancelled():
            task.exception()
    except (asyncio.CancelledError, Exception):
        pass


def _norm_files(files: list[str] | tuple[str, ...] | set[str] | str | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    if isinstance(files, str):
        items: Any = [files]
    elif isinstance(files, (list, tuple, set)):
        items = files
    else:
        items = []
    root_path = Path(_get_active_workspace()).resolve()
    for item in items:
        if not isinstance(item, str):
            continue
        raw = item.strip().replace("\\", "/")
        if not raw:
            continue
        try:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = root_path / candidate
            resolved = candidate.resolve(strict=False)
            if root_path != resolved and root_path not in resolved.parents:
                continue
            f = resolved.relative_to(root_path).as_posix()
        except Exception:
            continue
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _norm_tool_names(names: list[str] | tuple[str, ...] | set[str] | str | None) -> set[str]:
    if isinstance(names, str):
        items: Any = [names]
    elif isinstance(names, (list, tuple, set)):
        items = names
    else:
        items = []
    return {item.strip() for item in items if isinstance(item, str) and item.strip()}


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


def _safe_secret_scan_files(files: list[str] | None) -> list[str]:
    root = _get_active_workspace()
    out: list[str] = []
    seen: set[str] = set()
    for item in files or []:
        if not isinstance(item, str) or not item.strip():
            continue
        raw = item.strip().replace("\\", "/")
        if _is_runtime_artifact(raw):
            continue
        try:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = Path(root) / candidate
            if candidate.is_symlink():
                continue
            resolved = candidate.resolve(strict=True)
            root_path = Path(root).resolve()
            if root_path != resolved and root_path not in resolved.parents:
                continue
            if not resolved.is_file():
                continue
            rel = resolved.relative_to(root_path).as_posix()
        except Exception:
            continue
        if rel not in seen:
            seen.add(rel)
            out.append(rel)
    return out


def _safe_scan_files(files: list[str]) -> list[str]:
    return _safe_secret_scan_files(files)


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
    summary: dict[str, Any] = {"ok": _normalize_result_ok(result["ok"]) if "ok" in result else "error" not in result}
    for key in (
        "error", "status", "message", "verdict", "part_status", "summary", "score", "findings_count", "errors_count",
        "dead_symbols_count", "issues_count", "secrets_found", "warnings",
        "risk", "risk_score", "changed_symbol_count", "impacted_file_count", "test_gap_count",
    ):
        if key in result:
            summary[key] = result[key]
    if "findings" in result and isinstance(result["findings"], list):
        summary["findings_count"] = len(result["findings"])
    return _compact_auto_payload(summary)


def _normalize_result_ok(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return False
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "ok", "pass", "passed", "success", "completed"}
    return False


def _safe_repr(value: Any) -> str:
    try:
        return repr(value)
    except Exception as exc:
        return f"<unreprable:{type(value).__name__}:{type(exc).__name__}>"


def _compact_auto_payload(value: Any, *, max_string: int = 700, max_list: int = 8, max_dict: int = 24, depth: int = 0) -> Any:
    if depth > 4:
        return "<truncated:depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = value.replace("\x00", " ")
        if len(text) <= max_string:
            return text
        return text[:max_string].rstrip() + f"... <truncated {len(text) - max_string} chars>"
    if isinstance(value, (list, tuple, set, frozenset)):
        ordered = list(value) if not isinstance(value, (set, frozenset)) else sorted(value, key=_safe_repr)
        out = [
            _compact_auto_payload(item, max_string=max_string, max_list=max_list, max_dict=max_dict, depth=depth + 1)
            for item in ordered[:max_list]
        ]
        if len(ordered) > max_list:
            out.append(f"<truncated {len(ordered) - max_list} items>")
        return out
    if isinstance(value, dict):
        items = list(value.items())
        out = {
            str(k): _compact_auto_payload(v, max_string=max_string, max_list=max_list, max_dict=max_dict, depth=depth + 1)
            for k, v in items[:max_dict]
        }
        if len(items) > max_dict:
            out["<truncated_keys>"] = len(items) - max_dict
        return out
    text = _safe_repr(value)
    if len(text) <= max_string:
        return text
    return text[:max_string].rstrip() + f"... <truncated {len(text) - max_string} chars>"


def _auto_lesson_worthy_text(text: str, stage: str) -> bool:
    if stage in {"final", "pre_complete"}:
        return True
    return _has_any(text, {
        "fix", "fixed", "bug", "error", "fail", "failure", "timeout", "regression",
        "lesson", "learn", "workflow", "procedure", "root cause", "smoke", "test pass",
        "sửa", "lỗi", "học", "bài học", "quy trình", "kiểm tra",
    })


def _clean_check_result(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict) or result.get("ok") is not True:
        return False
    if result.get("warnings") or result.get("error") or result.get("detail"):
        return False
    bad_states = {"degraded", "error", "timeout", "failed", "failure", "fix_required", "blocked"}
    status_values = [
        str(result.get("status", "")).lower(),
        str(result.get("generation_status", "")).lower(),
        str(result.get("execution_status", "")).lower(),
        str(result.get("verdict", "")).lower(),
        str(result.get("part_status", "")).lower(),
    ]
    if any(value in bad_states or "timeout" in value for value in status_values if value):
        return False
    for key in ("findings_count", "errors_count", "issues_count", "secrets_found", "dead_symbols_count"):
        try:
            if int(result.get(key) or 0) > 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _record_auto_trigger_lesson(
    *,
    batch_id: str,
    diff_hash: str,
    files: list[str],
    task: str | None,
    stage: str,
    mode: str,
    selected: list[str],
    skipped_tools: list[str],
    results: list[dict[str, Any]],
    blockers_count: int,
    timeout_budget_exceeded: bool,
) -> dict[str, Any]:
    if not files or _docs_only(files) or blockers_count or timeout_budget_exceeded or not selected:
        return {"status": "skipped", "reason": "not a clean checked edit batch"}
    if len(results) < len(selected) or any(not _clean_check_result(r) for r in results):
        return {"status": "skipped", "reason": "one or more checks were not clean-success"}
    text = "\n".join([task or "", "\n".join(files), "\n".join(selected)])
    if not _auto_lesson_worthy_text(text, stage):
        return {"status": "skipped", "reason": "batch not lesson-worthy"}
    passed_tools = [
        str(r.get("tool")) for r in results
        if r.get("tool") and _clean_check_result(r)
    ][:8]
    warning_tools = [
        str(r.get("tool")) for r in results
        if r.get("tool") and r.get("ok") is not False and (r.get("warnings") or str(r.get("status", "")).lower() == "degraded")
    ][:8]
    title_seed = (task or "auto-trigger checked edit").strip().splitlines()[0]
    title = re.sub(r"\s+", " ", title_seed)[:140] or "auto-trigger checked edit"
    summary = (
        f"Auto-trigger checked {len(files)} file(s) at stage={stage} mode={mode}; "
        f"passed tools: {', '.join(passed_tools or selected[:5])}."
    )
    if warning_tools:
        summary += f" Completed with warnings: {', '.join(warning_tools)}."
    if skipped_tools:
        summary += f" Deferred tools: {', '.join(skipped_tools[:5])}."
    key_seed = json.dumps([batch_id, diff_hash, files, selected, title], ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(key_seed.encode("utf-8", errors="replace")).hexdigest()[:16]
    stored = append_lesson({
        "source": "auto_trigger",
        "lesson_type": "checked_edit",
        "title": title,
        "outcome": "checked_pass",
        "summary": summary,
        "fix_summary": summary,
        "files": files[:20],
        "tags": sorted(set(["auto_trigger", "checked_edit", stage, mode] + [tool for tool in selected[:8]])),
        "refs": {
            "batch_id": batch_id,
            "diff_hash": diff_hash,
            "selected_tools": selected,
            "skipped_tools": skipped_tools,
        },
        "lesson_key": f"auto_trigger:{digest}",
    })
    return {"status": "stored" if stored else "duplicate", "lesson_key": f"auto_trigger:{digest}", "title": title}


async def _run_named(name: str, factory) -> dict:
    async def invoke():
        candidate = factory() if callable(factory) else factory
        if inspect.isawaitable(candidate):
            return await candidate
        return candidate

    task = asyncio.create_task(invoke())
    try:
        done, _pending = await asyncio.wait({task}, timeout=_auto_tool_timeout_seconds())
        if task not in done:
            task.cancel()
            done_after_cancel, _ = await asyncio.wait({task}, timeout=0.1)
            if task in done_after_cancel:
                _consume_task_exception(task)
            else:
                task.add_done_callback(_consume_task_exception)
            return {"tool": name, "ok": False, "error": "timeout"}
        result = task.result()
        return {"tool": name, **_summarize_result(result)}
    except asyncio.CancelledError:
        task.cancel()
        task.add_done_callback(_consume_task_exception)
        raise
    except Exception as e:
        return _compact_auto_payload({"tool": name, "ok": False, "error": type(e).__name__, "detail": str(e) or repr(e)})


def _parse_subprocess_payload(out: str, err: str) -> dict[str, Any] | None:
    for stream in (out or "", err or ""):
        for line in reversed(stream.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and "ok" in payload:
                return payload
    return None


async def _run_subprocess_job(name: str, module: str, function: str, kwargs: dict[str, Any]) -> dict:
    script = (
        "import asyncio, importlib, inspect, json, os, sys\n"
        "try:\n"
        "    sys.stdout.reconfigure(encoding='utf-8')\n"
        "    sys.stderr.reconfigure(encoding='utf-8')\n"
        "except Exception:\n"
        "    pass\n"
        "try:\n"
        "    repo_root = os.path.realpath(sys.argv[3])\n"
        "    sys.path = [repo_root] + [p for p in sys.path if os.path.realpath(p or os.getcwd()) != os.getcwd()]\n"
        "    mod = importlib.import_module(sys.argv[1])\n"
        "    fn = getattr(mod, sys.argv[2])\n"
        "    kwargs = json.loads(sys.stdin.read() or '{}')\n"
        "    result = fn(**kwargs)\n"
        "    if inspect.isawaitable(result):\n"
        "        result = asyncio.run(result)\n"
        "    print(json.dumps({'ok': True, 'result': result}, default=str, ensure_ascii=False))\n"
        "except BaseException as e:\n"
        "    print(json.dumps({'ok': False, 'error': type(e).__name__, 'detail': str(e) or repr(e)}, ensure_ascii=False))\n"
        "    sys.exit(1)\n"
    )
    env = os.environ.copy()
    repo_root = os.path.realpath(os.path.join(os.path.dirname(__file__), os.pardir))
    active_workspace = os.path.realpath(_get_active_workspace())
    env["PYTHONPATH"] = repo_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["WORKSPACE_ROOT"] = active_workspace
    env["CLAUDE_PROJECT_DIR"] = active_workspace
    proc_kwargs: dict[str, Any] = {"cwd": repo_root, "env": env}
    if os.name == "nt":
        proc_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        proc_kwargs["start_new_session"] = True
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        module,
        function,
        repo_root,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **proc_kwargs,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(json.dumps(kwargs).encode("utf-8")),
            timeout=_auto_tool_timeout_seconds(),
        )
    except asyncio.TimeoutError:
        await _kill_subprocess_tree(proc)
        return {"tool": name, "ok": False, "error": "timeout"}
    except asyncio.CancelledError:
        if proc.returncode is None:
            await _kill_subprocess_tree(proc)
        raise
    out = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()
    payload = _parse_subprocess_payload(out, err)
    if payload is None:
        return _compact_auto_payload({"tool": name, "ok": False, "error": "invalid_subprocess_json", "detail": (err or out)[-1000:]})
    if not payload.get("ok"):
        return _compact_auto_payload({"tool": name, "ok": False, "error": payload.get("error", "subprocess_error"), "detail": payload.get("detail", "")})
    return {"tool": name, **_summarize_result(payload.get("result"))}


async def _kill_subprocess_tree(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        if os.name == "nt":
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(proc.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.communicate()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        await proc.communicate()
    except Exception:
        await proc.wait()


async def auto_trigger(
    changed_files: list[str] | tuple[str, ...] | set[str] | str | None = None,
    diff: str | None = None,
    task: str | None = None,
    stage: str = "post_edit",
    mode: str | None = None,
    exclude_tools: list[str] | tuple[str, ...] | set[str] | str | None = None,
) -> dict:
    """Run contextual checks automatically after edits.

    mode:
    - max: run aggressive default checks for code changes.
    - safe: skip panel/devops unless clear risk keywords are present.
    """
    if not _auto_enabled():
        return {"status": "skipped", "reason": "HARNESS_AUTO_PILOT=0"}

    from .goal import get_active_goal, goal_progress_summary

    raw_files = _norm_files(changed_files)
    files = [f for f in raw_files if not _is_runtime_artifact(f)]
    ignored_runtime_files = [f for f in raw_files if _is_runtime_artifact(f)]
    if raw_files and not files:
        return {
            "status": "skipped",
            "reason": "runtime-artifact-only change",
            "files": [],
            "ignored_runtime_files": ignored_runtime_files,
        }
    diff_hash = hashlib.sha256((diff or "").encode("utf-8", errors="replace")).hexdigest()[:16] if diff else ""
    mode = str(mode if mode is not None else choice_flag(
        "HARNESS_AUTO_MODE",
        "safe",
        {"safe", "max"},
        root=_get_active_workspace(),
    )).strip().lower()
    if mode not in {"safe", "max"}:
        return {"error": "invalid_argument", "detail": "mode must be one of: safe, max"}
    stage = str(stage or "post_edit").strip().lower()
    if stage not in {"post_edit", "final", "pre_complete"}:
        return {"error": "invalid_argument", "detail": "stage must be one of: post_edit, final, pre_complete"}
    batch_seed = json.dumps({"stage": stage, "files": files, "diff_hash": diff_hash, "task": task or ""}, ensure_ascii=False, sort_keys=True)
    batch_id = hashlib.sha256(batch_seed.encode("utf-8", errors="replace")).hexdigest()[:12]
    active_goal = get_active_goal()
    goal_text = active_goal.goal if active_goal else ""
    goal_summary = goal_progress_summary(active_goal) if active_goal else ""
    task_with_goal = f"{goal_summary}\n\n{task or ''}".strip() if goal_summary else task
    text = "\n".join([goal_text, task or "", diff or "", "\n".join(files)])
    prior_lessons = load_relevant_lessons_context(text)
    task_context = "\n\n".join(x for x in [task_with_goal or "", f"Prior lessons:\n{prior_lessons}" if prior_lessons else ""] if x).strip()
    integration_routes = integration_router(task=task_with_goal or task, changed_files=files, diff=diff)
    workflow_routes = workflow_router(task=task_with_goal or task, changed_files=files, diff=diff)

    if _docs_only(files) and mode != "max" and not active_goal:
        from .orchestrator import orchestrate
        orchestrator = orchestrate(stage=stage, files=files, diff=diff, task=task, mode=mode)
        return {
            "status": "skipped",
            "reason": "docs-only change",
            "files": files,
            "prior_lessons": prior_lessons,
            "integration_routes": integration_routes,
            "workflow_routes": workflow_routes,
            "orchestrator": orchestrator,
        }

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
        from .orchestrator import orchestrate
        orchestrator = orchestrate(stage=stage, files=files, diff=diff, task=task, mode=mode)
        return {
            "status": "skipped",
            "reason": "docs-only change",
            "files": files,
            "prior_lessons": prior_lessons,
            "integration_routes": integration_routes,
            "workflow_routes": workflow_routes,
            "orchestrator": orchestrator,
        }
    has_ui = bool(ui_files) or _has_any(text, {
        "ui", "ux", "frontend", "front-end", "design", "redesign", "layout", "screen",
        "component", "dashboard", "landing", "homepage", "user flow", "usability",
        "interaction", "microcopy", "visual", "responsive",
        "a11y", "accessibility", "i18n", "translation", "wcag",
    })
    has_deps = bool(dependency_files)
    has_tests = bool(test_files) or _has_any(text, {"pytest", "coverage", "flaky", "mutation test", "benchmark"})
    has_perf = _has_any(text, {"performance", "regression", "slow", "latency", "throughput", "load test", "benchmark"})
    risky = (
        has_security or has_db or has_api or has_refactor or len(code_files) > 1
        or bool(migration_files or ci_files or container_files or dependency_files)
    )

    selected: list[str] = []
    job_specs: list[tuple[str, str, str, dict[str, Any]]] = []
    excluded = _norm_tool_names(exclude_tools)
    orchestrator: dict[str, Any] = {"status": "not_run"}

    def add(name: str, module: str, function: str, **kwargs: Any) -> None:
        if name in excluded:
            return
        job_specs.append((name, module, function, kwargs))

    scan_files = _safe_secret_scan_files(files)

    if active_goal:
        add("goal_alignment", "tools.goal", "check_goal", changed_files=files, diff=diff, task=task_context or task_with_goal)
    if code_files and (risky or len(code_files) > 1 or stage in {"final", "pre_complete"} or mode == "max"):
        add("review_context_graph", "tools.graph_review", "review_context_graph", changed_files=code_files, detail_level="minimal")
    if has_trace or _has_any(text, {"bug", "debug", "diagnose", "traceback", "exception", "crash", "regression"}):
        add("bug_repro_guard", "tools.workflow", "bug_repro_guard", task=task_context or task_with_goal, error_log=text[:4000], changed_files=files, diff=diff)
    if (mode == "max" or has_config or has_security) and scan_files:
        add("secret_scanner", "tools.analysis", "secret_scanner", paths=scan_files)
    if mode == "max" or has_env:
        add("env_parity_checker", "tools.analysis", "env_parity_checker")
    if mode == "max" or has_config or has_security:
        add("config_security_audit", "tools.security", "config_security_audit")
    if code_files and (mode == "max" or risky):
        add("complexity_analyzer", "tools.analysis", "complexity_analyzer", paths=code_files)
    if files and (diff or stage in {"final", "pre_complete"} or mode == "max"):
        add("scope_creep_detector", "tools.scope_guard", "scope_creep_detector", changed_files=files, diff=diff, task=task_context or task_with_goal)
    if mode == "max" and code_files and (
        stage in {"final", "pre_complete"}
        or bool(ci_files or container_files or dependency_files)
        or has_release
        or _has_any(text, {"ci", "build", "lint", "typecheck", "pipeline"})
    ):
        add("devops_pipeline", "tools.devops", "devops_pipeline")
    if has_db or migration_files:
        if migration_files:
            add("migration_validator", "tools.quality", "migration_validator", paths=migration_files)
        if code_files:
            add("sql_query_analyzer", "tools.quality", "sql_query_analyzer", files=code_files)
    if code_files and (has_security or has_api or (mode == "max" and risky)):
        add("data_flow_taint_analyzer", "tools.quality", "data_flow_taint_analyzer", files=code_files)
    if has_api or (mode == "max" and any(_basename(f) in {"openapi.json", "openapi.yaml", "openapi.yml"} for f in files)):
        add("openapi_spec_sync", "tools.quality", "openapi_spec_sync")
        endpoints = _discover_api_endpoints(code_files)
        if endpoints:
            add("api_contract_tester", "tools.devops", "api_contract_tester", endpoints=endpoints)
    if container_files:
        add("container_linter", "tools.quality", "container_linter", paths=container_files or files)
    if ci_files:
        add("ci_pipeline_validator", "tools.quality", "ci_pipeline_validator", paths=ci_files)
    if has_ui:
        add("a11y_auditor", "tools.intel", "a11y_auditor", files=ui_files or files)
        if mode == "max" or _has_any(text, {"i18n", "translation"}):
            add("i18n_auditor", "tools.intel", "i18n_auditor", files=ui_files or files)
    if has_deps:
        add("license_scanner", "tools.intel", "license_scanner")
    if code_files and (mode == "max" or _has_any(text, {"importerror", "circular import", "dependency graph"})):
        add("dependency_graph_visualizer", "tools.quality", "dependency_graph_visualizer", paths=code_files)
    if has_tests or (mode == "max" and stage in {"final", "pre_complete"}):
        add("coverage_analyzer", "tools.testing", "coverage_analyzer")
    if _has_any(text, {"flaky", "non-deterministic"}):
        add("flaky_test_detector", "tools.quality", "flaky_test_detector", runs=3, test_path=test_files[0] if test_files else "")
    if _has_any(text, {"mutation test", "mutation score"}):
        add("mutation_tester", "tools.quality", "mutation_tester", files=code_files or None)
    if mode == "max" and (has_api or has_db or "basemodel" in text.lower()):
        add("schema_drift", "tools.analysis", "schema_drift")
    if mode == "max" and stage in {"final", "pre_complete"} and (has_refactor or has_perf or len(code_files) >= 2):
        add("breaking_change_detector", "tools.quality", "breaking_change_detector")
        add("performance_regression_detector", "tools.quality", "performance_regression_detector")
    urls = _extract_urls(text)
    if urls and _has_any(text, {"load test", "throughput", "rps"}):
        add("load_tester", "tools.analysis", "load_tester", url=urls[0])
    if has_refactor or (mode == "max" and len(code_files) >= 2):
        add("dead_code_scanner", "tools.analysis", "dead_code_scanner")
        add("duplicate_code_scanner", "tools.quality", "duplicate_code_scanner")
        add("incremental_refactor_guard", "tools.gap_tools", "incremental_refactor_guard", files=code_files, diff=diff, mode=mode)
    if (mode == "max" and has_security and has_api) or _has_any(text, {"auth matrix", "permission matrix", "ownership check"}):
        add("auth_matrix_auditor", "tools.gap_tools", "auth_matrix_auditor", files=code_files or files, diff=diff, context=task_context or task_with_goal, mode=mode)
    if has_release or (mode == "max" and stage in {"final", "pre_complete"}):
        add("release_orchestrator", "tools.gap_tools", "release_orchestrator", changed_files=files, diff=diff, context=task_context or task_with_goal, mode=mode)
    if has_release and mode == "max":
        add("provenance_checker", "tools.gap_tools", "provenance_checker", files=files, context=task_context or task_with_goal, mode=mode)
    if has_trace:
        add("harness_trace_viewer", "tools.gap_tools", "harness_trace_viewer", limit=20, mode=mode)
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
        if prior_lessons:
            focus_bits.append("prior lessons already handled: check against injected PRIOR LESSONS")
        add("panel_review", "tools.review", "panel_review", files=panel_files, focus=", ".join(focus_bits) or None)

    if not job_specs:
        from .orchestrator import orchestrate
        orchestrator = orchestrate(stage=stage, files=files, diff=diff, task=task, mode=mode)
        return {
            "status": "skipped",
            "reason": "no matching automatic checks",
            "files": files,
            "prior_lessons": prior_lessons,
            "integration_routes": integration_routes,
            "workflow_routes": workflow_routes,
            "orchestrator": orchestrator,
        }

    warnings = []
    if not _auto_llm_enabled():
        before = len(job_specs)
        job_specs = [spec for spec in job_specs if spec[0] not in LLM_AUTO_TOOLS]
        if before != len(job_specs):
            warnings.append("9Router LLM auto-checks skipped; set HARNESS_AUTO_LLM=1 to allow them explicitly")

    if not job_specs:
        from .orchestrator import orchestrate
        orchestrator = orchestrate(stage=stage, files=files, diff=diff, task=task, mode=mode)
        return {
            "status": "skipped",
            "reason": "only 9Router LLM checks matched and HARNESS_AUTO_LLM is off",
            "files": files,
            "ignored_runtime_files": ignored_runtime_files,
            "prior_lessons": prior_lessons,
            "integration_routes": integration_routes,
            "workflow_routes": workflow_routes,
            "orchestrator": orchestrator,
            "warnings": warnings,
        }

    indexed_specs = list(enumerate(job_specs))
    indexed_specs.sort(key=lambda item: (_tool_priority(item[1][0]), item[0]))
    max_tools = _auto_max_tools(mode)
    selected_specs = indexed_specs[:max_tools]
    skipped_specs = indexed_specs[max_tools:]
    selected = [name for _idx, (name, _module, _function, _kwargs) in selected_specs]
    skipped_tools = [name for _idx, (name, _module, _function, _kwargs) in skipped_specs]

    subprocess_sem = asyncio.Semaphore(_auto_subprocess_concurrency())

    async def _run_limited_subprocess_job(name: str, module: str, function: str, kwargs: dict[str, Any]) -> dict:
        async with subprocess_sem:
            return await _run_subprocess_job(name, module, function, kwargs)

    runner_tasks = {
        asyncio.create_task(_run_limited_subprocess_job(name, module, function, kwargs)): name
        for _idx, (name, module, function, kwargs) in selected_specs
    }
    done, pending = await asyncio.wait(set(runner_tasks), timeout=_auto_total_timeout_seconds())
    results: list[dict[str, Any]] = []
    for task_done in done:
        try:
            results.append(task_done.result())
        except Exception as e:
            results.append({"tool": runner_tasks[task_done], "ok": False, "error": type(e).__name__, "detail": str(e) or repr(e)})
    for task_pending in pending:
        name = runner_tasks[task_pending]
        task_pending.cancel()
        task_pending.add_done_callback(_consume_task_exception)
        results.append({"tool": name, "ok": False, "error": "timeout_budget_exceeded"})
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
    failed_tools = [str(r.get("tool", "")) for r in blockers if r.get("tool")]
    if skipped_tools:
        warnings.append(f"auto_trigger budget selected {len(selected)} of {len(job_specs)} matching checks; skipped_tools lists deferred checks")
    if pending:
        warnings.append("auto_trigger hit total timeout budget before all selected checks completed")
    if prior_lessons:
        warnings.append("prior lessons were auto-injected into matching checks; inspect prior_lessons for trace")
    lessons_recorded = _record_auto_trigger_lesson(
        batch_id=batch_id,
        diff_hash=diff_hash,
        files=files,
        task=task,
        stage=stage,
        mode=mode,
        selected=selected,
        skipped_tools=skipped_tools,
        results=results,
        blockers_count=len(blockers),
        timeout_budget_exceeded=bool(pending),
    )
    try:
        from .core import record_failure_causality_memory
        causality_recorded = record_failure_causality_memory(
            batch_id=batch_id,
            diff_hash=diff_hash,
            files=files,
            task=task,
            selected_tools=selected,
            failed_tools=failed_tools,
            results=results,
            blockers_count=len(blockers),
        )
    except Exception:
        causality_recorded = {"status": "skipped", "reason": "record_failed"}
    try:
        from .ops import append_run_ledger
        from .orchestrator import orchestrate
        orchestrator = orchestrate(stage=stage, files=files, diff=diff, task=task, mode=mode, results={"results": results, "blockers_count": len(blockers)})
        append_run_ledger({
            "tool": "auto_trigger",
            "event": "edit_batch_checked",
            "batch_id": batch_id,
            "stage": stage,
            "mode": mode,
            "files": files,
            "diff_hash": diff_hash,
            "task": task,
            "selected_tools": selected,
            "skipped_tools": skipped_tools,
            "timeout_budget_exceeded": bool(pending),
            "failed_tools": failed_tools,
            "blockers_count": len(blockers),
            "prior_lessons": prior_lessons,
            "integration_routes": integration_routes,
            "workflow_routes": workflow_routes,
            "lessons_recorded": lessons_recorded,
            "causality_recorded": causality_recorded,
            "orchestrator": orchestrator,
        })
    except Exception:
        orchestrator = {"status": "skipped"}
    if panel_files != (code_files or files):
        warnings.append(".env-like files were kept out of LLM review to avoid exposing secret values; local secret scanner still scans them with redacted snippets")
    if goal_changed_mid_run:
        warnings.append("active goal changed or completed while auto_trigger was running; dropped stale goal_alignment result")
    compact_results = [_compact_auto_payload(result) for result in results]
    compact_prior_lessons = _compact_auto_payload(prior_lessons, max_string=1800) if prior_lessons else ""
    compact_integration_routes = _compact_auto_payload(integration_routes, max_string=500, max_list=6)
    compact_workflow_routes = _compact_auto_payload(workflow_routes, max_string=500, max_list=6)
    compact_orchestrator = _compact_auto_payload(orchestrator, max_string=700, max_list=8)
    status = "degraded" if skipped_tools or pending else "completed"
    guidance = "OK to continue; inspect warnings only if relevant."
    if blockers:
        guidance = "Address failed_tools/blockers before reporting completion."
    elif skipped_tools or pending:
        guidance = "Checks completed with deferred/timeout items; do not treat skipped tools as code failures unless they match the task."
    return {
        "status": status,
        "mode": mode,
        "stage": stage,
        "summary": (
            f"auto_trigger {status}: {len(files)} file(s), "
            f"{len(selected)} selected, {len(skipped_tools)} skipped, {len(blockers)} blocker(s)."
        ),
        "agent_guidance": guidance,
        "batch_id": batch_id,
        "diff_hash": diff_hash,
        "files": files,
        "ignored_runtime_files": ignored_runtime_files,
        "goal_active": bool(active_goal),
        "goal": goal_text or None,
        "selected_tools": selected,
        "skipped_tools": skipped_tools,
        "timeout_budget_exceeded": bool(pending),
        "results": compact_results,
        "blockers_count": len(blockers),
        "failed_tools": failed_tools,
        "prior_lessons": compact_prior_lessons,
        "integration_routes": compact_integration_routes,
        "workflow_routes": compact_workflow_routes,
        "lessons_recorded": lessons_recorded,
        "causality_recorded": causality_recorded,
        "orchestrator": compact_orchestrator,
        "warnings": _compact_auto_payload(warnings, max_string=400, max_list=10),
    }
