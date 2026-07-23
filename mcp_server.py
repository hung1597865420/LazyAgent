"""
Agent Harness - MCP Server (Support Toolbox cho Claude Code)
Claude Code gọi các tool này qua MCP protocol.

Đăng ký với Claude Code:
  claude mcp add agent-harness -- python "đường/dẫn/tới/mcp_server.py"
"""
import asyncio
import contextlib
import contextvars
import hashlib
import importlib
import logging
import json
import math
import os
import re
import subprocess
import sys
import threading
import ctypes
import time
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from agents import Agent, AgentRole, get_finops_stats
from config import MODELS, WORKSPACE_ROOT, get_llm_client, get_model_config
from runtime_flags import bool_flag
from tools.workspace_context import get_active_workspace_override, workspace_scope
import support_tools as st

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_log = logging.getLogger("harness.mcp")

app = Server("agent-harness")

# Registry giữ background tasks tránh GC + cho phép harvest khi cancel
_background_tasks: set[asyncio.Task] = set()
# Giới hạn đồng thời để tránh 9Router rate-limit khi spam cancel
_TOOL_SEM = asyncio.Semaphore(8)
_LAZY_SETTINGS_MERGE_DONE = False
_HOT_RELOAD_LOCK = asyncio.Lock()
_TOOL_INFLIGHT_COND = asyncio.Condition()
_TOOL_INFLIGHT = 0
_TOOL_CALL_DEPTH = contextvars.ContextVar("harness_tool_call_depth", default=0)
_HOT_RELOAD_SIGNATURES: dict[str, tuple[float, int, str]] = {}
_TOOL_SINGLE_FLIGHT_LOCK = asyncio.Lock()
_TOOL_SINGLE_FLIGHTS: dict[str, asyncio.Task] = {}
_TOOL_SINGLE_FLIGHT_RESULTS: dict[str, tuple[float, list[types.TextContent]]] = {}
_TOOL_SINGLE_FLIGHT_REPLAY_KEYS: set[str] = set()
_TOOL_SINGLE_FLIGHT_REPLAY_SECONDS = 60.0
_NO_BACKGROUND_ON_CANCEL_TOOLS = {
    "alt_implementation",
    "ask_codebase",
    "auto_trigger",
    "auto_tester",
    "benchmark_runner",
    "changelog_generator",
    "consult",
    "dependency_upgrader",
    "doc_sync",
    "goal_autopilot",
    "goal_runner",
    "panel_review",
    "lesson_curator",
    "prod_readiness_gate",
    "quick_task",
    "release_orchestrator",
    "run_single_agent",
    "security_autofix",
    "suggest_fix",
    "swarm_debug",
    "visual_reviewer",
    "wiki_ingest",
    "wiki_lint",
}
_MUTATING_TOOL_ACTIONS = {
    "hallmark_bridge": {"write_preflight"},
    "speckit_bridge": {"init", "scaffold"},
    "office_bridge": {"create", "set", "add", "remove", "batch", "raw_set", "open", "save", "close", "watch", "unwatch", "goto"},
    "goal_runner_control": {"resume", "cancel_stale"},
}
_READ_ONLY_TOOL_ACTIONS = {
    "hallmark_bridge": {"preflight", "audit_plan", "status"},
    "speckit_bridge": {"status", "snapshot", "audit_plan"},
    "office_bridge": {"status", "read", "dump", "validate"},
    "goal_runner_control": {"status"},
}
_TRUE_VALUES = {True, 1, "1", "true", "yes", "y", "on"}
_NON_IDENTITY_MUTATION_ARGS = {
    "allow_mutation",
    "timeout",
    "timeout_s",
    "timeout_ms",
    "max_output_tokens",
}
_SET_LIKE_SINGLE_FLIGHT_ARGS = {
    "changed_files",
    "exclude",
    "exclude_tools",
    "files",
    "include",
    "paths",
    "target_files",
}


def _normalize_tool_name(name: str) -> str:
    text = str(name or "").strip()
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _sort_dedupe_canonical_list(items: list) -> list:
    seen: set[str] = set()
    out: list = []
    for item in items:
        identity = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        if identity in seen:
            continue
        seen.add(identity)
        out.append(item)
    return sorted(out, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))


def _canonicalize_for_single_flight(value, key: str = ""):
    if isinstance(value, dict):
        canonical = {}
        for k, v in sorted(value.items(), key=lambda item: str(item[0])):
            key_s = str(k)
            canonical[key_s] = _canonicalize_for_single_flight(v, key_s)
        return canonical
    if isinstance(value, list):
        items = [_canonicalize_for_single_flight(item, key) for item in value]
        if key in _SET_LIKE_SINGLE_FLIGHT_ARGS:
            return _sort_dedupe_canonical_list(items)
        return items
    if isinstance(value, str):
        text = value.strip()
        if key in _SET_LIKE_SINGLE_FLIGHT_ARGS:
            return text
        lower = text.lower()
        if lower in {"true", "false"}:
            return lower == "true"
        if re.fullmatch(r"-?\d+", text):
            try:
                return int(text)
            except ValueError:
                return text
        if re.fullmatch(r"-?\d+\.\d+", text):
            try:
                return float(text)
            except ValueError:
                return text
        return text
    return value


