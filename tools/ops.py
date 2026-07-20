"""Operational tools for harness self-management and evaluation."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

from .core import LESSON_INDEX_FILE, _assemble_context, _get_active_workspace, _lesson_file_lock, _run_cmd_safe, get_global_lessons_path, read_lessons
from .orchestrator import ORCH_FILE, orchestrate
from .goal import load_goal_state
from .runner import RUNNER_LOCK_FILE, _read_lock

LEDGER_FILE = ".harness_run_ledger.jsonl"
INSTALL_MANIFEST_FILE = "harness.install.json"
HARNESS_SERVER_FILE = Path(__file__).resolve().parents[1] / "mcp_server.py"
HARNESS_ROOT = Path(__file__).resolve().parents[1]

POLICY_PROFILES: dict[str, dict[str, Any]] = {
    "fast": {"mode": "safe", "max_iterations": 3, "final_prod_gate": False, "llm": "minimal"},
    "balanced": {"mode": "max", "max_iterations": 8, "final_prod_gate": True, "llm": "contextual"},
    "prod": {"mode": "max", "max_iterations": 12, "final_prod_gate": True, "llm": "heavy"},
    "paranoid": {"mode": "max", "max_iterations": 20, "final_prod_gate": True, "llm": "max"},
}


async def router_quota_status(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Compatibility shim for the removed quota feature.

    The previous implementation queried 9Router/dashboard quota endpoints. That
    feature was intentionally removed; this shim keeps old MCP clients from
    failing with unknown-tool while making the removal explicit.
    """
    return {
        "status": "deprecated",
        "deprecated": True,
        "removed": True,
        "tool": "router_quota_status",
        "replacement": "finops_stats",
        "message": (
            "router_quota_status was removed with the quota/costguard feature set. "
            "Use local finops_stats for recorded token/cost telemetry; no router quota endpoint is queried."
        ),
        "llm_used": False,
        "router_queried": False,
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


def _home_display_path(path: Path) -> str:
    return _display_path(str(path.expanduser().resolve() if path.exists() else path.expanduser()))


def _expand_user_path(value: str) -> Path:
    text = str(value or "")
    if text.startswith("~/") or text == "~":
        return Path.home() / text[2:]
    return Path(text)


def _read_text_safe(path: Path, max_bytes: int = 2_000_000) -> str:
    try:
        if not path.exists() or not path.is_file():
            return ""
        data = path.read_bytes()[:max_bytes]
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return data.decode("utf-16", errors="replace")
        if data[:3] == b"\xef\xbb\xbf":
            return data.decode("utf-8-sig", errors="replace")
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _read_json_safe(path: Path) -> dict[str, Any]:
    text = _read_text_safe(path)
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    words = len(re.findall(r"\S+", text))
    by_words = int(words * 1.3)
    by_chars = int(len(text) / 4)
    return max(by_words, by_chars)


def _file_budget(path: Path, label: str, category: str) -> dict[str, Any]:
    text = _read_text_safe(path)
    try:
        line_count = text.count("\n") + (1 if text else 0)
        byte_count = path.stat().st_size if path.exists() else 0
    except OSError:
        line_count = 0
        byte_count = 0
    return {
        "label": label,
        "category": category,
        "path": _display_path(str(path)),
        "exists": path.exists(),
        "lines": line_count,
        "bytes": byte_count,
        "estimated_tokens": _estimate_tokens(text),
    }


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
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
        with _lesson_file_lock(path):
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
    except OSError:
        pass


def _read_ledger(limit: int = 20) -> list[dict[str, Any]]:
    path = _root() / LEDGER_FILE
    if not path.exists():
        return []
    rows = []
    try:
        wanted = max(1, min(200, int(limit)))
        with _lesson_file_lock(path):
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


def _read_orchestrator(limit: int = 20) -> list[dict[str, Any]]:
    path = _root() / ORCH_FILE
    if not path.exists():
        return []
    try:
        wanted = max(1, min(200, int(limit)))
        with _lesson_file_lock(path):
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, ValueError):
        return []
    rows = []
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
            if len(rows) >= wanted:
                break
    return list(reversed(rows))


async def run_ledger(limit: int = 20) -> dict[str, Any]:
    """Return recent goal/benchmark runner ledger entries."""
    rows = _read_ledger(limit)
    lessons = read_lessons(limit)
    return {
        "status": "completed",
        "entries": rows,
        "entries_count": len(rows),
        "file": _display_path(str(_root() / LEDGER_FILE)),
        "lessons": lessons,
        "lessons_count": len(lessons),
        "lessons_file": _display_path(str(_root() / LESSON_INDEX_FILE)),
        "global_lessons_file": _display_path(get_global_lessons_path()),
        "global_sync_manifest": _display_path(str(Path(get_global_lessons_path()).with_suffix(".manifest.json"))),
        "orchestrator": _read_orchestrator(limit),
        "orchestrator_file": _display_path(str(_root() / ORCH_FILE)),
    }


async def policy_profile(profile: str = "balanced") -> dict[str, Any]:
    """Return policy profile defaults for runner/check intensity."""
    key = (profile or "balanced").strip().lower()
    if key not in POLICY_PROFILES:
        return {"error": "invalid_argument", "detail": f"profile must be one of: {', '.join(POLICY_PROFILES)}"}
    intelligence = orchestrate(stage="policy_profile", files=[], diff="", task=f"profile {key}", mode=key)
    return {"status": "completed", "profile": key, "settings": POLICY_PROFILES[key], "profiles": POLICY_PROFILES, "orchestrator": intelligence}


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
    """Audit assembled context size, warning count, and likely usefulness without calling 9Router."""
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
    """Dry-run the local ask_codebase context path to catch overlarge/weak context before 9Router."""
    audit = await context_auditor(question=question, files=files, context=context)
    advice = []
    if audit["verdict"] == "too_large":
        advice.append("Narrow files or rely on ask_codebase auto-selection before 9Router.")
    if audit["warnings_count"]:
        advice.append("Review warnings; skipped files may remove needed evidence.")
    if not advice:
        advice.append("Context path looks usable; 9Router timeout risk is mostly model/quota, not local context assembly.")
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