def _boolish_true(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_VALUES
    return value in _TRUE_VALUES


def _mutation_identity_args(name: str, arguments: dict) -> dict:
    canonical = _canonicalize_for_single_flight(dict(arguments or {}))
    if "action" in canonical:
        canonical["action"] = str(canonical.get("action") or "").strip().lower()
    if name == "goal_autopilot":
        mode = str(canonical.get("mode") or "").strip().lower()
        if mode in {"complete", "block", "status"}:
            return {"mode": mode}
        if mode == "init":
            return {"mode": mode, "goal": canonical.get("goal")}
        if mode == "check":
            return {
                "mode": mode,
                "changed_files": canonical.get("changed_files", []),
                "diff": canonical.get("diff", ""),
                "task": canonical.get("task", ""),
                "context": canonical.get("context", ""),
            }
    if _tool_call_is_mutating(name, canonical):
        for key in _NON_IDENTITY_MUTATION_ARGS:
            canonical.pop(key, None)
    return canonical


def _single_flight_key(name: str, arguments: dict) -> str:
    name = _normalize_tool_name(name)
    canonical_args = _mutation_identity_args(name, arguments or {})
    payload = json.dumps(
        {
            "workspace": str(Path(_active_workspace()).resolve(strict=False)),
            "arguments": canonical_args,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{name}:{digest}"


def _extract_tool_file_args(arguments: dict) -> list[str]:
    if not isinstance(arguments, dict):
        return []
    files: list[str] = []
    for key in (
        "files",
        "changed_files",
        "target_files",
        "html_files",
        "file",
        "path",
        "paths",
        "file_path",
        "example_file",
        "env_file",
        "spec_path",
        "test_path",
    ):
        value = arguments.get(key)
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, (list, tuple, set)):
            candidates = list(value)
        else:
            continue
        for item in candidates:
            if isinstance(item, str) and item.strip():
                files.append(item)
    return files


def _workspace_for_tool_call(arguments: dict) -> str:
    workspace = _active_workspace()
    files = _extract_tool_file_args(arguments)
    if not files:
        return workspace
    try:
        from tools.core import resolve_workspace_for_files

        resolved = resolve_workspace_for_files(files)
        return str(resolved.get("resolved_workspace") or workspace)
    except Exception as exc:
        _log.debug("workspace auto-resolve skipped: %s", exc)
        return workspace


def _tool_call_is_mutating(name: str, arguments: dict) -> bool:
    name = _normalize_tool_name(name)
    if name in _NO_BACKGROUND_ON_CANCEL_TOOLS:
        return True
    action = str((arguments or {}).get("action") or "").strip().lower()
    if action:
        if action in _MUTATING_TOOL_ACTIONS.get(name, set()):
            return True
        if action in _READ_ONLY_TOOL_ACTIONS.get(name, set()):
            return False
        if name in _MUTATING_TOOL_ACTIONS or name in _READ_ONLY_TOOL_ACTIONS:
            return True
    if isinstance(arguments, dict) and _boolish_true(arguments.get("allow_mutation")):
        return True
    return False


def _allow_background_after_cancel(name: str, arguments: dict) -> bool:
    return not _tool_call_is_mutating(name, arguments)


def _prune_single_flight_results(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    expired = [key for key, (expiry, _result) in _TOOL_SINGLE_FLIGHT_RESULTS.items() if expiry <= now]
    for key in expired:
        _TOOL_SINGLE_FLIGHT_RESULTS.pop(key, None)


async def _forget_single_flight(key: str, task: asyncio.Task) -> None:
    async with _TOOL_SINGLE_FLIGHT_LOCK:
        if _TOOL_SINGLE_FLIGHTS.get(key) is task:
            _TOOL_SINGLE_FLIGHTS.pop(key, None)
            replay_requested = key in _TOOL_SINGLE_FLIGHT_REPLAY_KEYS
            _TOOL_SINGLE_FLIGHT_REPLAY_KEYS.discard(key)
            if replay_requested and not task.cancelled():
                try:
                    result = task.result()
                except Exception:
                    result = None
                if result:
                    _TOOL_SINGLE_FLIGHT_RESULTS[key] = (
                        time.monotonic() + _TOOL_SINGLE_FLIGHT_REPLAY_SECONDS,
                        result,
                    )
                    if len(_TOOL_SINGLE_FLIGHT_RESULTS) > 512:
                        _prune_single_flight_results()


def _module_signature(path: str) -> tuple[float, int, str]:
    stat = os.stat(path)
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return stat.st_mtime, stat.st_size, digest.hexdigest()


for _name, _module in list(sys.modules.items()):
    if not (_name == "tools" or _name.startswith("tools.") or _name == "support_tools"):
        continue
    _path = getattr(_module, "__file__", None)
    if not _path:
        continue
    try:
        _HOT_RELOAD_SIGNATURES[_name] = _module_signature(_path)
    except OSError:
        pass


@app.list_resources()
async def list_resources() -> list[types.Resource]:
    return []


@app.list_resource_templates()
async def list_resource_templates() -> list[types.ResourceTemplate]:
    return []


def _cleanup_orphaned_worktrees() -> None:
    """Xóa git worktrees bị bỏ lại từ lần chạy trước bị crash.
    Dùng 'git worktree list --porcelain' để chỉ remove đúng worktrees do harness tạo.
    """
    workspace = (os.getenv("CLAUDE_PROJECT_DIR") or "").strip()
    if not workspace:
        meta = os.getenv("ANTIGRAVITY_SOURCE_METADATA")
        if meta:
            try:
                workspace = str(json.loads(meta).get("tool", {}).get("workspacePath") or "").strip()
            except Exception:
                workspace = ""
    repo = Path(workspace or (os.getenv("WORKSPACE_ROOT") or "").strip() or WORKSPACE_ROOT)
    if not repo.is_dir():
        return
    try:
        r = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(repo), capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return
        # Parse porcelain: mỗi worktree block bắt đầu bằng "worktree <path>"
        for line in r.stdout.splitlines():
            if not line.startswith("worktree "):
                continue
            wt_path = Path(line[len("worktree "):].strip())
            try:
                wt_resolved = wt_path.resolve()
                repo_resolved = repo.resolve()
                under_repo = os.path.commonpath([str(wt_resolved), str(repo_resolved)]) == str(repo_resolved)
            except (OSError, ValueError):
                under_repo = False
            git_meta = wt_path / ".git"
            if (under_repo
                    and wt_path.name.startswith(".harness_worktree_")
                    and wt_path.is_dir()
                    and not wt_path.is_symlink()
                    and git_meta.exists()
                    and not git_meta.is_dir()):
                try:
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(wt_path)],
                        cwd=str(repo), capture_output=True, timeout=10,
                    )
                    _log.info("Cleaned orphaned worktree: %s", wt_path.name)
                except Exception as e:
                    _log.debug("Worktree cleanup skip %s: %s", wt_path.name, e)
    except Exception as e:
        _log.debug("Worktree list failed: %s", e)


_cleanup_orphaned_worktrees()

STR_TO_ROLE: dict[str, AgentRole] = {r.value: r for r in AgentRole}

_AGENT_METADATA = {
    AgentRole.MANAGER:     {"tool": "ask_codebase",       "specialty": "Q&A trên codebase lớn — 1M token context. Gọi TRƯỚC khi đọc file nếu task >1 file"},
    AgentRole.SYNTHESIZER: {"tool": "panel_review",       "specialty": "Merge/dedupe findings từ review panel"},
    AgentRole.ANALYZER:    {"tool": "consult",            "specialty": "Design questions, trade-offs (deep reasoning)"},
    AgentRole.CODE_A:      {"tool": "alt_implementation", "specialty": "Phương án implementation 1 — code-focused, nhanh"},
    AgentRole.CODE_B:      {"tool": "alt_implementation", "specialty": "Phương án implementation 2 — chủ động khác biệt"},
    AgentRole.REVIEWER:    {"tool": "panel_review",       "specialty": "Bugs, logic errors, anti-patterns, performance"},
    AgentRole.TESTER:      {"tool": "panel_review",       "specialty": "Adversarial devil's advocate — race condition, hidden assumption, edge case mà quality/security bỏ sót"},
    AgentRole.SECURITY:    {"tool": "panel_review",       "specialty": "Injection, XSS, auth flaws, secrets"},
    AgentRole.INTEGRITY:   {"tool": "panel_review",       "specialty": "Data integrity, partial failure gaps, final synthesis guard"},
    AgentRole.SCANNER:     {"tool": "dead_code_scanner",  "specialty": "Static analysis enrichment: dead code, complexity, duplicates, perf hotspots"},
    AgentRole.DEBUGGER:    {"tool": "suggest_fix",        "specialty": "Root cause + patch dạng unified diff"},
    AgentRole.WORKER:      {"tool": "quick_task",         "specialty": "Boilerplate, fixtures, docs, việc vặt"},
}
if set(_AGENT_METADATA) != set(AgentRole):
    missing = set(AgentRole) - set(_AGENT_METADATA)
    extra = set(_AGENT_METADATA) - set(AgentRole)
    raise RuntimeError(f"AGENT_METADATA mismatch: missing={missing}, extra={extra}")

AGENT_INFO = [
    {"role": role.value, **_AGENT_METADATA[role]}
    for role in AgentRole
]

MCP_LESSON_FALLBACK_TOOLS = {
    "quick_task", "consult", "alt_implementation", "suggest_fix", "ask_codebase",
    "context_auditor", "swarm_debug", "incident_responder", "run_single_agent",
}
MCP_LESSON_BACKGROUND_LIMIT = 64
MCP_MEMORY_BACKGROUND_LIMIT = 128
_mcp_memory_slots = threading.BoundedSemaphore(MCP_MEMORY_BACKGROUND_LIMIT)

def _model_by_role() -> dict[str, str]:
    models = get_model_config()
    return {role.value: getattr(models, role.value) for role in AgentRole}

_FILES_SCHEMA = {
    "type": "array", "items": {"type": "string"},
    "description": f"Danh sách file paths (tương đối từ WORKSPACE_ROOT: {WORKSPACE_ROOT})",
}


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    _ensure_lazy_settings_merge()
    return [
        types.Tool(
            name="auto_trigger",
            description=(
                "Auto-Pilot: sau Edit/Write hoặc trước khi hoàn thành, tự chọn và chạy các harness checks phù hợp "
                "(secret/env/config/devops/complexity/dead-code/duplicate/panel_review). "
                "Đây là post-edit/final verification, KHÔNG thay thế BA/ask_codebase/consult preflight trước khi code. "
                "mode=max để vắt 9Router mạnh nhất; tránh gửi .env thật vào panel_review."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "changed_files": _FILES_SCHEMA,
                    "diff": {"type": "string", "description": "Unified diff hoặc summary diff nếu có"},
                    "task": {"type": "string", "description": "Task/user request hiện tại để chọn checks"},
                    "stage": {"type": "string", "enum": ["post_edit", "final", "pre_complete"], "description": "Vị trí gọi auto-pilot"},
                    "mode": {"type": "string", "enum": ["max", "safe"], "description": "max=vắt 9Router mạnh nhất; safe=chỉ chạy khi có rủi ro rõ"},
                    "exclude_tools": {
                        "description": "Optional tool name(s) to skip for this auto_trigger run",
                        "oneOf": [
                            {"type": "array", "items": {"type": "string"}},
                            {"type": "string"},
                        ],
                    },
                },
            },
        ),
        types.Tool(
            name="preflight_trigger",
            description=(
                "Static pre-code lifecycle router: phân bổ BA discovery, market research, ask_codebase, consult, "
                "Hallmark/Spec Kit/UI preflight trước khi agent plan/code. Không gọi LLM, không mutate; trả run_now + do_not_run_yet."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "changed_files": _FILES_SCHEMA,
                    "diff": {"type": "string", "description": "Diff/context nếu đã có, thường để trống trước code"},
                    "task": {"type": "string", "description": "User request hiện tại để route preflight"},
                    "mode": {"type": "string", "enum": ["max", "safe"], "description": "Mode dự kiến cho later checks; profile vẫn thắng"},
                },
            },
        ),
        types.Tool(
            name="tool_lifecycle",
            description=(
                "Static map phân bổ toàn bộ MCP tools theo vòng đời: session/setup, preflight_before_code, "
                "during_implementation, post_edit_batch, background_watch, final_review, release_gate, memory/docs/ops."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="session_heartbeat",
            description="Static cross-session coordinator heartbeat. Registers this agent/session/workspace without LLM.",
            inputSchema={"type": "object", "properties": {
                "session_id": {"type": "string"},
                "agent_kind": {"type": "string"},
                "task": {"type": "string"},
                "status": {"type": "string"},
            }},
        ),
        types.Tool(
            name="coordination_status",
            description="Static cross-session status: active sessions, file leases, conflicts, and recent coordination events.",
            inputSchema={"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}}},
        ),
        types.Tool(
            name="active_sessions",
            description="List active/stale harness sessions for this workspace from the coordinator DB.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="claim_files",
            description="Claim file/symbol lease before editing. Static SQLite guard for multi-session/multi-agent coordination.",
            inputSchema={"type": "object", "properties": {
                "files": _FILES_SCHEMA,
                "session_id": {"type": "string"},
                "agent_kind": {"type": "string"},
                "task": {"type": "string"},
                "symbols": {"oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}]},
                "lease_mode": {"type": "string"},
                "ttl_seconds": {"type": "number"},
                "allow_shared": {"type": "boolean"},
            }},
        ),
        types.Tool(
            name="release_files",
            description="Release file leases for current/session after task or when switching scope.",
            inputSchema={"type": "object", "properties": {
                "files": _FILES_SCHEMA,
                "session_id": {"type": "string"},
            }},
        ),
        types.Tool(
            name="conflict_check",
            description="Check unresolved cross-session file/hash/lease conflicts before auto_trigger, panel, final, or commit.",
            inputSchema={"type": "object", "properties": {
                "files": _FILES_SCHEMA,
                "session_id": {"type": "string"},
                "task": {"type": "string"},
                "stage": {"type": "string"},
                "require_lease": {"type": "boolean", "description": "Force missing-lease warnings. Defaults to strict for final/commit/release stages and quiet for auto_trigger/watch."},
            }},
        ),
        types.Tool(
            name="takeover_stale_claim",
            description="Take over stale file leases only. Active owners remain blocked unless user decides.",
            inputSchema={"type": "object", "properties": {
                "files": _FILES_SCHEMA,
                "session_id": {"type": "string"},
            }},
        ),
        types.Tool(
            name="coordination_policy",
            description="Return static profile-aware coordination policy: warning/block/exclusive/advisor rules.",
            inputSchema={"type": "object", "properties": {"profile": {"type": "string"}}},
        ),
        types.Tool(
            name="coordination_events",
            description="Read recent static cross-session coordination events/conflicts.",
            inputSchema={"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}}},
        ),
        types.Tool(
            name="coordination_advisor",
            description="Optional profile-gated conflict advisor. Static-first; does not call LLM unless a future explicit policy allows it.",
            inputSchema={"type": "object", "properties": {
                "files": _FILES_SCHEMA,
                "session_id": {"type": "string"},
                "task": {"type": "string"},
            }},
        ),
        types.Tool(
            name="integration_router",
            description=(
                "Static router for distilled Hallmark UI flow, UI Skills routing, and Spec Kit spec-first flow. "
                "Does not call LLM or mutate files; reports who should call each flow under the current profile."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "changed_files": _FILES_SCHEMA,
                    "diff": {"type": "string", "description": "Unified diff hoặc summary diff nếu có"},
                    "task": {"type": "string", "description": "Task/user request hiện tại"},
                },
            },
        ),
        types.Tool(
            name="workflow_router",
            description=(
                "Static Matt-skills-inspired router for BA discovery/market research advisor/UI-UX advisor/spec/tickets/debug/wayfinder/domain/review/TDD/architecture flows. "
                "No LLM, no mutation."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "changed_files": _FILES_SCHEMA,
                    "diff": {"type": "string", "description": "Unified diff hoặc summary diff nếu có"},
                    "task": {"type": "string", "description": "Task/user request hiện tại"},
                },
            },
        ),
        types.Tool(
            name="bug_repro_guard",
            description=(
                "Static debug guard: verifies a bug task has a red-capable repro command/output before hypothesis-first fixing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "error_log": {"type": "string"},
                    "changed_files": _FILES_SCHEMA,
                    "commands": {"type": "array", "items": {"type": "string"}},
                    "test_output": {"type": "string"},
                    "diff": {"type": "string"},
                },
            },
        ),
        types.Tool(
            name="ui_skill_router",
            description=(
                "Static ibelick UI Skills router: selects at most 3 compact UI checklists "
                "(ui-ux-advisor/baseline/a11y/motion/metadata/improve-ui) before heavy review."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "changed_files": _FILES_SCHEMA,
                    "task": {"type": "string"},
                },
            },
        ),
        types.Tool(
            name="hallmark_bridge",
            description=(
                "Hallmark-compatible UI bridge: status/preflight/audit_plan are static; "
                "write_preflight writes .hallmark/preflight.json only when allowed by profile and allow_mutation."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["status", "preflight", "audit_plan", "write_preflight"]},
                    "task": {"type": "string"},
                    "files": _FILES_SCHEMA,
                    "allow_mutation": {"type": "boolean"},
                },
            },
        ),
        types.Tool(
            name="speckit_bridge",
            description=(
                "Spec Kit bridge: status/snapshot read existing spec artifacts; "
                "init can call specify CLI and scaffold can write specs/<feature> docs when profile/allow_mutation permit."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["status", "snapshot", "init", "scaffold"]},
                    "task": {"type": "string"},
                    "feature": {"type": "string"},
                    "integration": {"type": "string", "enum": ["claude", "codex", "gemini", "agy"]},
                    "allow_mutation": {"type": "boolean"},
                },
            },
        ),
        types.Tool(
            name="scope_creep_detector",
            description=(
                "Static scope guard distilled from awesome-llm-apps: compares git diff against the stated task "
                "and flags likely unrelated dependency/config/CI/API rename/large-hunk changes. Local only, no LLM."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "changed_files": _FILES_SCHEMA,
                    "diff": {"type": "string", "description": "Unified diff. If omitted, tool runs local git diff with --no-ext-diff --no-textconv."},
                    "task": {"type": "string", "description": "Stated user intent/task to compare against changed paths/content."},
                    "staged": {"type": "boolean", "description": "Use git diff --cached when diff is omitted."},
                    "base": {"type": "string", "description": "Optional base ref for git diff base...HEAD when diff is omitted."},
                    "hunk_threshold": {"type": "integer", "description": "Added+removed line threshold for large_hunk signal. Default 80."},
                },
            },
        ),
        types.Tool(
            name="office_bridge",
            description=(
                "Optional OfficeCLI bridge for .docx/.xlsx/.pptx. status/help/view/validate/get/query/dump are read-only; "
                "create/set/add/remove/batch/watch/resident actions require allow_mutation=true and a profile above off. "
                "Never installs OfficeCLI or DesktopCommander."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": [
                        "status", "help", "view", "validate", "get", "query", "dump", "plugins",
                        "create", "set", "add", "remove", "batch", "raw_set", "open", "save", "close", "watch", "unwatch", "goto",
                    ]},
                    "file": {"type": "string", "description": "Workspace-relative .docx/.xlsx/.pptx path."},
                    "mode": {"type": "string", "description": "view mode: outline/text/issues/html/screenshot/stats/etc."},
                    "path": {"type": "string", "description": "OfficeCLI path for get/dump subtree or advanced commands."},
                    "selector": {"type": "string", "description": "OfficeCLI selector for query."},
                    "command": {"type": "string", "description": "Extra OfficeCLI command tail for help or advanced mutation actions."},
                    "output": {"type": "string", "description": "Workspace-relative output path for view/dump where supported."},
                    "allow_mutation": {"type": "boolean"},
                    "timeout": {"type": "integer", "description": "Command timeout seconds. Default 120."},
                },
            },
        ),
        types.Tool(
            name="prod_readiness_gate",
            description=(
                "Production readiness gate: gom auto_trigger final + security/env/secret/review/release checks "
                "và trả verdict cứng: ready_to_deploy, fix_required, blocked_needs_user, deploy_then_verify, rollback_required."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "changed_files": _FILES_SCHEMA,
                    "diff": {"type": "string", "description": "Unified diff hoặc summary diff nếu có"},
                    "task": {"type": "string", "description": "Task/user request hiện tại"},
                    "context": {"type": "string", "description": "Release/deploy context bổ sung"},
                    "staged": {"type": "boolean", "description": "True → dùng git diff --cached cho panel_review"},
                    "since_commit": {"type": "string", "description": "Base ref/SHA cho breaking change detector và review diff"},
                    "mode": {"type": "string", "enum": ["safe", "max"], "description": "safe=nhẹ/offline hơn; max=full pre-prod gate"},
                },
            },
        ),
        types.Tool(
            name="release_orchestrator",
            description="Release coordinator: checks git/changelog/SBOM evidence and returns ready/manual_steps/blocked before release.",
            inputSchema={"type": "object", "properties": {
                "changed_files": _FILES_SCHEMA,
                "diff": {"type": "string"},
                "context": {"type": "string"},
                "mode": {"type": "string", "enum": ["safe", "max"]},
            }},
        ),
        types.Tool(
            name="provenance_checker",
            description="Static build provenance checker: commit, remote, dependency evidence, artifact hashes, suspicious build scripts.",
            inputSchema={"type": "object", "properties": {
                "files": _FILES_SCHEMA,
                "context": {"type": "string"},
                "mode": {"type": "string", "enum": ["safe", "max"]},
            }},
        ),
        types.Tool(
            name="auth_matrix_auditor",
            description="Build endpoint/auth matrix and flag missing auth or object-level ownership checks.",
            inputSchema={"type": "object", "properties": {
                "files": _FILES_SCHEMA,
                "diff": {"type": "string"},
                "context": {"type": "string"},
                "mode": {"type": "string", "enum": ["safe", "max"]},
            }},
        ),
        types.Tool(
            name="harness_trace_viewer",
            description="View recent harness traces/logs from FinOps DB and .harness logs with secret redaction.",
            inputSchema={"type": "object", "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "include_logs": {"type": "boolean"},
                "mode": {"type": "string", "enum": ["safe", "max"]},
            }},
        ),
        types.Tool(
            name="incremental_refactor_guard",
            description="Detect public symbol removals/signature changes and syntax errors in refactor diffs.",
            inputSchema={"type": "object", "properties": {
                "files": _FILES_SCHEMA,
                "diff": {"type": "string"},
                "since_commit": {"type": "string"},
                "mode": {"type": "string", "enum": ["safe", "max"]},
            }},
        ),
        types.Tool(
            name="goal_autopilot",
            description=(
                "Prompt-only goal autopilot: init/check/complete/block/status. "
                "Stores one active goal and auto_trigger checks alignment after edits."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["init", "check", "complete", "block", "status"], "description": "Operation mode"},
                    "goal": {"type": "string", "description": "User goal; required for init"},
                    "context": {"type": "string", "description": "Progress note or extra context"},
                    "changed_files": _FILES_SCHEMA,
                    "diff": {"type": "string", "description": "Unified diff or summary diff if available"},
                    "task": {"type": "string", "description": "Current task/user request"},
                },
                "required": ["mode"],
            },
        ),
        types.Tool(
            name="goal_supervisor",
            description=(
                "Goal supervisor: reads active goal state/checks and returns one hard next_action enum: "
                "continue_part, run_check, run_final, blocked_ask_user, complete. Call after each edit/check batch."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "changed_files": _FILES_SCHEMA,
                    "diff": {"type": "string", "description": "Unified diff or summary diff if available"},
                    "context": {"type": "string", "description": "Progress note, user question, or completion summary"},
                    "last_checks": {"description": "Optional last auto_trigger/panel/check result object/list/string"},
                },
            },
        ),
        types.Tool(
            name="goal_runner",
            description=(
                "Direct prompt runner: initializes goal_autopilot from one prompt, delegates to an agent CLI, "
                "runs auto_trigger/goal_supervisor loop, then finalizes through prod_readiness_gate."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Prompt/goal to run directly through the harness"},
                    "max_iterations": {"type": "integer", "minimum": 1, "maximum": 30},
                    "mode": {"type": "string", "enum": ["safe", "max"]},
                    "agent_command": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                        "description": "Optional command template or argv array; use {prompt} placeholder or prompt is appended",
                    },
                    "agent_timeout": {"type": "number", "minimum": 5, "maximum": 7200},
                    "dry_run": {"type": "boolean", "description": "True initializes/supervises but does not call an agent command"},
                    "final_prod_gate": {"type": "boolean", "description": "Run prod_readiness_gate before completing the goal"},
                },
                "required": ["prompt"],
            },
        ),
        types.Tool(
            name="goal_runner_control",
            description="Control direct goal runner: status, resume active goal, or cancel a stale runner lock.",
            inputSchema={"type": "object", "properties": {
                "action": {"type": "string", "enum": ["status", "resume", "cancel_stale"]},
                "prompt": {"type": "string"},
                "mode": {"type": "string", "enum": ["safe", "max"]},
                "dry_run": {"type": "boolean"},
            }},
        ),
        types.Tool(
            name="run_ledger",
            description="Read recent goal_runner/benchmark audit ledger entries.",
            inputSchema={"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}}},
        ),
        types.Tool(
            name="policy_profile",
            description="Return runtime profile rules and allowed auto_trigger mode. balanced/review use safe; only heavy/max/prod/paranoid use max.",
            inputSchema={"type": "object", "properties": {"profile": {"type": "string", "enum": ["off", "light", "standard", "balanced", "4", "review", "5", "heavy", "7", "max", "fast", "prod", "paranoid"]}}},
        ),
        types.Tool(
            name="agent_adapters",
            description="List supported agent CLI adapters and whether claude/gemini/codex/custom command is available.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="context_auditor",
            description="Audit context assembly for size, warnings, goal injection, and line-context presence without calling 9Router.",
            inputSchema={"type": "object", "properties": {
                "question": {"type": "string"},
                "files": _FILES_SCHEMA,
                "context": {"type": "string"},
            }},
        ),
        types.Tool(
            name="install_manifest",
            description="Static ECC-inspired setup manifest: list profiles/targets or render a dry-run install/check plan without mutating files.",
            inputSchema={"type": "object", "properties": {
                "action": {"type": "string", "enum": ["summary", "list", "plan", "check"]},
                "profile": {"type": "string", "enum": ["minimal", "standard", "full"]},
                "target": {"type": "string", "enum": ["claude", "codex", "gemini", "antigravity"]},
            }},
        ),
        types.Tool(
            name="adapter_parity_doctor",
            description="Static cross-agent parity check for Claude, Codex, Gemini, and Antigravity rules/MCP config drift.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="mcp_inventory",
            description="Inventory MCP configs across Claude/Codex/Gemini/Antigravity/workspace; redacts secret values and flags duplicated or drifted servers.",
            inputSchema={"type": "object", "properties": {
                "fragmented_only": {"type": "boolean"},
            }},
        ),
        types.Tool(
            name="context_budget",
            description="Estimate loaded rules/skills/MCP tool schema token overhead and include lightweight runtime status without calling 9Router.",
            inputSchema={"type": "object", "properties": {
                "include_home": {"type": "boolean"},
                "verbose": {"type": "boolean"},
            }},
        ),
        types.Tool(
            name="router_quota_status",
            description=(
                "Deprecated compatibility shim. The router quota/costguard feature was removed; "
                "this returns a migration message and never queries 9Router quota endpoints."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="ask_codebase_health",
            description="Dry-run local ask_codebase context path to catch overlarge or weak context before 9Router.",
            inputSchema={"type": "object", "properties": {
                "question": {"type": "string"},
                "files": _FILES_SCHEMA,
                "context": {"type": "string"},
            }},
        ),
        types.Tool(
            name="patch_safety_check",
            description="Apply a proposed patch in an isolated git worktree and run tests; never mutates main workspace.",
            inputSchema={"type": "object", "properties": {
                "patch": {"type": "string"},
                "files": _FILES_SCHEMA,
            }, "required": ["patch"]},
        ),
        types.Tool(
            name="benchmark_runner",
            description="Run a small benchmark task list through goal_runner, dry-run by default, and write ledger.",
            inputSchema={"type": "object", "properties": {
                "tasks": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string", "enum": ["safe", "max"]},
                "dry_run": {"type": "boolean"},
            }},
        ),
        types.Tool(
            name="harness_doctor",
            description="Self-check harness readiness: git, 9Router env, rules stamp, runner lock, and agent CLI adapters.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="lesson_curator",
            description="Classify local lessons, filter noise, and promote safe reusable procedure/workflow lessons to global memory. mode=max uses 9Router 3-agent adjudication.",
            inputSchema={"type": "object", "properties": {
                "limit": {"type": "integer", "description": "Số local lessons gần nhất cần scan"},
                "promote": {"type": "boolean", "description": "True để promote lesson đủ điều kiện lên global"},
                "dry_run": {"type": "boolean", "description": "True chỉ phân loại, không ghi global"},
                "mode": {"type": "string", "enum": ["safe", "max"], "description": "safe=static rules, max=9Router 3-agent adjudication"},
                "llm_limit": {"type": "integer", "description": "Số lesson candidate tối đa gửi 9Router"},
                "timeout": {"type": "number", "description": "Timeout mỗi 9Router agent, mặc định 15s"},
                "allow_untrusted_promote": {"type": "boolean", "description": "Mặc định false; true mới cho phép promote source không nằm trong trusted allowlist"},
            }},
        ),
        types.Tool(
            name="panel_review",
            description=(
                "3 model parallel (reviewer/security/tester adversarial) → findings JSON file/line/severity/fix. "
                "Mỗi finding có `triage`: `auto_fix` (áp ngay) hoặc `ask_user` (cần developer quyết). "
                "`warnings[]` chứa anti-consensus alert khi panel đồng thuận bất thường. "
                "Dùng SAU KHI code xong. Cung cấp ít nhất một trong: files, diff, code, staged, since_commit."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "files":        _FILES_SCHEMA,
                    "diff":         {"type": "string", "description": "Unified diff của thay đổi cần review"},
                    "code":         {"type": "string", "description": "Code snippet inline cần review"},
                    "focus":        {"type": "string", "description": "Trọng tâm review (vd: 'concurrency', 'auth flow')"},
                    "staged":       {"type": "boolean", "description": "True → tự lấy git diff --cached (staged changes). Không cần truyền files."},
                    "since_commit": {"type": "string",  "description": "SHA hoặc ref (vd: 'HEAD~3', 'main') → diff từ commit đó đến HEAD. Không cần truyền files."},
                    "fast":         {"type": "boolean", "description": "True → cap context nhỏ hơn và bỏ integrity stage để tránh timeout."},
                    "agent_timeout": {"type": "number", "description": "Timeout mỗi reviewer 9Router. MCP mặc định cap 75s để trả trước client timeout."},
                },
            },
        ),
        types.Tool(
            name="consult",
            description="Hỏi Sonnet (deep reasoning) trước khi implement: approach, trade-offs, edge cases. Kể cả quyết định nhỏ 'A hay B'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Câu hỏi design cụ thể"},
                    "files":    _FILES_SCHEMA,
                    "context":  {"type": "string", "description": "Context bổ sung (constraints, requirements...)"},
                },
                "required": ["question"],
            },
        ),
        types.Tool(
            name="alt_implementation",
            description="2 model song song sinh 2 approach khác nhau để so sánh. Dùng cho function/module độc lập.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spec":    {"type": "string", "description": "Spec của thứ cần implement"},
                    "files":   _FILES_SCHEMA,
                    "context": {"type": "string", "description": "Context bổ sung"},
                },
                "required": ["spec"],
            },
        ),
        types.Tool(
            name="suggest_fix",
            description="code + error → root cause + unified diff patch. Dùng khi debug bí sau 1-2 lần thử.",
            inputSchema={
                "type": "object",
                "properties": {
                    "error":   {"type": "string", "description": "Error message / stack trace / mô tả bug"},
                    "files":   _FILES_SCHEMA,
                    "code":    {"type": "string", "description": "Code bị lỗi (inline)"},
                    "context": {"type": "string", "description": "Context bổ sung (đã thử gì, repro steps...)"},
                },
                "required": ["error"],
            },
        ),
        types.Tool(
            name="ask_codebase",
            description="Q&A codebase lớn: đọc rộng, relevance-prune trước 9Router, fallback local có file:line nếu model timeout/empty. Gọi TRƯỚC khi Read nếu task >1 file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Câu hỏi về codebase"},
                    "files":    {**_FILES_SCHEMA, "description": _FILES_SCHEMA["description"] + " — nạp nhiều file thoải mái"},
                    "index_md": {"type": "string", "description": "Nội dung index.md làm navigation"},
                },
                "required": ["question"],
            },
        ),
        types.Tool(
            name="quick_task",
            description="Model mini cho việc vặt: boilerplate, fixtures, mock data, docstring, commit message, cập nhật index.md/decisions.md, tóm tắt diff, giải thích code. Không dùng cho logic phức tạp.",
            inputSchema={
                "type": "object",
                "properties": {
                    "instruction": {"type": "string", "description": "Việc cần làm"},
                    "task": {"type": "string", "description": "Alias tương thích cho instruction"},
                    "context":     {"type": "string", "description": "Input/context nếu cần"},
                },
            },
        ),
        types.Tool(
            name="run_single_agent",
            description="Escape hatch: gọi thẳng 1 trong 12 agent. Roles: " + ", ".join(STR_TO_ROLE.keys()) + ".",
            inputSchema={
                "type": "object",
                "properties": {
                    "role":    {"type": "string", "enum": list(STR_TO_ROLE.keys())},
                    "task":    {"type": "string", "description": "Task cần làm"},
                    "context": {"type": "string", "description": "Context bổ sung"},
                },
                "required": ["role", "task"],
            },
        ),
        types.Tool(
            name="list_agents",
            description="Xem 12 agents: model deployment, tool tương ứng, specialty.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="wiki_ingest",
            description="Ingest llmwiki/raw/ → trích xuất concepts/entities vào wiki. Chạy sau khi thêm file vào raw/.",
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "enum": ["local", "global"], "description": "local=project wiki (default), global=~/.claude/llmwiki/"},
                },
            },
        ),
        types.Tool(
            name="wiki_query",
            description="Tìm kiếm wiki concepts/entities theo từ khóa.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Từ khóa tìm kiếm"},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="wiki_lint",
            description="Kiểm tra wiki: link hỏng, trang trống, raw chưa ingest.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="security_autofix",
            description="Auto-fix Critical/High security findings: panel_review → suggest_fix → worktree test → apply patch → wiki lesson.",
            inputSchema={
                "type": "object",
                "properties": {
                    "files": _FILES_SCHEMA,
                },
                "required": ["files"],
            },
        ),
        types.Tool(
            name="auto_tester",
            description="Sinh pytest từ files + panel_review findings. Chạy trong worktree cô lập.",
            inputSchema={
                "type": "object",
                "properties": {
                    "files": _FILES_SCHEMA,
                    "findings": {"type": "array", "items": {"type": "object"}, "description": "Findings từ panel_review"}
                },
                "required": ["files", "findings"]
            }
        ),
        types.Tool(
            name="visual_reviewer",
            description="Screenshot URL + Vision LLM audit giao diện theo Executive Command UI criteria. So sánh với baseline nếu có.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL cần kiểm tra"},
                    "baseline_url": {"type": "string", "description": "URL baseline (tùy chọn)"}
                },
                "required": ["url"]
            }
        ),
        types.Tool(
            name="benchmarker",
            description="So sánh 2 đoạn Python: thời gian + bộ nhớ.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code_a": {"type": "string", "description": "Code thứ nhất"},
                    "code_b": {"type": "string", "description": "Code thứ hai"},
                    "iterations": {"type": "integer", "description": "Số lần chạy (mặc định 5)"}
                },
                "required": ["code_a", "code_b"]
            }
        ),
        types.Tool(
            name="dependency_upgrader",
            description="Quét package lỗi thời trong requirements.txt. dry_run=True chỉ báo cáo, không sửa.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dry_run": {"type": "boolean", "description": "Chỉ quét, không sửa (mặc định True)"}
                }
            }
        ),
        types.Tool(
            name="schema_drift",
            description="So sánh Pydantic models với baseline → phát hiện drift.",
            inputSchema={
                "type": "object",
                "properties": {
                    "baseline_schema": {"type": "string", "description": "Schema baseline JSON (tùy chọn)"}
                }
            }
        ),
        types.Tool(
            name="doc_sync",
            description="Đồng bộ README.md theo public functions mới.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="telemetry_debugger",
            description="stack trace → định vị file + đề xuất patch.",
            inputSchema={
                "type": "object",
                "properties": {
                    "log_content": {"type": "string", "description": "Log lỗi hoặc stack trace"}
                },
                "required": ["log_content"]
            }
        ),
        types.Tool(
            name="run_in_sandbox",
            description="Chạy Python code trong sandbox cô lập, giới hạn tài nguyên.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code cần chạy"},
                    "timeout": {"type": "number", "description": "Timeout giây (mặc định 5.0)"}
                },
                "required": ["code"]
            }
        ),
        types.Tool(
            name="semantic_search",
            description="Tìm file/hàm/class trong codebase — polyglot 158 ngôn ngữ, FTS5+tree-sitter. Index tự build.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Từ khóa tìm kiếm"},
                    "top_k": {"type": "integer", "description": "Số kết quả (mặc định 5)"}
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="swarm_debug",
            description="Multi-Agent Swarm (Architect→Tester→Coder→Reviewer) chẩn đoán và vá lỗi tự động.",
            inputSchema={
                "type": "object",
                "properties": {
                    "error_log": {"type": "string", "description": "Stack trace hoặc log lỗi"},
                    "files": _FILES_SCHEMA
                },
                "required": ["error_log"]
            }
        ),
        types.Tool(
            name="finops_stats",
            description="Thống kê FinOps: chi phí USD, tokens, latency, cache hit rate theo agent/run.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="devops_pipeline",
            description="Quality gate: ruff/flake8 + mypy + black (fallback AST).",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="config_security_audit",
            description="Quét secrets rò rỉ, .env drift, CORS unsafe.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="pr_generator",
            description="Sinh PR title + description từ git diff.",
            inputSchema={
                "type": "object",
                "properties": {
                    "diff": {"type": "string", "description": "Git diff (tùy chọn)"},
                    "branch": {"type": "string", "description": "Branch để diff (tùy chọn)"}
                }
            }
        ),
        types.Tool(
            name="license_scanner",
            description="Phát hiện licenses trong codebase, cảnh báo tương thích.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="sbom_generator",
            description="Sinh SBOM (SPDX JSON) từ dependencies. Dùng trước deploy production.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="a11y_auditor",
            description="Kiểm tra accessibility WCAG và Executive Command UI criteria trong HTML/CSS/JSX.",
            inputSchema={
                "type": "object",
                "properties": {"files": _FILES_SCHEMA}
            }
        ),
        types.Tool(
            name="i18n_auditor",
            description="Tìm hardcoded strings cần i18n trong UI code.",
            inputSchema={
                "type": "object",
                "properties": {"files": _FILES_SCHEMA}
            }
        ),
        types.Tool(
            name="polyglot_reviewer",
            description="Code review chuyên sâu theo ngôn ngữ đặc thù (polyglot).",
            inputSchema={
                "type": "object",
                "properties": {"files": _FILES_SCHEMA},
                "required": ["files"]
            }
        ),
        types.Tool(
            name="git_archaeologist",
            description="git blame nâng cao: tìm commit cuối thay đổi file/dòng cụ thể.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "File cần khảo cổ"},
                    "line_no": {"type": "integer", "description": "Dòng cần blame (tùy chọn)"}
                },
                "required": ["file_path"]
            }
        ),
        types.Tool(
            name="feature_flag_auditor",
            description="Phát hiện feature flags không dùng hoặc quá hạn trong codebase.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="dead_code_scanner",
            description="Phát hiện hàm/class không được gọi — polyglot 158 ngôn ngữ, tree-sitter.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="index_codebase",
            description="Build/rebuild codebase index (FTS5+tree-sitter, 158 ngôn ngữ). force=True rebuild hoàn toàn. Tự chạy khi semantic_search/dead_code_scanner/ask_codebase gọi lần đầu.",
            inputSchema={
                "type": "object",
                "properties": {
                    "force": {"type": "boolean", "description": "Rebuild hoàn toàn (mặc định False)"}
                }
            }
        ),
        types.Tool(
            name="review_context_graph",
            description="Static CRG-style review pre-pass: changed symbols, blast radius, test gaps, risk score, and estimated context savings. Does not call 9Router.",
            inputSchema={
                "type": "object",
                "properties": {
                    "changed_files": _FILES_SCHEMA,
                    "base": {"type": "string", "description": "Git ref to diff against (default HEAD~1)"},
                    "detail_level": {"type": "string", "description": "minimal or standard"},
                    "max_callers_per_symbol": {"type": "integer", "description": "Caller/reference cap per symbol"}
                }
            }
        ),
        types.Tool(
            name="graph_health",
            description="Static graph architecture health: hub nodes, bridge/chokepoint nodes, dead-code candidates, untested hotspots, suggested review questions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max items per section (default 10)"}
                }
            }
        ),
        types.Tool(
            name="graph_minimal_context",
            description="Ultra-compact local graph context for agents before expensive search/review. Does not call 9Router.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Current task description"},
                    "changed_files": _FILES_SCHEMA,
                    "base": {"type": "string", "description": "Git ref to diff against (default HEAD~1)"}
                }
            }
        ),
        types.Tool(
            name="profiler",
            description="cProfile + tracemalloc cho Python code. Tìm bottleneck CPU và memory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code cần profile"},
                    "iterations": {"type": "integer", "description": "Số vòng lặp (mặc định 1)"}
                },
                "required": ["code"]
            }
        ),
        types.Tool(
            name="coverage_analyzer",
            description="pytest + coverage.py → báo cáo test coverage.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="incident_responder",
            description="log/crash dump → phân loại incident + mitigation ngay + fix lâu dài.",
            inputSchema={
                "type": "object",
                "properties": {
                    "log_content": {"type": "string", "description": "Log hoặc crash dump"}
                },
                "required": ["log_content"]
            }
        ),
        types.Tool(
            name="api_contract_tester",
            description="Sinh pytest kiểm tra API contract (status code, JSON schema).",
            inputSchema={
                "type": "object",
                "properties": {
                    "endpoints": {"type": "array", "items": {"type": "object"}, "description": "Danh sách endpoint {path, method}"}
                },
                "required": ["endpoints"]
            }
        ),
        types.Tool(
            name="chaos_tester",
            description="Fault injection (CPU/memory stress) trong khi monitor ứng dụng.",
            inputSchema={
                "type": "object",
                "properties": {
                    "app_run_command": {"type": "string", "description": "Lệnh chạy app"},
                    "duration": {"type": "integer", "description": "Thời gian inject (mặc định 5s)"}
                },
                "required": ["app_run_command"]
            }
        ),
        types.Tool(
            name="secret_scanner",
            description="Tìm hardcoded secrets bằng regex + Shannon entropy (API key, token, private key).",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "Paths cần quét (mặc định toàn workspace)"}
                }
            }
        ),
        types.Tool(
            name="changelog_generator",
            description="Sinh changelog từ git log, nhóm theo conventional commit type.",
            inputSchema={
                "type": "object",
                "properties": {
                    "since": {"type": "string", "description": "Từ commit nào (mặc định HEAD~10)"},
                    "until": {"type": "string", "description": "Đến commit nào (mặc định HEAD)"},
                    "format": {"type": "string", "description": "'markdown' hoặc 'text' (mặc định markdown)"}
                }
            }
        ),
        types.Tool(
            name="env_parity_checker",
            description="So sánh keys .env vs .env.example — phát hiện thiếu/thừa.",
            inputSchema={
                "type": "object",
                "properties": {
                    "example_file": {"type": "string", "description": "Template (mặc định .env.example)"},
                    "env_file": {"type": "string", "description": "Env thực tế (mặc định .env)"}
                }
            }
        ),
        types.Tool(
            name="load_tester",
            description="HTTP load test concurrent → p50/p95/p99 latency, error rate, RPS.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL cần test"},
                    "requests_count": {"type": "integer", "description": "Tổng requests (mặc định 100)"},
                    "concurrency": {"type": "integer", "description": "Requests song song (mặc định 10)"},
                    "method": {"type": "string", "description": "HTTP method (mặc định GET)"}
                },
                "required": ["url"]
            }
        ),
        types.Tool(
            name="complexity_analyzer",
            description="Cyclomatic complexity từng function Python (AST). Flag hotspot > threshold.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "Paths cần phân tích (mặc định toàn workspace)"},
                    "threshold": {"type": "integer", "description": "Ngưỡng flag (mặc định 10)"}
                }
            }
        ),
        types.Tool(
            name="migration_validator",
            description="Validate SQL/Alembic migration: LOCK_RISK, NON_REVERSIBLE, MISSING_INDEX, DATA_LOSS.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "Migration files (mặc định tự tìm)"}
                }
            }
        ),
        types.Tool(
            name="sql_query_analyzer",
            description="Phát hiện N+1 query, thiếu index, raw SQL không parameterized (SQLAlchemy, Django ORM).",
            inputSchema={
                "type": "object",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Files cần phân tích (mặc định toàn .py)"}
                }
            }
        ),
        types.Tool(
            name="openapi_spec_sync",
            description="So sánh OpenAPI spec với route handlers + Pydantic models → UNDOCUMENTED_ENDPOINT, SCHEMA_MISMATCH.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spec_path": {"type": "string", "description": "OpenAPI spec path (mặc định tự tìm)"}
                }
            }
        ),
        types.Tool(
            name="breaking_change_detector",
            description="Phát hiện breaking API changes HEAD vs main: renamed param, removed field, status code change. Dùng trước PR.",
            inputSchema={
                "type": "object",
                "properties": {
                    "base_ref": {"type": "string", "description": "Base ref để diff (mặc định tự tìm main/master)"}
                }
            }
        ),
        types.Tool(
            name="flaky_test_detector",
            description="Chạy test N lần, phát hiện flaky tests (pass/fail không nhất quán).",
            inputSchema={
                "type": "object",
                "properties": {
                    "runs": {"type": "integer", "description": "Số lần chạy 2-5 (mặc định 3)"},
                    "test_path": {"type": "string", "description": "Test file/folder (mặc định toàn bộ)"}
                }
            }
        ),
        types.Tool(
            name="duplicate_code_scanner",
            description="Tìm copy-paste code bằng AST normalization — function tương đồng >80% nên extract.",
            inputSchema={
                "type": "object",
                "properties": {
                    "min_lines": {"type": "integer", "description": "Dòng tối thiểu để scan (mặc định 6)"},
                    "threshold": {"type": "number", "description": "Ngưỡng tương đồng 0-1 (mặc định 0.8)"}
                }
            }
        ),
        types.Tool(
            name="container_linter",
            description="Lint Dockerfile/docker-compose: root process, hardcoded secret, unpinned image, missing HEALTHCHECK.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "Dockerfile/compose paths (mặc định tự tìm)"}
                }
            }
        ),
        types.Tool(
            name="dependency_graph_visualizer",
            description="Python import graph: circular imports, God modules (fan-in ≥10), high coupling.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": ".py files (mặc định toàn workspace)"}
                }
            }
        ),
        types.Tool(
            name="ci_pipeline_validator",
            description="Validate GitHub Actions/GitLab CI: hardcoded secret, injection, no timeout, deprecated actions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "CI YAML paths (mặc định tự tìm .github/workflows/)"}
                }
            }
        ),
        types.Tool(
            name="mutation_tester",
            description="Inject mutations (flip bool, đổi operator) → chạy tests → mutation score. Score thấp = test yếu.",
            inputSchema={
                "type": "object",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Source files cần mutate (mặc định tự tìm non-test .py)"},
                    "max_mutations": {"type": "integer", "description": "Số mutations tối đa (mặc định 20)"}
                }
            }
        ),
        types.Tool(
            name="data_flow_taint_analyzer",
            description="Track user input → dangerous sinks (SQL, subprocess, template) → SQL/COMMAND/TEMPLATE_INJECTION, PATH_TRAVERSAL.",
            inputSchema={
                "type": "object",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Files cần phân tích (mặc định tự tìm)"}
                }
            }
        ),
        types.Tool(
            name="performance_regression_detector",
            description="git diff HEAD vs main → phát hiện O(n)→O(n²), unbounded memory, sync IO trong async path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "functions": {"type": "array", "items": {"type": "string"}, "description": "Functions cần kiểm tra (mặc định tự detect từ diff)"},
                    "threshold_pct": {"type": "number", "description": "Ngưỡng regression % (mặc định 20)"}
                }
            }
        ),
    ]


def _json_response(data) -> list[types.TextContent]:
    if data is None:
        data = {"error": "empty_tool_result", "detail": "Tool returned None instead of a JSON object."}
    if not isinstance(data, dict):
        data = {"status": "completed", "result": data}
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    except Exception as exc:
        text = json.dumps({
            "error": "json_response_serialization_failed",
            "detail": f"{type(exc).__name__}: {exc}",
            "repr": repr(data)[:4000],
        }, ensure_ascii=False, indent=2)
    if not text.strip():
        text = json.dumps({"error": "empty_tool_result", "detail": "Serialized response was empty."}, ensure_ascii=False)
    max_chars = 900_000
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [truncated by mcp_server._json_response]"
    return [types.TextContent(
        type="text", text=text,
    )]


def _maybe_record_mcp_tool_lesson(name: str, arguments: dict, response: list[types.TextContent]) -> dict:
    if "/" in name:
        name = name.split("/", 1)[-1]
    if name not in MCP_LESSON_FALLBACK_TOOLS:
        return {"status": "skipped", "reason": "tool not lesson fallback candidate"}
    try:
        from tools.core import _redact_lesson_value, record_procedure_lesson
        from tools.runner import _infer_agent_procedure_lesson

        safe_arguments = _redact_lesson_value(arguments or {})
        arg_text = _collect_lesson_text(safe_arguments)[:4_000]
        result_chunks = []
        for chunk in _mcp_response_text_chunks(response, max_chars=8_000):
            result_chunks.append(chunk)
        result_text = "\n".join(chunk[:8_000] for chunk in result_chunks)
        text = f"{arg_text}\n{result_text}"[:12_000]
        fallback = _infer_agent_procedure_lesson(f"mcp tool {name}", text)
        if not fallback:
            return {"status": "skipped", "reason": "no structured reusable workflow"}
        record = record_procedure_lesson(
            title=fallback["title"],
            summary=fallback["summary"],
            steps=fallback["steps"],
            tags=fallback["tags"],
            source="mcp_tool_fallback",
            refs={"tool": name},
        )
        return {"status": record.get("status"), "lesson_key": record.get("lesson_key"), "title": record.get("title")}
    except Exception as exc:
        _log.debug("MCP lesson fallback skipped for %s: %s", name, exc)
        return {"status": "skipped", "reason": type(exc).__name__}