def _load_install_manifest() -> dict[str, Any]:
    path = HARNESS_ROOT / INSTALL_MANIFEST_FILE
    data = _read_json_safe(path)
    if not data:
        return {"version": 0, "targets": {}, "modules": {}, "profiles": {}}
    for key in ("targets", "modules", "profiles"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    return data


async def install_manifest(action: str = "summary", profile: str = "standard", target: str | None = None) -> dict[str, Any]:
    """Inspect the static setup manifest and render a dry-run install/check plan."""
    manifest = _load_install_manifest()
    action = (action or "summary").strip().lower()
    profile = (profile or "standard").strip().lower()
    target = (target or "").strip().lower() or None
    profiles = manifest.get("profiles", {})
    targets = manifest.get("targets", {})
    modules = manifest.get("modules", {})
    manifest_path = HARNESS_ROOT / INSTALL_MANIFEST_FILE

    if action not in {"summary", "list", "plan", "check"}:
        return {"error": "invalid_argument", "detail": "action must be one of: summary, list, plan, check"}
    if target and target not in targets:
        return {"error": "invalid_argument", "detail": f"target must be one of: {', '.join(sorted(targets))}"}
    if profile not in profiles and action in {"plan", "check"}:
        return {"error": "invalid_argument", "detail": f"profile must be one of: {', '.join(sorted(profiles))}"}

    if action in {"summary", "list"}:
        return {
            "status": "completed",
            "manifest": _display_path(str(manifest_path)),
            "version": manifest.get("version"),
            "profiles": {
                key: {
                    "description": value.get("description", ""),
                    "modules": value.get("modules", []),
                }
                for key, value in sorted(profiles.items())
            },
            "targets": {
                key: {
                    "description": value.get("description", ""),
                    "modules": value.get("modules", []),
                    "required_files": value.get("required_files", []),
                }
                for key, value in sorted(targets.items())
            },
            "modules": modules,
        }

    selected_modules = set(profiles.get(profile, {}).get("modules", []))
    selected_targets = {target: targets[target]} if target else targets
    operations = []
    missing_required_files = []
    for target_id, target_cfg in sorted(selected_targets.items()):
        target_modules = set(target_cfg.get("modules", []))
        effective_modules = sorted(selected_modules.intersection(target_modules))
        skipped_modules = sorted(selected_modules - target_modules)
        required_files = []
        for raw_path in target_cfg.get("required_files", []):
            path = _expand_user_path(str(raw_path))
            exists = path.exists()
            required_files.append({
                "path": str(raw_path),
                "display_path": _display_path(str(path)),
                "exists": exists,
            })
            if not exists:
                missing_required_files.append({"target": target_id, "path": str(raw_path)})
        operations.append({
            "target": target_id,
            "description": target_cfg.get("description", ""),
            "selected_modules": effective_modules,
            "skipped_modules": skipped_modules,
            "required_files": required_files,
            "installer": "python merge_settings.py plus harness-full-setup.bat for dependencies/startup task",
        })
    return {
        "status": "completed",
        "manifest": _display_path(str(manifest_path)),
        "profile": profile,
        "target": target or "all",
        "valid": not missing_required_files if action == "check" else True,
        "missing_required_files": missing_required_files,
        "operations": operations,
        "note": "Dry-run only; this tool never writes agent configs or changes harness.features.json.",
    }


def _extract_json_mcp_servers(path: Path, harness: str) -> list[dict[str, Any]]:
    data = _read_json_safe(path)
    servers = data.get("mcpServers") or data.get("servers") or {}
    if not isinstance(servers, dict):
        return []
    rows = []
    for name, cfg in sorted(servers.items()):
        if not isinstance(cfg, dict):
            continue
        env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
        args = cfg.get("args") if isinstance(cfg.get("args"), list) else []
        command = str(cfg.get("command") or "")
        url = str(cfg.get("url") or cfg.get("endpoint") or "")
        transport = str(cfg.get("transport") or ("http" if url else "stdio"))
        rows.append({
            "name": str(name),
            "harness": harness,
            "source": _display_path(str(path)),
            "transport": transport,
            "command": command,
            "args": [str(arg) for arg in args],
            "url": url,
            "enabled": cfg.get("disabled") is not True and cfg.get("enabled") is not False,
            "env_keys": sorted(str(key) for key in env.keys()),
            "has_secrets": bool(env),
        })
    return rows


def _parse_toml_value(raw: str) -> Any:
    raw = raw.strip().rstrip(",")
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip('"')
    if raw.startswith("[") and raw.endswith("]"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return [part.strip().strip('"') for part in raw.strip("[]").split(",") if part.strip()]
    if raw.lower() in {"true", "false"}:
        return raw.lower() == "true"
    return raw


def _extract_codex_mcp_servers(path: Path) -> list[dict[str, Any]]:
    text = _read_text_safe(path)
    if not text:
        return []
    rows = []
    pattern = re.compile(r'(?ms)^\s*\[mcp_servers\.(?:"([^"]+)"|([A-Za-z0-9_.-]+))\]\s*\n(.*?)(?=^\s*\[|\Z)')
    for match in pattern.finditer(text):
        name = match.group(1) or match.group(2) or ""
        body = match.group(3)
        cfg: dict[str, Any] = {}
        for line in body.splitlines():
            clean = line.split("#", 1)[0].strip()
            if "=" not in clean:
                continue
            key, value = clean.split("=", 1)
            cfg[key.strip()] = _parse_toml_value(value)
        args = cfg.get("args") if isinstance(cfg.get("args"), list) else []
        env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
        rows.append({
            "name": str(name),
            "harness": "codex",
            "source": _display_path(str(path)),
            "transport": str(cfg.get("transport") or ("http" if cfg.get("url") else "stdio")),
            "command": str(cfg.get("command") or ""),
            "args": [str(arg) for arg in args],
            "url": str(cfg.get("url") or ""),
            "enabled": cfg.get("disabled") is not True,
            "env_keys": sorted(str(key) for key in env.keys()),
            "has_secrets": bool(env),
        })
    return rows


def _server_fingerprint(server: dict[str, Any]) -> str:
    payload = {
        "transport": server.get("transport"),
        "command": server.get("command"),
        "args": server.get("args", []),
        "url": server.get("url", ""),
        "enabled": server.get("enabled", True),
    }
    return json.dumps(payload, sort_keys=True)


def _all_mcp_servers() -> list[dict[str, Any]]:
    home = Path.home()
    candidates = [
        ("claude", home / ".claude" / "claude_mcp_config.json", "json"),
        ("gemini", home / ".gemini" / "config" / "mcp_config.json", "json"),
        ("antigravity", home / ".gemini" / "antigravity-ide" / "mcp_config.json", "json"),
        ("workspace", _root() / ".mcp.json", "json"),
        ("codex", home / ".codex" / "config.toml", "toml"),
    ]
    servers: list[dict[str, Any]] = []
    for harness, path, kind in candidates:
        if kind == "toml":
            servers.extend(_extract_codex_mcp_servers(path))
        else:
            servers.extend(_extract_json_mcp_servers(path, harness))
    return servers


async def mcp_inventory(fragmented_only: bool = False) -> dict[str, Any]:
    """Inventory MCP server config across Claude, Codex, Gemini, Antigravity, and workspace config."""
    servers = _all_mcp_servers()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for server in servers:
        grouped.setdefault(str(server.get("name", "")), []).append(server)
    fragmentation = []
    for name, rows in sorted(grouped.items()):
        if len(rows) < 2:
            continue
        fingerprints = {_server_fingerprint(row) for row in rows}
        fragmentation.append({
            "name": name,
            "harnesses": sorted(str(row.get("harness")) for row in rows),
            "harness_count": len(rows),
            "consistent": len(fingerprints) == 1,
        })
    visible_servers = [
        server for server in servers
        if not fragmented_only or len(grouped.get(str(server.get("name", "")), [])) > 1
    ]
    return {
        "status": "completed",
        "schema_version": "agent-harness.mcp-inventory.v1",
        "aggregates": {
            "server_count": len(servers),
            "harness_count": len({str(server.get("harness")) for server in servers}),
            "duplicate_server_count": len(fragmentation),
            "inconsistent_server_count": sum(1 for item in fragmentation if not item["consistent"]),
            "servers_with_secret_env": sum(1 for server in servers if server.get("has_secrets")),
        },
        "fragmentation": fragmentation,
        "servers": _redact_value(visible_servers),
        "note": "Secret values are never returned; only env key names are listed.",
    }


def _path_mentions_current_server(values: list[str]) -> bool:
    expected = HARNESS_SERVER_FILE.resolve()
    for value in values:
        text = str(value).strip().strip('"').strip("'")
        if not text:
            continue
        candidate = Path(text)
        if candidate.name.lower() != "mcp_server.py":
            continue
        try:
            if candidate.exists() and candidate.resolve() == expected:
                return True
        except OSError:
            pass
        if text.replace("\\", "/").endswith(str(expected).replace("\\", "/")):
            return True
    return False


def _agent_harness_server(harness: str) -> dict[str, Any] | None:
    for server in _all_mcp_servers():
        if server.get("harness") == harness and server.get("name") == "agent-harness":
            return server
    return None


def _adapter_record(target: str, rules_path: Path, markers: list[str], mcp_harness: str) -> dict[str, Any]:
    text = _read_text_safe(rules_path)
    server = _agent_harness_server(mcp_harness)
    rule_ok = rules_path.exists() and all(marker in text for marker in markers)
    server_values = []
    if server:
        server_values.extend([str(server.get("command") or ""), str(server.get("url") or "")])
        server_values.extend(str(arg) for arg in server.get("args", []))
    mcp_ok = bool(server and server.get("enabled") and _path_mentions_current_server(server_values))
    issues = []
    if not rules_path.exists():
        issues.append("rules file missing")
    elif not rule_ok:
        issues.append("rules marker/profile policy missing or stale")
    if not server:
        issues.append("agent-harness MCP server missing")
    elif not mcp_ok:
        issues.append("MCP server disabled or points at a different mcp_server.py")
    return {
        "target": target,
        "rules_file": _display_path(str(rules_path)),
        "rules_ok": rule_ok,
        "mcp_ok": mcp_ok,
        "server": _redact_value(server or {}),
        "status": "ok" if not issues else "error",
        "issues": issues,
    }


async def adapter_parity_doctor() -> dict[str, Any]:
    """Check cross-agent rules/MCP parity for Claude, Codex, Gemini, and Antigravity."""
    home = Path.home()
    records = [
        _adapter_record("claude", home / ".claude" / "CLAUDE.md", ["agent-harness-managed", "Runtime Profile Policy"], "claude"),
        _adapter_record("codex", home / ".codex" / "AGENTS.md", ["agent-harness-runtime-profile-policy", "Runtime Profile Policy"], "codex"),
        _adapter_record("gemini", home / ".gemini" / "GEMINI.md", ["agent-harness", "Runtime Profile Policy"], "gemini"),
        _adapter_record("antigravity", home / ".gemini" / "GEMINI.md", ["agent-harness", "Runtime Profile Policy"], "antigravity"),
    ]
    missing_user_agents = not (home / "AGENTS.md").exists()
    if missing_user_agents:
        records.append({
            "target": "generic-user-agents",
            "rules_file": _display_path(str(home / "AGENTS.md")),
            "rules_ok": False,
            "mcp_ok": None,
            "server": {},
            "status": "warning",
            "issues": ["~/AGENTS.md missing; Codex fallback/user-level generic agents may miss shared policy"],
        })
    return {
        "status": "completed",
        "ready": all(record["status"] == "ok" for record in records if record["target"] != "generic-user-agents"),
        "current_server": _display_path(str(HARNESS_SERVER_FILE)),
        "records": records,
        "summary": {
            "ok": sum(1 for record in records if record["status"] == "ok"),
            "warnings": sum(1 for record in records if record["status"] == "warning"),
            "errors": sum(1 for record in records if record["status"] == "error"),
        },
    }


def _scan_skill_budgets(root: Path, label: str, limit: int = 200) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    rows = []
    try:
        skill_files = sorted(root.glob("*/SKILL.md"))[:limit]
    except OSError:
        return []
    for path in skill_files:
        rows.append(_file_budget(path, f"{label}:{path.parent.name}", "skill"))
    return rows


def _mcp_tool_count() -> int:
    text = _read_text_safe(HARNESS_SERVER_FILE, max_bytes=3_000_000)
    return len(set(re.findall(r'name="([A-Za-z0-9_ -]+)"', text)))


def _auto_watch_status() -> dict[str, Any]:
    pid_path = _root() / ".harness_auto_watch.pid"
    log_path = _root() / ".harness_auto_watch.log"
    pid = None
    alive = False
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text(encoding="utf-8", errors="replace").strip().split()[0])
        except (OSError, ValueError, IndexError):
            pid = None
    if pid:
        if os.name == "nt":
            rc, out, _err = _run_cmd_safe(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], cwd=str(_root()), timeout=5)
            alive = rc == 0 and str(pid) in out
        else:
            alive = Path(f"/proc/{pid}").exists()
    return {
        "pid": pid,
        "alive": alive,
        "pid_file": _display_path(str(pid_path)),
        "log_file": _display_path(str(log_path)),
        "log_exists": log_path.exists(),
    }