def _lesson_marker_window(text: str, max_chars: int = 12_000) -> str:
    lower = text.lower()
    markers = ("reusable workflow", "procedure", "lesson learned", "summary:", "steps:")
    positions = [lower.find(marker) for marker in markers if lower.find(marker) >= 0]
    if not positions:
        return text[:max_chars]
    start = max(0, min(positions) - 1000)
    return text[start:start + max_chars]


def _mcp_response_text_chunks(response: list[types.TextContent], max_chars: int = 8_000) -> list[str]:
    from tools.core import _redact_lesson_value

    chunks: list[str] = []
    decoder = json.JSONDecoder()
    for item in (response or []):
        if getattr(item, "type", "") != "text":
            continue
        raw = str(item.text or "")
        if not raw:
            continue
        parsed = []
        idx = 0
        while idx < len(raw) and idx < 64_000 and len("\n".join(parsed)) < max_chars * 4:
            starts = [pos for pos in (raw.find("{", idx), raw.find("[", idx)) if pos >= 0]
            if not starts:
                break
            start = min(starts)
            try:
                obj, end = decoder.raw_decode(raw[start:])
            except ValueError:
                idx = start + 1
                continue
            parsed.append(_collect_lesson_text(_redact_lesson_value(obj))[:max_chars])
            idx = start + max(end, 1)
        if parsed:
            chunks.extend(piece for piece in parsed if piece)
            window = _lesson_marker_window(_collect_lesson_text(_redact_lesson_value(raw)), max_chars=max_chars)
            if window and window not in chunks:
                chunks.append(window)
        else:
            window = _lesson_marker_window(raw, max_chars=max_chars)
            chunks.append(_collect_lesson_text(_redact_lesson_value(window))[:max_chars])
    return chunks


def _collect_lesson_text(value, depth: int = 0) -> str:
    if depth > 6:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_collect_lesson_text(v, depth + 1) for v in value.values())
    if isinstance(value, list):
        return "\n".join(_collect_lesson_text(v, depth + 1) for v in value[:40])
    return str(value) if value is not None else ""


def _schedule_mcp_tool_lesson(name: str, arguments: dict, response: list[types.TextContent]) -> None:
    if not bool_flag("HARNESS_LESSONS_ENABLED", True, root=_active_workspace()):
        return
    if "/" in name:
        tool_name = name.split("/", 1)[-1]
    else:
        tool_name = name
    if tool_name not in MCP_LESSON_FALLBACK_TOOLS:
        return
    lesson_task_count = sum(
        1 for task in _background_tasks
        if not task.done() and str(task.get_name()).startswith("mcp-lesson-")
    )
    if lesson_task_count >= MCP_LESSON_BACKGROUND_LIMIT:
        _log.debug("MCP lesson fallback skipped for %s: background task cap reached", tool_name)
        return

    async def _run_lesson_record():
        try:
            await asyncio.wait_for(
                asyncio.to_thread(_maybe_record_mcp_tool_lesson, tool_name, dict(arguments or {}), list(response or [])),
                timeout=2.0,
            )
        except Exception as exc:
            _log.debug("MCP lesson fallback background failed for %s: %s", tool_name, exc)

    task = asyncio.create_task(_run_lesson_record(), name=f"mcp-lesson-{tool_name}")
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _schedule_mcp_memory_events(name: str, arguments: dict, response: list[types.TextContent], started_at: float) -> None:
    if not bool_flag("HARNESS_LESSONS_ENABLED", True, root=_active_workspace()):
        return
    tool_name = name.split("/", 1)[-1] if "/" in str(name) else str(name)
    if tool_name in {"list_agents", "finops_stats", "router_quota_status"}:
        return
    if not _mcp_memory_slots.acquire(blocking=False):
        _log.debug("MCP memory events skipped for %s: background task cap reached", tool_name)
        return

    async def _run_memory_events():
        try:
            from tools.core import record_text_memory_signals, record_tool_performance_memory
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            await asyncio.to_thread(record_tool_performance_memory, tool_name, duration_ms, response, dict(arguments or {}))
            signal_text = "\n".join([
                _collect_lesson_text(arguments or {})[:2500],
                "\n".join(_mcp_response_text_chunks(response, max_chars=2500))[:2500],
            ]).strip()
            if signal_text:
                await asyncio.to_thread(
                    record_text_memory_signals,
                    signal_text[:5000],
                    source=f"mcp:{tool_name}",
                    refs={"tool": tool_name},
                )
        except Exception as exc:
            _log.debug("MCP memory events skipped for %s: %s", tool_name, exc)
        finally:
            try:
                _mcp_memory_slots.release()
            except ValueError:
                pass

    try:
        task = asyncio.create_task(_run_memory_events(), name=f"mcp-memory-{tool_name}")
    except Exception:
        _mcp_memory_slots.release()
        raise
    _background_tasks.add(task)
    def _discard_memory_task(done_task: asyncio.Task) -> None:
        _background_tasks.discard(done_task)
    task.add_done_callback(_discard_memory_task)


def _parse_bool_arg(args: dict, name: str, default: bool = False) -> tuple[bool, str | None]:
    value = args.get(name, default)
    if isinstance(value, bool):
        return value, None
    if value is None:
        return default, None
    if isinstance(value, int) and value in (0, 1):
        return bool(value), None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True, None
        if normalized in {"false", "0", "no", "off"}:
            return False, None
    return default, f"Argument '{name}' must be boolean, got {value!r}"


def _parse_optional_bool_arg(args: dict, name: str) -> tuple[bool | None, str | None]:
    if name not in args or args.get(name) is None:
        return None, None
    parsed, error = _parse_bool_arg(args, name, default=False)
    return (None, error) if error else (parsed, None)


def _mcp_panel_timeout() -> float:
    try:
        configured = float(os.getenv("HARNESS_MCP_PANEL_TIMEOUT", "240"))
    except (TypeError, ValueError):
        configured = 240.0
    if not math.isfinite(configured) or configured <= 5:
        configured = 240.0
    return min(285.0, max(10.0, configured))


def _nonempty_str_list(value) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)


_wiki_ingest_targets: set[str] = set()
_wiki_ingest_lock = threading.Lock()
_lazy_settings_lock = threading.Lock()
_auto_watch_roots: set[str] = set()
_auto_watch_lock = threading.Lock()


def _ensure_lazy_settings_merge() -> None:
    global _LAZY_SETTINGS_MERGE_DONE
    if _LAZY_SETTINGS_MERGE_DONE:
        return
    with _lazy_settings_lock:
        if _LAZY_SETTINGS_MERGE_DONE:
            return
        try:
            import merge_settings
            if merge_settings.lazy_merge_if_needed():
                _log.info("Auto-merged Agent Harness rules version %s", merge_settings.RULES_VERSION)
        except Exception as e:
            _log.warning("Auto-merge settings skipped (non-fatal): %s", e)
        finally:
            _LAZY_SETTINGS_MERGE_DONE = True


def _reloadable_tool_modules() -> list[str]:
    names = [
        name for name in sys.modules
        if name == "tools" or name.startswith("tools.") or name == "support_tools"
    ]
    # Reload dependency providers first, package/shim last so re-exported function refs update.
    priority = {
        "tools.core": 0,
        "tools.codebase_index": 1,
        "tools.goal": 2,
        "tools.ops": 3,
        "tools.swarm": 4,
        "tools": 98,
        "support_tools": 99,
    }
    return sorted(names, key=lambda item: (priority.get(item, 50), item))


async def _ensure_fresh_tool_modules() -> list[str]:
    async with _HOT_RELOAD_LOCK:
        return await _ensure_fresh_tool_modules_locked()


async def _ensure_fresh_tool_modules_locked() -> list[str]:
    changed = False
    for name in _reloadable_tool_modules():
        module = sys.modules.get(name)
        path = getattr(module, "__file__", None) if module else None
        if not path:
            continue
        try:
            signature = _module_signature(path)
        except OSError:
            continue
        old = _HOT_RELOAD_SIGNATURES.setdefault(name, signature)
        if signature != old:
            changed = True

    if not changed:
        return []

    # Caller holds _HOT_RELOAD_LOCK so reload and new tool entry are serialized.
    async with _TOOL_INFLIGHT_COND:
        while _TOOL_INFLIGHT:
            await _TOOL_INFLIGHT_COND.wait()

    # Re-check under lock; another concurrent call may have already refreshed.
    dirty: list[str] = []
    for name in _reloadable_tool_modules():
        module = sys.modules.get(name)
        path = getattr(module, "__file__", None) if module else None
        if not path:
            continue
        try:
            signature = _module_signature(path)
        except OSError:
            continue
        if signature != _HOT_RELOAD_SIGNATURES.get(name):
            dirty.append(name)
    if not dirty:
        return []

    reloaded: list[str] = []
    for name in _reloadable_tool_modules():
        module = sys.modules.get(name)
        path = getattr(module, "__file__", None) if module else None
        if not path:
            continue
        try:
            cached = getattr(module, "__cached__", None)
            if cached and os.path.exists(cached):
                with contextlib.suppress(OSError):
                    os.remove(cached)
            importlib.reload(module)
            _HOT_RELOAD_SIGNATURES[name] = _module_signature(path)
            reloaded.append(name)
        except Exception as exc:
            _log.warning("Hot-reload skipped for %s: %s", name, exc)
    if reloaded:
        _log.info("Hot-reloaded harness tool modules: %s", ", ".join(reloaded))
    return reloaded


def _active_workspace() -> str:
    override = get_active_workspace_override()
    if override:
        return os.path.abspath(str(override))
    workspace = (os.getenv("CLAUDE_PROJECT_DIR") or "").strip()
    if not workspace:
        meta = os.getenv("ANTIGRAVITY_SOURCE_METADATA")
        if meta:
            try:
                workspace = str(json.loads(meta).get("tool", {}).get("workspacePath") or "").strip()
            except Exception:
                workspace = ""
    workspace = workspace or (os.getenv("WORKSPACE_ROOT") or "").strip()
    return os.path.abspath(workspace or os.getcwd() or WORKSPACE_ROOT)