def _feature_snapshot() -> dict[str, Any]:
    path = _root() / "harness.features.json"
    data = _read_json_safe(path)
    return {
        "path": _display_path(str(path)),
        "exists": path.exists(),
        "profile": data.get("profile"),
        "llm_enabled": bool((data.get("llm") or {}).get("enabled")) if isinstance(data.get("llm"), dict) else None,
        "auto_watch_enabled": bool((data.get("auto_watch") or {}).get("enabled")) if isinstance(data.get("auto_watch"), dict) else None,
        "auto_watch_llm": bool((data.get("auto_watch") or {}).get("llm")) if isinstance(data.get("auto_watch"), dict) else None,
        "auto_pilot_enabled": bool((data.get("auto_pilot") or {}).get("enabled")) if isinstance(data.get("auto_pilot"), dict) else None,
        "auto_pilot_llm": bool((data.get("auto_pilot") or {}).get("llm")) if isinstance(data.get("auto_pilot"), dict) else None,
        "finops_enabled": bool((data.get("finops") or {}).get("enabled")) if isinstance(data.get("finops"), dict) else None,
        "lessons_enabled": bool((data.get("lessons") or {}).get("enabled")) if isinstance(data.get("lessons"), dict) else None,
    }


def _sqlite_row_count(path: Path, table: str) -> int | None:
    if not path.exists():
        return None
    try:
        with sqlite3.connect(str(path), timeout=1.0) as conn:
            row = conn.execute(f"select count(*) from {table}").fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error:
        return None