def _auto_watch_enabled() -> bool:
    return bool_flag("HARNESS_AUTO_WATCH", False, root=_active_workspace())


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _project_watcher_alive(root: str) -> bool:
    pid_file = os.path.join(root, ".harness_auto_watch.pid")
    try:
        with open(pid_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        pid = int(data.get("pid", 0))
        script = str(data.get("script", ""))
        if script and Path(script).name != "auto_watch.py":
            return False
        if pid <= 0:
            return False
        if os.name == "nt":
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return False
                return code.value == 259
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
    except Exception:
        return False


def _global_watcher_alive() -> bool:
    try:
        from tools.watch_registry import global_pid_active
        return global_pid_active()
    except Exception:
        return False


def _watcher_python() -> str:
    exe = Path(sys.executable)
    if os.name == "nt":
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            return str(pythonw)
    return str(exe)


def _claim_startup_lock(root: str) -> int | None:
    lock_path = os.path.join(root, ".harness_auto_watch.start.lock")
    try:
        if os.path.exists(lock_path) and time.time() - os.path.getmtime(lock_path) > 15:
            os.unlink(lock_path)
    except OSError:
        pass
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(lock_path, flags)
    except OSError:
        return None
    os.write(fd, json.dumps({"pid": os.getpid(), "ts": time.time()}).encode("utf-8"))
    return fd


def _release_startup_lock(root: str, fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(os.path.join(root, ".harness_auto_watch.start.lock"))
    except OSError:
        pass


def _close_startup_lock(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _rotate_bootstrap_log(log_path: Path) -> None:
    try:
        if log_path.exists() and log_path.stat().st_size > 1_000_000:
            rotated = log_path.with_suffix(log_path.suffix + ".1")
            try:
                rotated.unlink()
            except OSError:
                pass
            log_path.replace(rotated)
    except OSError:
        pass


def _kick_project_auto_watch() -> None:
    if not _auto_watch_enabled():
        return
    root = _active_workspace()
    if not os.path.isdir(root):
        return
    try:
        from tools.watch_registry import register_repo
        register_repo(root)
    except Exception:
        pass
    with _auto_watch_lock:
        if _global_watcher_alive():
            _auto_watch_roots.add(root)
            return
        if root in _auto_watch_roots and _project_watcher_alive(root):
            return
        _auto_watch_roots.discard(root)
        startup_fd = _claim_startup_lock(root)
        if startup_fd is None:
            return

        env = os.environ.copy()
        env["HARNESS_AUTO_WATCH_GLOBAL"] = "1"
        env.pop("HARNESS_WATCH_ROOT", None)
        script = Path(__file__).with_name("auto_watch.py")
        log_path = Path(root) / ".harness_auto_watch.bootstrap.log"
        try:
            _rotate_bootstrap_log(log_path)
            with open(log_path, "ab") as log:
                popen_kwargs = {
                    "cwd": str(Path(__file__).resolve().parent),
                    "env": env,
                    "stdout": log,
                    "stderr": log,
                    "stdin": subprocess.DEVNULL,
                    "close_fds": True,
                }
                if os.name == "nt":
                    popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                subprocess.Popen([_watcher_python(), str(script)], **popen_kwargs)
            deadline = time.time() + 10.0
            while time.time() < deadline:
                if _global_watcher_alive() or _project_watcher_alive(root):
                    break
                time.sleep(0.1)
            if _global_watcher_alive() or _project_watcher_alive(root):
                _auto_watch_roots.add(root)
                _log.info("Started Auto-Watch for %s", root)
            else:
                _auto_watch_roots.discard(root)
                _log.warning("Auto-Watch start attempted but no heartbeat appeared for %s", root)
        except Exception as e:
            _log.debug("Auto-Watch start skipped for %s: %s", root, e)
        finally:
            if _global_watcher_alive() or _project_watcher_alive(root):
                _release_startup_lock(root, startup_fd)
            else:
                # Keep the startup lock file briefly as an in-flight marker. Slow
                # Windows machines can take more than the heartbeat window to
                # launch pythonw; the stale-lock cleanup above allows retry later.
                _close_startup_lock(startup_fd)


def _kick_auto_wiki_ingest() -> None:
    try:
        import llmwiki_tool
        targets = llmwiki_tool.wiki_pending_targets()
    except Exception as e:
        _log.debug("wiki pending check failed: %s", e)
        return

    workspace = _active_workspace()
    for target in targets:
        target_key = f"{target}:{workspace if target == 'local' else 'global'}"
        with _wiki_ingest_lock:
            if target_key in _wiki_ingest_targets:
                continue
            _wiki_ingest_targets.add(target_key)

        async def _run(target_name: str = target, key: str = target_key) -> None:
            try:
                await llmwiki_tool.wiki_ingest(target=target_name)
                _log.info("Auto-ingested %s llmwiki raw docs", target_name)
            except Exception as e:
                _log.warning("Auto wiki ingest failed for %s: %s", target_name, e)
            finally:
                with _wiki_ingest_lock:
                    _wiki_ingest_targets.discard(key)

        task = asyncio.create_task(_run(), name=f"wiki-ingest-{target}")
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    import uuid
    import time
    from agents import current_run_id, log_run_to_db

    tool_name = _normalize_tool_name(name)
    args_for_guard = arguments if isinstance(arguments, dict) else {}
    resolved_workspace = _workspace_for_tool_call(args_for_guard)
    run_id = f"mcp-{uuid.uuid4().hex[:8]}"
    run_token = current_run_id.set(run_id)
    start_time = time.perf_counter()
    task: asyncio.Task | None = None
    with workspace_scope(resolved_workspace):
        _ensure_lazy_settings_merge()
        _kick_project_auto_watch()
        _kick_auto_wiki_ingest()
        tool_context = contextvars.copy_context()
        try:
            st.session_heartbeat(task=f"mcp:{tool_name}")
        except Exception as exc:
            _log.debug("coordination heartbeat skipped for %s: %s", tool_name, exc)
        allow_background_after_cancel = _allow_background_after_cancel(tool_name, args_for_guard)
        single_flight_key = None if allow_background_after_cancel else _single_flight_key(tool_name, args_for_guard)
    duplicate_inflight_res: list[types.TextContent] | None = None

    async def _run():
        global _TOOL_INFLIGHT
        depth = _TOOL_CALL_DEPTH.get()
        depth_token = _TOOL_CALL_DEPTH.set(depth + 1)
        top_level = depth == 0
        try:
            with workspace_scope(resolved_workspace):
                async with _TOOL_SEM:
                    if top_level:
                        async with _HOT_RELOAD_LOCK:
                            await _ensure_fresh_tool_modules_locked()
                            async with _TOOL_INFLIGHT_COND:
                                _TOOL_INFLIGHT += 1
                    try:
                        return await _execute_tool(tool_name, arguments)
                    finally:
                        if top_level:
                            async with _TOOL_INFLIGHT_COND:
                                _TOOL_INFLIGHT -= 1
                                _TOOL_INFLIGHT_COND.notify_all()
        finally:
            _TOOL_CALL_DEPTH.reset(depth_token)

    if single_flight_key:
        async with _TOOL_SINGLE_FLIGHT_LOCK:
            now = time.monotonic()
            _prune_single_flight_results(now)
            cached = _TOOL_SINGLE_FLIGHT_RESULTS.get(single_flight_key)
            if cached and cached[0] > now:
                task = None
                duplicate_inflight_res = cached[1]
                _log.info("replaying recent completed mutating tool %s", tool_name)
            else:
                task = _TOOL_SINGLE_FLIGHTS.get(single_flight_key)
            if duplicate_inflight_res is None:
                if task is None or task.done():
                    task = asyncio.create_task(_run(), name=f"tool-{run_id}", context=tool_context)
                    _TOOL_SINGLE_FLIGHTS[single_flight_key] = task
                    _background_tasks.add(task)
                    task.add_done_callback(_background_tasks.discard, context=tool_context)
                    task.add_done_callback(
                        lambda done_task, key=single_flight_key: asyncio.create_task(_forget_single_flight(key, done_task)),
                        context=tool_context,
                    )
                else:
                    _log.info("rejecting duplicate in-flight mutating tool %s", tool_name)
                    task = None
                    duplicate_inflight_res = _json_response({
                        "error": "in_flight_duplicate",
                        "detail": "An identical mutating tool call is already running; retry after it finishes.",
                        "tool": tool_name,
                    })
    else:
        task = asyncio.create_task(_run(), name=f"tool-{run_id}", context=tool_context)
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard, context=tool_context)

    try:
        if duplicate_inflight_res is not None:
            return duplicate_inflight_res
        if task is None:
            return _json_response({"error": "internal_error", "detail": f"{tool_name} did not create a task."})
        res = await asyncio.shield(task)
        res = res or _json_response({"error": "empty_tool_result", "detail": f"{tool_name} returned no content."})
        with workspace_scope(resolved_workspace):
            _schedule_mcp_tool_lesson(tool_name, arguments if isinstance(arguments, dict) else {}, res)
            _schedule_mcp_memory_events(tool_name, arguments if isinstance(arguments, dict) else {}, res, start_time)
        return res
    except asyncio.CancelledError:
        if task is None:
            raise
        # Yield once then check — catches tasks that finished microseconds before cancel
        await asyncio.sleep(0)
        if task.done() and not task.cancelled():
            exc = task.exception()
            if exc is None:
                return task.result()
        if allow_background_after_cancel:
            # Try brief harvest window for near-complete tasks
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=0.05)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            _log.info("tool %s cancelled by client, running in background", tool_name)
            res = _json_response({"error": "cancelled", "detail": "Cancelled by client; tool running in background"})
        else:
            task.cancel()
            done, _pending = await asyncio.wait({task}, timeout=0.5)
            stopped = task in done and task.done()
            if stopped:
                _log.info("tool %s cancelled by client; background execution disabled", tool_name)
                res = _json_response({"error": "cancelled", "detail": "Cancelled by client; background execution disabled for mutating tools"})
            else:
                _log.info("tool %s cancellation pending; duplicate retries remain blocked", tool_name)
                if single_flight_key:
                    async with _TOOL_SINGLE_FLIGHT_LOCK:
                        _TOOL_SINGLE_FLIGHT_REPLAY_KEYS.add(single_flight_key)
                res = _json_response({"error": "cancel_pending", "detail": "Cancellation is pending for a mutating tool; duplicate retries are blocked until the original task exits."})
        with workspace_scope(resolved_workspace):
            _schedule_mcp_memory_events(tool_name, arguments if isinstance(arguments, dict) else {}, res, start_time)
        return res
    except Exception as exc:
        _log.exception("tool %s failed before MCP response", tool_name)
        res = _json_response({"error": f"{type(exc).__name__}: {exc}", "tool": tool_name})
        with workspace_scope(resolved_workspace):
            _schedule_mcp_memory_events(tool_name, arguments if isinstance(arguments, dict) else {}, res, start_time)
        return res
    finally:
        current_run_id.reset(run_token)
        if tool_name not in ("list_agents", "finops_stats", "router_quota_status"):
            def _log_task(t: asyncio.Task, _rid=run_id, _n=tool_name, _s=start_time) -> None:
                try:
                    with workspace_scope(resolved_workspace):
                        suffix = "_cancelled" if t.cancelled() else ("_error" if t.exception() else "")
                        log_run_to_db(_rid, f"mcp_{_n}{suffix}", int((time.perf_counter() - _s) * 1000))
                except Exception as exc:
                    _log.debug("run ledger logging failed for %s: %s", _n, exc)

            if task is not None:
                if task.done():
                    _log_task(task)
                else:
                    task.add_done_callback(_log_task, context=tool_context)


async def _execute_tool(name: str, arguments: dict) -> list[types.TextContent]:
    # Gemini IDE gửi "agent-harness/panel_review", Claude Code gửi "panel_review"
    if "/" in name:
        name = name.split("/", 1)[-1]

    if arguments is None:
        args = {}
    elif not isinstance(arguments, dict):
        return _json_response({"error": "invalid_arguments_type", "detail": f"arguments must be object, got {type(arguments).__name__}"})
    else:
        args = arguments

    try:
        if name == "auto_trigger":
            stage = str(args.get("stage", "post_edit")).strip().lower()
            if stage not in {"post_edit", "final", "pre_complete"}:
                return _json_response({"error": "invalid_argument", "detail": "stage must be one of: post_edit, final, pre_complete"})
            mode = args.get("mode")
            mode = str(mode).strip().lower() if mode is not None else None
            if mode is not None and mode not in {"max", "safe"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: max, safe"})
            return _json_response(await st.auto_trigger(
                changed_files=args.get("changed_files"),
                diff=args.get("diff"),
                task=args.get("task"),
                stage=stage,
                mode=mode,
                exclude_tools=args.get("exclude_tools"),
            ))

        if name == "preflight_trigger":
            mode = args.get("mode")
            mode = str(mode).strip().lower() if mode is not None else None
            if mode is not None and mode not in {"max", "safe"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: max, safe"})
            return _json_response(st.preflight_trigger(
                task=args.get("task"),
                changed_files=args.get("changed_files"),
                diff=args.get("diff"),
                mode=mode,
            ))

        if name == "tool_lifecycle":
            return _json_response(st.tool_lifecycle())

        if name == "session_heartbeat":
            return _json_response(st.session_heartbeat(
                session_id=args.get("session_id"),
                agent_kind=args.get("agent_kind"),
                task=args.get("task"),
                status=args.get("status", "active"),
            ))

        if name == "coordination_status":
            try:
                limit = int(args.get("limit", 50) or 50)
            except (TypeError, ValueError):
                return _json_response({"error": "invalid_argument", "detail": "limit must be an integer"})
            return _json_response(st.coordination_status(limit=limit))

        if name == "active_sessions":
            return _json_response(st.active_sessions())

        if name == "claim_files":
            allow_shared, shared_error = _parse_bool_arg(args, "allow_shared")
            if shared_error:
                return _json_response({"error": "invalid_argument", "detail": shared_error})
            try:
                ttl_seconds = float(args.get("ttl_seconds", 900) or 900)
            except (TypeError, ValueError):
                return _json_response({"error": "invalid_argument", "detail": "ttl_seconds must be a number"})
            return _json_response(st.claim_files(
                files=args.get("files"),
                session_id=args.get("session_id"),
                agent_kind=args.get("agent_kind"),
                task=args.get("task"),
                symbols=args.get("symbols"),
                lease_mode=args.get("lease_mode", "auto"),
                ttl_seconds=ttl_seconds,
                allow_shared=allow_shared,
            ))

        if name == "release_files":
            return _json_response(st.release_files(
                files=args.get("files"),
                session_id=args.get("session_id"),
            ))

        if name == "conflict_check":
            require_lease, lease_error = _parse_optional_bool_arg(args, "require_lease")
            if lease_error:
                return _json_response({"error": "invalid_argument", "detail": lease_error})
            return _json_response(st.conflict_check(
                files=args.get("files"),
                session_id=args.get("session_id"),
                task=args.get("task"),
                stage=args.get("stage", "manual"),
                require_lease=require_lease,
            ))

        if name == "takeover_stale_claim":
            return _json_response(st.takeover_stale_claim(
                files=args.get("files"),
                session_id=args.get("session_id"),
            ))

        if name == "coordination_policy":
            return _json_response(st.coordination_policy(profile=args.get("profile")))

        if name == "coordination_events":
            try:
                limit = int(args.get("limit", 100) or 100)
            except (TypeError, ValueError):
                return _json_response({"error": "invalid_argument", "detail": "limit must be an integer"})
            return _json_response(st.coordination_events(limit=limit))

        if name == "coordination_advisor":
            return _json_response(st.coordination_advisor(
                files=args.get("files"),
                session_id=args.get("session_id"),
                task=args.get("task"),
            ))

        if name == "integration_router":
            return _json_response(st.integration_router(
                task=args.get("task"),
                changed_files=args.get("changed_files"),
                diff=args.get("diff"),
            ))

        if name == "workflow_router":
            return _json_response(st.workflow_router(
                task=args.get("task"),
                changed_files=args.get("changed_files"),
                diff=args.get("diff"),
            ))

        if name == "bug_repro_guard":
            return _json_response(st.bug_repro_guard(
                task=args.get("task"),
                error_log=args.get("error_log"),
                changed_files=args.get("changed_files"),
                commands=args.get("commands"),
                test_output=args.get("test_output"),
                diff=args.get("diff"),
            ))

        if name == "ui_skill_router":
            return _json_response(st.ui_skill_router(
                task=args.get("task"),
                changed_files=args.get("changed_files"),
            ))

        if name == "hallmark_bridge":
            allow_mutation, mutation_error = _parse_bool_arg(args, "allow_mutation")
            if mutation_error:
                return _json_response({"error": "invalid_argument", "detail": mutation_error})
            return _json_response(st.hallmark_bridge(
                action=args.get("action", "status"),
                task=args.get("task"),
                files=args.get("files"),
                allow_mutation=allow_mutation,
            ))

        if name == "speckit_bridge":
            allow_mutation, mutation_error = _parse_bool_arg(args, "allow_mutation")
            if mutation_error:
                return _json_response({"error": "invalid_argument", "detail": mutation_error})
            return _json_response(st.speckit_bridge(
                action=args.get("action", "status"),
                task=args.get("task"),
                feature=args.get("feature"),
                integration=args.get("integration", "codex"),
                allow_mutation=allow_mutation,
            ))

        if name == "scope_creep_detector":
            staged, staged_error = _parse_bool_arg(args, "staged")
            if staged_error:
                return _json_response({"error": "invalid_argument", "detail": staged_error})
            try:
                hunk_threshold = int(args.get("hunk_threshold", 80) or 80)
            except (TypeError, ValueError):
                return _json_response({"error": "invalid_argument", "detail": "hunk_threshold must be an integer"})
            return _json_response(st.scope_creep_detector(
                changed_files=args.get("changed_files"),
                diff=args.get("diff"),
                task=args.get("task"),
                staged=staged,
                base=args.get("base"),
                hunk_threshold=hunk_threshold,
            ))

        if name == "office_bridge":
            allow_mutation, mutation_error = _parse_bool_arg(args, "allow_mutation")
            if mutation_error:
                return _json_response({"error": "invalid_argument", "detail": mutation_error})
            try:
                timeout = int(args.get("timeout", 120) or 120)
            except (TypeError, ValueError):
                return _json_response({"error": "invalid_argument", "detail": "timeout must be an integer"})
            return _json_response(st.office_bridge(
                action=args.get("action", "status"),
                file=args.get("file"),
                mode=args.get("mode"),
                path=args.get("path"),
                selector=args.get("selector"),
                command=args.get("command"),
                output=args.get("output"),
                allow_mutation=allow_mutation,
                timeout=timeout,
            ))

        if name == "prod_readiness_gate":
            staged, staged_error = _parse_bool_arg(args, "staged")
            if staged_error:
                return _json_response({"error": "invalid_argument", "detail": staged_error})
            mode = str(args.get("mode", "safe")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            since_commit = args.get("since_commit", "")
            since_commit = "" if since_commit is None else str(since_commit).strip()
            return _json_response(await st.prod_readiness_gate(
                changed_files=args.get("changed_files"),
                diff=args.get("diff"),
                task=args.get("task"),
                context=args.get("context"),
                staged=staged,
                since_commit=since_commit,
                mode=mode,
            ))

        if name == "goal_autopilot":
            mode = str(args.get("mode", "")).strip().lower()
            if mode not in {"init", "check", "complete", "block", "status"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: init, check, complete, block, status"})
            return _json_response(await st.goal_autopilot(
                mode=mode,
                goal=args.get("goal"),
                context=args.get("context"),
                changed_files=args.get("changed_files"),
                diff=args.get("diff"),
                task=args.get("task"),
            ))

        if name == "release_orchestrator":
            mode = str(args.get("mode", "safe")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            return _json_response(await st.release_orchestrator(
                changed_files=args.get("changed_files"),
                diff=args.get("diff"),
                context=args.get("context"),
                mode=mode,
            ))

        if name == "provenance_checker":
            mode = str(args.get("mode", "safe")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            return _json_response(await st.provenance_checker(
                files=args.get("files"),
                context=args.get("context"),
                mode=mode,
            ))

        if name == "auth_matrix_auditor":
            mode = str(args.get("mode", "safe")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            return _json_response(await st.auth_matrix_auditor(
                files=args.get("files"),
                diff=args.get("diff"),
                context=args.get("context"),
                mode=mode,
            ))

        if name == "harness_trace_viewer":
            mode = str(args.get("mode", "safe")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            limit = args.get("limit", 20)
            try:
                limit = max(1, min(200, int(limit)))
            except (TypeError, ValueError):
                return _json_response({"error": "invalid_argument", "detail": "limit must be an integer"})
            include_logs, include_logs_error = _parse_bool_arg(args, "include_logs")
            if include_logs_error:
                return _json_response({"error": "invalid_argument", "detail": include_logs_error})
            return _json_response(await st.harness_trace_viewer(limit=limit, include_logs=include_logs, mode=mode))

        if name == "incremental_refactor_guard":
            mode = str(args.get("mode", "safe")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            return _json_response(await st.incremental_refactor_guard(
                files=args.get("files"),
                diff=args.get("diff"),
                since_commit=args.get("since_commit", ""),
                mode=mode,
            ))

        if name == "goal_supervisor":
            return _json_response(await st.goal_supervisor(
                changed_files=args.get("changed_files"),
                diff=args.get("diff"),
                context=args.get("context"),
                last_checks=args.get("last_checks"),
            ))

        if name == "goal_runner":
            mode = str(args.get("mode", "max")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            agent_command = args.get("agent_command")
            if agent_command is not None and not (
                isinstance(agent_command, str)
                or (isinstance(agent_command, list) and all(isinstance(item, str) and item.strip() for item in agent_command))
            ):
                return _json_response({"error": "invalid_argument", "detail": "agent_command must be a string or list of strings"})
            dry_run, dry_run_error = _parse_bool_arg(args, "dry_run")
            if dry_run_error:
                return _json_response({"error": "invalid_argument", "detail": dry_run_error})
            final_prod_gate, final_prod_gate_error = _parse_bool_arg(args, "final_prod_gate", True)
            if final_prod_gate_error:
                return _json_response({"error": "invalid_argument", "detail": final_prod_gate_error})
            return _json_response(await st.goal_runner(
                prompt=args.get("prompt", ""),
                max_iterations=args.get("max_iterations", 8),
                mode=mode,
                agent_command=agent_command,
                agent_timeout=args.get("agent_timeout", 900.0),
                dry_run=dry_run,
                final_prod_gate=final_prod_gate,
            ))

        if name == "goal_runner_control":
            mode = str(args.get("mode", "max")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            dry_run, dry_run_error = _parse_bool_arg(args, "dry_run")
            if dry_run_error:
                return _json_response({"error": "invalid_argument", "detail": dry_run_error})
            return _json_response(await st.goal_runner_control(
                action=args.get("action", "status"),
                prompt=args.get("prompt"),
                mode=mode,
                dry_run=dry_run,
            ))

        if name == "run_ledger":
            return _json_response(await st.run_ledger(limit=args.get("limit", 20)))

        if name == "policy_profile":
            return _json_response(await st.policy_profile(profile=args.get("profile", "balanced")))

        if name == "agent_adapters":
            return _json_response(await st.agent_adapters())

        if name == "context_auditor":
            return _json_response(await st.context_auditor(
                question=args.get("question", ""),
                files=args.get("files"),
                context=args.get("context"),
            ))

        if name == "install_manifest":
            return _json_response(await st.install_manifest(
                action=args.get("action", "summary"),
                profile=args.get("profile", "standard"),
                target=args.get("target"),
            ))

        if name == "adapter_parity_doctor":
            return _json_response(await st.adapter_parity_doctor())

        if name == "mcp_inventory":
            fragmented_only, fragmented_error = _parse_bool_arg(args, "fragmented_only", False)
            if fragmented_error:
                return _json_response({"error": "invalid_argument", "detail": fragmented_error})
            return _json_response(await st.mcp_inventory(fragmented_only=fragmented_only))

        if name == "context_budget":
            include_home, include_home_error = _parse_bool_arg(args, "include_home", True)
            if include_home_error:
                return _json_response({"error": "invalid_argument", "detail": include_home_error})
            verbose, verbose_error = _parse_bool_arg(args, "verbose", False)
            if verbose_error:
                return _json_response({"error": "invalid_argument", "detail": verbose_error})
            return _json_response(await st.context_budget(include_home=include_home, verbose=verbose))

        if name == "router_quota_status":
            return _json_response(await st.router_quota_status())

        if name == "ask_codebase_health":
            return _json_response(await st.ask_codebase_health(
                question=args.get("question", "harness codebase health"),
                files=args.get("files"),
                context=args.get("context"),
            ))

        if name == "patch_safety_check":
            return _json_response(await st.patch_safety_check(
                patch=args.get("patch", ""),
                files=args.get("files"),
            ))

        if name == "benchmark_runner":
            mode = str(args.get("mode", "safe")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            dry_run, dry_run_error = _parse_bool_arg(args, "dry_run", True)
            if dry_run_error:
                return _json_response({"error": "invalid_argument", "detail": dry_run_error})
            return _json_response(await st.benchmark_runner(
                tasks=args.get("tasks"),
                mode=mode,
                dry_run=dry_run,
            ))

        if name == "harness_doctor":
            return _json_response(await st.harness_doctor())

        if name == "lesson_curator":
            promote, promote_error = _parse_bool_arg(args, "promote", True)
            if promote_error:
                return _json_response({"error": "invalid_argument", "detail": promote_error})
            dry_run, dry_run_error = _parse_bool_arg(args, "dry_run", False)
            if dry_run_error:
                return _json_response({"error": "invalid_argument", "detail": dry_run_error})
            allow_untrusted, allow_untrusted_error = _parse_bool_arg(args, "allow_untrusted_promote", False)
            if allow_untrusted_error:
                return _json_response({"error": "invalid_argument", "detail": allow_untrusted_error})
            mode = str(args.get("mode", "max")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            try:
                raw_limit = args.get("limit", 100)
                raw_llm_limit = args.get("llm_limit", 20)
                raw_timeout = args.get("timeout", 15.0)
                if any(isinstance(v, str) and len(v) > 20 for v in (raw_limit, raw_llm_limit, raw_timeout)):
                    raise ValueError("numeric argument too long")
                limit = int(raw_limit)
                llm_limit = int(raw_llm_limit)
                timeout = float(raw_timeout)
            except (TypeError, ValueError):
                return _json_response({"error": "invalid_argument", "detail": "limit/llm_limit must be integers and timeout must be numeric"})
            if limit <= 0 or llm_limit < 0 or timeout < 5.0 or not math.isfinite(timeout):
                return _json_response({"error": "invalid_argument", "detail": "limit must be > 0, llm_limit >= 0, timeout >= 5"})
            return _json_response(await st.lesson_curator(
                limit=limit,
                promote=promote,
                dry_run=dry_run,
                mode=mode,
                llm_limit=llm_limit,
                timeout=timeout,
                allow_untrusted_promote=allow_untrusted,
            ))

        if name == "panel_review":
            staged, staged_error = _parse_bool_arg(args, "staged")
            if staged_error:
                return _json_response({"error": "invalid_argument", "detail": staged_error})
            fast, fast_error = _parse_bool_arg(args, "fast", True)
            if fast_error:
                return _json_response({"error": "invalid_argument", "detail": fast_error})
            try:
                agent_timeout = float(args.get("agent_timeout", 45.0) or 45.0)
            except (TypeError, ValueError):
                return _json_response({"error": "invalid_argument", "detail": "agent_timeout must be numeric"})
            if not math.isfinite(agent_timeout) or agent_timeout <= 0:
                return _json_response({"error": "invalid_argument", "detail": "agent_timeout must be a positive finite number"})
            agent_timeout = min(agent_timeout, 45.0)
            if args.get("files"):
                coordination_gate = st.conflict_check(files=args.get("files"), task=args.get("focus"), stage="panel_review")
                if coordination_gate.get("status") == "blocked_conflict":
                    return _json_response({
                        "status": "blocked_conflict",
                        "verdict": "blocked_conflict",
                        "summary": "panel_review blocked by unresolved cross-session conflict",
                        "findings": [],
                        "coordination": coordination_gate,
                    })
            panel_timeout = _mcp_panel_timeout()
            try:
                result = await asyncio.wait_for(
                    st.panel_review(
                        files=args.get("files"), diff=args.get("diff"),
                        code=args.get("code"), focus=args.get("focus"),
                        staged=staged,
                        since_commit=args.get("since_commit", ""),
                        fast=fast,
                        agent_timeout=agent_timeout,
                    ),
                    timeout=panel_timeout,
                )
            except asyncio.TimeoutError:
                result = {
                    "verdict": "degraded",
                    "summary": f"panel_review exceeded MCP deadline ({panel_timeout:.0f}s); returning controlled timeout instead of letting the MCP client hang.",
                    "findings": [],
                    "panel": [],
                    "warnings": [
                        f"panel_review exceeded HARNESS_MCP_PANEL_TIMEOUT={panel_timeout:.0f}s",
                        "Default MCP panel uses fast=True and agent_timeout<=45s; restart the MCP client if its tool schema does not expose fast/agent_timeout.",
                    ],
                    "degraded": True,
                    "timeout": True,
                }
            return _json_response(result)

        if name == "consult":
            return _json_response(await st.consult(
                question=args["question"],
                files=args.get("files"), context=args.get("context"),
            ))

        if name == "alt_implementation":
            return _json_response(await st.alt_implementation(
                spec=args["spec"],
                files=args.get("files"), context=args.get("context"),
            ))

        if name == "suggest_fix":
            return _json_response(await st.suggest_fix(
                error=args["error"], files=args.get("files"),
                code=args.get("code"), context=args.get("context"),
            ))

        if name == "ask_codebase":
            return _json_response(await st.ask_codebase(
                question=args["question"], 
                files=args.get("files"),
                index_md=args.get("index_md"),
            ))

        if name == "quick_task":
            instruction = args.get("instruction") or args.get("task")
            if not isinstance(instruction, str) or not instruction.strip():
                return _json_response({"error": "invalid_argument", "detail": "quick_task requires instruction or task"})
            return _json_response(await st.quick_task(
                instruction=instruction, context=args.get("context"),
            ))

        if name == "run_single_agent":
            role_str = args.get("role", "")
            if role_str not in STR_TO_ROLE:
                return _json_response({"error": f"Invalid role: {role_str}. Lựa chọn hợp lệ: {list(STR_TO_ROLE.keys())}"})
            role = STR_TO_ROLE[role_str]
            client = get_llm_client()
            result = await Agent(role, client).run_async(
                args.get("task", ""), args.get("context", ""),
            )
            return _json_response({
                "agent_id": result.agent_id, "role": result.agent_role.value,
                "model": result.model_used, "status": result.status,
                "duration_ms": result.duration_ms,
                "result": result.result, "error": result.error,
            })

        if name == "list_agents":
            model_by_role = _model_by_role()
            return _json_response({
                "toolbox": "12-Agent Support Team cho Claude Code",
                "workspace_root": _active_workspace(),
                "agents": [
                    {**a, "model": model_by_role[a["role"]]} for a in AGENT_INFO
                ],
            })

        if name == "wiki_ingest":
            import llmwiki_tool
            return _json_response(await llmwiki_tool.wiki_ingest(target=args.get("target", "local")))

        if name == "wiki_query":
            import llmwiki_tool
            return _json_response(llmwiki_tool.wiki_query(args["query"]))

        if name == "wiki_lint":
            import llmwiki_tool
            return _json_response(llmwiki_tool.wiki_lint())

        if name == "security_autofix":
            files = args.get("files")
            if not files:
                return _json_response({"error": "Thiếu argument bắt buộc: files"})
            return _json_response(await st.security_autofix(files=files))

        if name == "auto_tester":
            files = args.get("files")
            findings = args.get("findings")
            if not files or not isinstance(findings, list) or not findings or not all(isinstance(f, dict) for f in findings):
                return _json_response({"error": "Thiếu argument bắt buộc: files và findings"})
            return _json_response(await st.auto_tester(files=files, findings=findings))

        if name == "visual_reviewer":
            url = args.get("url")
            if not url:
                return _json_response({"error": "Thiếu argument bắt buộc: url"})
            return _json_response(await st.visual_reviewer(url=url, baseline_url=args.get("baseline_url")))

        if name == "benchmarker":
            code_a = args.get("code_a")
            code_b = args.get("code_b")
            if not code_a or not code_b:
                return _json_response({"error": "Thiếu argument bắt buộc: code_a và code_b"})
            return _json_response(await st.benchmarker(code_a=code_a, code_b=code_b, iterations=args.get("iterations", 5)))

        if name == "dependency_upgrader":
            return _json_response(await st.dependency_upgrader(dry_run=args.get("dry_run", True)))

        if name == "schema_drift":
            return _json_response(await st.schema_drift(baseline_schema=args.get("baseline_schema")))

        if name == "doc_sync":
            return _json_response(await st.doc_sync())

        if name == "telemetry_debugger":
            log_content = args.get("log_content")
            if not log_content:
                return _json_response({"error": "Thiếu argument bắt buộc: log_content"})
            return _json_response(await st.telemetry_debugger(log_content=log_content))

        if name == "run_in_sandbox":
            code = args.get("code")
            if not code:
                return _json_response({"error": "Thiếu argument bắt buộc: code"})
            return _json_response(st.run_in_sandbox(code=code, timeout=args.get("timeout", 5.0)))

        if name == "semantic_search":
            query = args.get("query")
            if not query:
                return _json_response({"error": "Thiếu argument bắt buộc: query"})
            return _json_response(await st.semantic_search(query=query, top_k=args.get("top_k", 5)))

        if name == "swarm_debug":
            error_log = args.get("error_log")
            if not error_log:
                return _json_response({"error": "Thiếu argument bắt buộc: error_log"})
            return _json_response(await st.swarm_debug(error_log=error_log, files=args.get("files")))

        if name == "finops_stats":
            return _json_response(get_finops_stats())

        if name == "devops_pipeline":
            return _json_response(await st.devops_pipeline())

        if name == "config_security_audit":
            return _json_response(await st.config_security_audit())

        if name == "pr_generator":
            return _json_response(await st.pr_generator(diff=args.get("diff"), branch=args.get("branch")))

        if name == "license_scanner":
            return _json_response(await st.license_scanner())

        if name == "sbom_generator":
            return _json_response(await st.sbom_generator())

        if name == "a11y_auditor":
            return _json_response(await st.a11y_auditor(files=args.get("files")))

        if name == "i18n_auditor":
            return _json_response(await st.i18n_auditor(files=args.get("files")))

        if name == "polyglot_reviewer":
            files = args.get("files")
            if not _nonempty_str_list(files):
                return _json_response({"error": "Thiếu hoặc sai kiểu argument: files phải là mảng string không rỗng"})
            return _json_response(await st.polyglot_reviewer(files=files))

        if name == "git_archaeologist":
            file_path = args.get("file_path")
            if not file_path:
                return _json_response({"error": "Thiếu argument bắt buộc: file_path"})
            return _json_response(await st.git_archaeologist(file_path=file_path, line_no=args.get("line_no")))

        if name == "feature_flag_auditor":
            return _json_response(await st.feature_flag_auditor())

        if name == "dead_code_scanner":
            return _json_response(await st.dead_code_scanner())

        if name == "index_codebase":
            return _json_response(await st.index_codebase(force=args.get("force", False)))

        if name == "review_context_graph":
            return _json_response(await st.review_context_graph(
                changed_files=args.get("changed_files"),
                base=args.get("base", "HEAD~1"),
                detail_level=args.get("detail_level", "standard"),
                max_callers_per_symbol=args.get("max_callers_per_symbol", 25),
            ))

        if name == "graph_health":
            return _json_response(await st.graph_health(limit=args.get("limit", 10)))

        if name == "graph_minimal_context":
            return _json_response(await st.graph_minimal_context(
                task=args.get("task", ""),
                changed_files=args.get("changed_files"),
                base=args.get("base", "HEAD~1"),
            ))

        if name == "profiler":
            code = args.get("code")
            if not code:
                return _json_response({"error": "Thiếu argument bắt buộc: code"})
            return _json_response(st.profiler(code=code, iterations=args.get("iterations", 1)))

        if name == "coverage_analyzer":
            return _json_response(await st.coverage_analyzer())

        if name == "incident_responder":
            log_content = args.get("log_content")
            if not log_content:
                return _json_response({"error": "Thiếu argument bắt buộc: log_content"})
            return _json_response(await st.incident_responder(log_content=log_content))

        if name == "api_contract_tester":
            endpoints = args.get("endpoints")
            if not isinstance(endpoints, list) or not endpoints or not all(isinstance(e, dict) for e in endpoints):
                return _json_response({"error": "Thiếu hoặc sai kiểu argument: endpoints phải là mảng object không rỗng"})
            return _json_response(await st.api_contract_tester(endpoints=endpoints))

        if name == "chaos_tester":
            app_run_command = args.get("app_run_command")
            if not app_run_command:
                return _json_response({"error": "Thiếu argument bắt buộc: app_run_command"})
            return _json_response(st.chaos_tester(app_run_command=app_run_command, duration=args.get("duration", 5)))

        if name == "secret_scanner":
            return _json_response(await st.secret_scanner(paths=args.get("paths")))

        if name == "changelog_generator":
            return _json_response(await st.changelog_generator(
                since=args.get("since", "HEAD~10"),
                until=args.get("until", "HEAD"),
                format=args.get("format", "markdown"),
            ))

        if name == "env_parity_checker":
            return _json_response(await st.env_parity_checker(
                example_file=args.get("example_file", ".env.example"),
                env_file=args.get("env_file", ".env"),
            ))

        if name == "load_tester":
            url = args.get("url")
            if not url:
                return _json_response({"error": "Thiếu argument bắt buộc: url"})
            return _json_response(await st.load_tester(
                url=url,
                requests_count=args.get("requests_count", 100),
                concurrency=args.get("concurrency", 10),
                method=args.get("method", "GET"),
            ))

        if name == "complexity_analyzer":
            return _json_response(await st.complexity_analyzer(
                paths=args.get("paths"),
                threshold=args.get("threshold", 10),
            ))

        if name == "migration_validator":
            return _json_response(await st.migration_validator(paths=args.get("paths")))

        if name == "sql_query_analyzer":
            return _json_response(await st.sql_query_analyzer(files=args.get("files")))

        if name == "openapi_spec_sync":
            return _json_response(await st.openapi_spec_sync(spec_path=args.get("spec_path")))

        if name == "breaking_change_detector":
            return _json_response(await st.breaking_change_detector(base_ref=args.get("base_ref", "")))

        if name == "flaky_test_detector":
            return _json_response(await st.flaky_test_detector(
                runs=args.get("runs", 3),
                test_path=args.get("test_path", ""),
            ))

        if name == "duplicate_code_scanner":
            return _json_response(await st.duplicate_code_scanner(
                min_lines=args.get("min_lines", 6),
                threshold=args.get("threshold", 0.8),
            ))

        if name == "container_linter":
            return _json_response(await st.container_linter(paths=args.get("paths")))

        if name == "dependency_graph_visualizer":
            return _json_response(await st.dependency_graph_visualizer(paths=args.get("paths")))

        if name == "ci_pipeline_validator":
            return _json_response(await st.ci_pipeline_validator(paths=args.get("paths")))

        if name == "mutation_tester":
            return _json_response(await st.mutation_tester(
                files=args.get("files"),
                max_mutations=args.get("max_mutations", 20),
            ))

        if name == "data_flow_taint_analyzer":
            return _json_response(await st.data_flow_taint_analyzer(files=args.get("files")))

        if name == "performance_regression_detector":
            return _json_response(await st.performance_regression_detector(
                functions=args.get("functions"),
                threshold_pct=args.get("threshold_pct", 20.0),
            ))

        return _json_response({"error": f"Unknown tool: {name}"})

    except KeyError as e:
        return _json_response({"error": f"Thiếu argument bắt buộc: {e}"})
    except Exception as e:
        return _json_response({"error": f"{type(e).__name__}: {e}"})


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