async def context_budget(include_home: bool = True, verbose: bool = False) -> dict[str, Any]:
    """Estimate static context/tool overhead and summarize runtime status without calling 9Router."""
    home = Path.home()
    workspace = _root()
    files = [
        _file_budget(workspace / "AGENTS.md", "workspace:AGENTS.md", "rules"),
        _file_budget(workspace / ".Codex" / "index.md", "workspace:.Codex/index.md", "memory"),
        _file_budget(workspace / ".Codex" / "decisions.md", "workspace:.Codex/decisions.md", "memory"),
        _file_budget(HARNESS_ROOT / "README.md", "harness:README.md", "docs"),
        _file_budget(HARNESS_ROOT / "harness.install.json", "harness:install-manifest", "manifest"),
    ]
    if include_home:
        files.extend([
            _file_budget(home / ".claude" / "CLAUDE.md", "claude:CLAUDE.md", "rules"),
            _file_budget(home / ".gemini" / "GEMINI.md", "gemini:GEMINI.md", "rules"),
            _file_budget(home / ".codex" / "AGENTS.md", "codex:AGENTS.md", "rules"),
            _file_budget(home / "AGENTS.md", "home:AGENTS.md", "rules"),
        ])
        files.extend(_scan_skill_budgets(home / ".claude" / "skills", "claude-skill"))
        files.extend(_scan_skill_budgets(home / ".codex" / "skills", "codex-skill"))
        files.extend(_scan_skill_budgets(home / ".agents" / "skills", "agents-skill"))
    mcp_tools = _mcp_tool_count()
    mcp_tool_tokens = mcp_tools * 500
    existing_files = [item for item in files if item["exists"]]
    component_tokens = sum(int(item["estimated_tokens"]) for item in existing_files)
    total_tokens = component_tokens + mcp_tool_tokens
    heavy_files = sorted(
        [item for item in existing_files if int(item["estimated_tokens"]) > 2_000 or int(item["lines"]) > 250],
        key=lambda item: int(item["estimated_tokens"]),
        reverse=True,
    )[:20]
    issues = []
    if mcp_tools > 80:
        issues.append("MCP tool schema overhead is high; prefer static bundled tools over adding more MCP servers.")
    for item in heavy_files[:5]:
        issues.append(f"{item['label']} is heavy (~{item['estimated_tokens']} tokens, {item['lines']} lines).")
    profile = _feature_snapshot()
    status_bits = {
        "profile": profile,
        "auto_watch": _auto_watch_status(),
        "finops": {
            "db": _display_path(str(workspace / ".harness_finops.db")),
            "exists": (workspace / ".harness_finops.db").exists(),
            "runs_count": _sqlite_row_count(workspace / ".harness_finops.db", "runs"),
        },
        "lessons": {
            "local_file": _display_path(str(workspace / ".harness_lessons.jsonl")),
            "local_exists": (workspace / ".harness_lessons.jsonl").exists(),
            "global_file": _display_path(get_global_lessons_path()),
            "global_exists": Path(get_global_lessons_path()).exists(),
        },
    }
    payload = {
        "status": "completed",
        "schema_version": "agent-harness.context-budget.v1",
        "summary": {
            "estimated_static_tokens": total_tokens,
            "component_tokens": component_tokens,
            "mcp_tool_count": mcp_tools,
            "mcp_tool_estimated_tokens": mcp_tool_tokens,
            "files_counted": len(existing_files),
            "issues_count": len(issues),
        },
        "breakdown": {
            "by_category": {},
            "mcp_tools": {"count": mcp_tools, "estimated_tokens": mcp_tool_tokens},
        },
        "heavy_files": heavy_files,
        "issues": issues,
        "runtime_status": status_bits,
        "note": "Estimates are approximate: prose words*1.3, code chars/4, MCP tool schemas ~500 tokens/tool.",
    }
    by_category: dict[str, dict[str, int]] = payload["breakdown"]["by_category"]
    for item in existing_files:
        cat = str(item["category"])
        bucket = by_category.setdefault(cat, {"files": 0, "estimated_tokens": 0})
        bucket["files"] += 1
        bucket["estimated_tokens"] += int(item["estimated_tokens"])
    if verbose:
        payload["files"] = existing_files
    return payload


async def harness_doctor() -> dict[str, Any]:
    """Self-check harness install/runtime readiness."""
    rc, head, git_err = _run_cmd_safe(["git", "rev-parse", "--short", "HEAD"], cwd=str(_root()))
    adapters = await agent_adapters()
    parity = await adapter_parity_doctor()
    checks = {
        "workspace": _display_path(str(_root())),
        "git": {"ok": rc == 0, "head": head.strip(), "error": git_err},
        "llm_env": bool(os.getenv("ROUTER_BASE_URL") and os.getenv("ROUTER_API_KEY")),
        "rules_version": _rules_version(),
        "goal_state": bool(load_goal_state()),
        "runner_lock": _lock_status(),
        "agent_adapters": adapters["adapters"],
        "adapter_parity": parity["summary"],
        "runtime_profile": _feature_snapshot(),
        "auto_watch": _auto_watch_status(),
        "orchestrator_recent": _read_orchestrator(3),
    }
    problems = []
    if not checks["git"]["ok"]:
        problems.append("workspace is not a git repo")
    if not checks["llm_env"]:
        problems.append("9Router env is missing; LLM tools will degrade/fail")
    if not any(v.get("available") for v in checks["agent_adapters"].values() if isinstance(v, dict)):
        problems.append("no agent CLI adapter detected; goal_runner needs HARNESS_GOAL_AGENT_CMD or claude/gemini/codex")
    if not parity.get("ready"):
        problems.append("one or more agent adapters have stale/missing rules or MCP config")
    return {"status": "completed", "ready": not problems, "checks": checks, "problems": problems}


def _rules_version() -> dict[str, Any]:
    try:
        import merge_settings

        return {"current": merge_settings.RULES_VERSION, "installed": merge_settings.installed_rules_version()}
    except Exception as exc:
        return {"error": str(exc)}
