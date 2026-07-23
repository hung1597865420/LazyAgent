"""
Prompt-only goal autopilot for Agent Harness.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from config import WORKSPACE_ROOT
from .workspace_context import get_active_workspace_override

GOAL_STATE_FILE = ".harness_goal_state.json"
MAX_TEXT = 6000
NEXT_ACTIONS = {"continue_part", "run_check", "run_final", "blocked_ask_user", "complete"}


def _clean_text(value: Any) -> str:
    """Return UTF-8-safe text even when clipboard/client input has surrogates."""
    text = str(value or "")
    return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _clean_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, dict):
        return {_clean_text(k): _clean_jsonish(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_jsonish(v) for v in value]
    if isinstance(value, tuple):
        return [_clean_jsonish(v) for v in value]
    return value


def _state_path() -> Path:
    # One active goal per workspace. Prefer explicit active/workspace roots over
    # inherited client vars so a stale Claude env cannot write into another repo.
    use_process_env = _allow_process_env_workspace()
    meta_workspace = ""
    meta = os.getenv("ANTIGRAVITY_SOURCE_METADATA") if use_process_env else ""
    if meta:
        try:
            meta_workspace = str(json.loads(meta).get("tool", {}).get("workspacePath") or "").strip()
        except Exception:
            meta_workspace = ""
    candidates = [
        get_active_workspace_override(),
        os.getenv("HARNESS_ACTIVE_WORKSPACE") if use_process_env else "",
        os.getenv("WORKSPACE_ROOT") if use_process_env else "",
        meta_workspace,
        os.getenv("CLAUDE_PROJECT_DIR") if use_process_env else "",
        WORKSPACE_ROOT,
        os.getcwd(),
        tempfile.gettempdir(),
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if not str(candidate or "").strip():
            continue
        try:
            candidate_path = Path(str(candidate)).expanduser().resolve()
            if not candidate_path.is_dir():
                continue
            canonical = os.path.normcase(str(candidate_path))
            if canonical in seen:
                continue
            seen.add(canonical)
            return Path(canonical) / GOAL_STATE_FILE
        except (OSError, ValueError, RuntimeError):
            continue
    return Path(tempfile.gettempdir()) / GOAL_STATE_FILE


def _allow_process_env_workspace() -> bool:
    if threading.current_thread() is not threading.main_thread():
        return False
    try:
        asyncio.get_running_loop()
        return False
    except RuntimeError:
        return True


@contextmanager
def _state_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as f:
        if os.name == "nt":
            import msvcrt

            f.seek(0)
            if not f.read(1):
                f.seek(0)
                f.write(b"\0")
                f.flush()
                os.fsync(f.fileno())
            f.seek(0)
            deadline = time.monotonic() + 10.0
            while True:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out waiting for goal state lock: {lock_path}")
                    time.sleep(0.05)
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            deadline = time.monotonic() + 10.0
            while True:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out waiting for goal state lock: {lock_path}")
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _now() -> float:
    return time.time()


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            json.dump(_clean_jsonish(data), tmp, ensure_ascii=False, indent=2, sort_keys=True)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _normalize_goal_status(value: Any) -> str:
    status = str(value or "active").strip().lower().replace("-", "_").replace(" ", "_")
    if status in {"budget_limited", "blocked_max_iterations"}:
        return "blocked"
    if status in {"active", "completed", "blocked"}:
        return status
    return "active"


def _goal_fingerprint(goal: str) -> str:
    normalized = " ".join(str(goal or "").strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8", errors="backslashreplace")).hexdigest()[:16]


@dataclass
class GoalState:
    goal: str
    goal_id: str = field(default_factory=lambda: f"goal-{uuid.uuid4().hex[:8]}")
    status: str = "active"
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    revision: int = 0
    checks_run: int = 0
    plan: str = ""
    parts: list[str] = field(default_factory=list)
    current_part_index: int = 0
    last_result: dict[str, Any] | None = None
    completion_note: str = ""
    goal_fingerprint: str = ""
    final_attempt_id: str = ""
    final_started_at: float = 0.0
    final_result: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.goal_fingerprint:
            self.goal_fingerprint = _goal_fingerprint(self.goal)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoalState | None":
        data = _clean_jsonish(data)
        goal = _clean_text(data.get("goal", "")).strip()
        if not goal:
            return None
        parts_data = data.get("parts", [])
        parts = [_clean_text(p).strip() for p in parts_data if _clean_text(p).strip()] if isinstance(parts_data, list) else []
        idx = max(0, _safe_int(data.get("current_part_index"), 0))
        if parts:
            idx = min(idx, len(parts) - 1)
        return cls(
            goal=goal,
            goal_id=_clean_text(data.get("goal_id") or f"goal-{uuid.uuid4().hex[:8]}"),
            status=_normalize_goal_status(data.get("status")),
            created_at=_safe_float(data.get("created_at"), _now()),
            updated_at=_safe_float(data.get("updated_at"), _now()),
            revision=max(0, _safe_int(data.get("revision"), 0)),
            checks_run=_safe_int(data.get("checks_run"), 0),
            plan=_clean_text(data.get("plan") or ""),
            parts=parts,
            current_part_index=idx,
            last_result=data.get("last_result") if isinstance(data.get("last_result"), dict) else None,
            completion_note=_clean_text(data.get("completion_note") or ""),
            goal_fingerprint=_clean_text(data.get("goal_fingerprint") or _goal_fingerprint(goal)),
            final_attempt_id=_clean_text(data.get("final_attempt_id") or ""),
            final_started_at=_safe_float(data.get("final_started_at"), 0.0),
            final_result=data.get("final_result") if isinstance(data.get("final_result"), dict) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_int(value: Any, default: int, lo: int | None = None, hi: int | None = None) -> int:
    try:
        if isinstance(value, float) and not math.isfinite(value):
            return default
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if lo is not None:
        parsed = max(lo, parsed)
    if hi is not None:
        parsed = min(hi, parsed)
    return parsed


def _safe_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _safe_blockers_count(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return 0
    return max(0, _safe_int(value, default))


def _clean_file_list(files: Any) -> list[str]:
    if isinstance(files, str):
        items = [files]
    elif isinstance(files, (list, tuple, set)):
        items = list(files)
    else:
        items = []
    return [text for item in items if (text := _clean_text(item).strip())]


def _load_goal_state_from(path: Path) -> GoalState | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return GoalState.from_dict(data)
    except (TypeError, ValueError):
        return None


def load_goal_state() -> GoalState | None:
    return _load_goal_state_from(_state_path())


def get_active_goal() -> GoalState | None:
    state = load_goal_state()
    return state if state and state.status == "active" else None


def save_goal_state(state: GoalState) -> None:
    path = _state_path()
    with _state_lock(path):
        _save_goal_state_unlocked(path, state)


def _save_goal_state_unlocked(path: Path, state: GoalState) -> None:
    state.revision = max(0, int(state.revision or 0)) + 1
    state.updated_at = _now()
    _atomic_write_json(path, state.to_dict())


async def _worker(instruction: str, context: str) -> dict[str, Any]:
    from .swarm import quick_task

    try:
        return await quick_task(instruction=instruction, context=context[:MAX_TEXT])
    except Exception as e:
        return {"output": None, "error": f"{type(e).__name__}: {e}"}


def _short_text(value: Any, limit: int = 1200) -> str:
    clean = _clean_jsonish(value)
    text = clean if isinstance(clean, str) else json.dumps(clean, ensure_ascii=False)
    return text[:limit]


def _one_line(value: Any, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", _clean_text(value)).strip()
    return text[:limit].rstrip()


def _last_verdict(state: GoalState | None) -> str:
    result = state.last_result if state else None
    if not isinstance(result, dict):
        return "none"
    return str(result.get("verdict") or "none")


def _last_part_status(state: GoalState | None) -> str:
    result = state.last_result if state else None
    if not isinstance(result, dict):
        return "none"
    return str(result.get("part_status") or "none")


def _iter_check_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        out = [value]
        for key in ("results", "checks", "last_checks"):
            nested = value.get(key)
            if isinstance(nested, list):
                out.extend(item for item in nested if isinstance(item, dict))
        return out
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return _iter_check_dicts(parsed)
    return []


def _blockers_count(last_checks: Any = None, state: GoalState | None = None) -> int:
    explicit = 0
    for item in _iter_check_dicts(last_checks):
        try:
            explicit += _safe_blockers_count(item.get("blockers_count"), 1)
        except (TypeError, ValueError):
            explicit += 1
        if item.get("ok") is False or str(item.get("verdict", "")).lower() == "fix_first":
            explicit += 1
    if explicit:
        return explicit
    result = state.last_result if state else None
    if isinstance(result, dict):
        verdict = str(result.get("verdict", "")).lower()
        part_status = str(result.get("part_status", "")).lower()
        if verdict == "fix_first" or part_status == "blocked":
            return 1
    return 0


def _final_check_passed(last_checks: Any) -> bool:
    for item in _iter_check_dicts(last_checks):
        status = str(item.get("status", "")).lower()
        stage = str(item.get("stage", "")).lower()
        if stage == "final" and status == "completed" and _blockers_count(item) == 0:
            return True
    return False


def goal_progress_summary(
    state: GoalState | None = None,
    *,
    next_action: str | None = None,
    blockers_count: int | None = None,
) -> str:
    state = state if state is not None else get_active_goal()
    if not state or state.status != "active":
        return ""
    total = max(1, len(state.parts) or 1)
    index = min(max(0, state.current_part_index), total - 1) + 1
    blockers = _blockers_count(state=state) if blockers_count is None else max(0, blockers_count)
    action = next_action or _next_action_for_state(state, blockers_count=blockers)
    return (
        f"Goal: {_one_line(state.goal, 60)} | Part {index}/{total} | "
        f"Last verdict: {_last_verdict(state)} | Blockers: {blockers} | Next: {action}"
    )


def inject_goal_progress_summary(text: str | None) -> str:
    summary = goal_progress_summary()
    body = text or ""
    normalized = body.lstrip("\ufeff \t\r\n")
    if not summary or normalized.startswith(summary):
        return body
    return f"{summary}\n\n{body}" if body else summary


def _next_action_for_state(
    state: GoalState | None,
    *,
    changed_files: list[str] | None = None,
    diff: str | None = None,
    context: str | None = None,
    last_checks: Any = None,
    blockers_count: int | None = None,
) -> str:
    if not state or state.status != "active":
        return "complete"
    blockers = _blockers_count(last_checks, state) if blockers_count is None else blockers_count
    if blockers > 0:
        return "blocked_ask_user"
    if _final_check_passed(last_checks):
        return "complete"
    result = state.last_result if isinstance(state.last_result, dict) else {}
    verdict = str(result.get("verdict") or "").lower()
    part_status = str(result.get("part_status") or "").lower()
    has_new_work = bool(changed_files or diff)
    total = len(state.parts) or 1
    is_last_part = state.current_part_index >= total - 1
    if not result:
        return "run_check" if has_new_work else "continue_part"
    if verdict == "pass" and part_status == "done":
        return "run_final" if is_last_part else "continue_part"
    if has_new_work and (verdict in {"unclear", "fix_first"} or part_status in {"in_progress", "blocked"}):
        return "run_check"
    return "continue_part"


async def goal_supervisor(
    changed_files: list[str] | None = None,
    diff: str | None = None,
    context: str | None = None,
    last_checks: Any = None,
) -> dict[str, Any]:
    """Return a hard next-action enum for the primary agent's goal loop."""
    state = get_active_goal()
    blockers = _blockers_count(last_checks, state)
    next_action = _next_action_for_state(
        state,
        changed_files=changed_files,
        diff=diff,
        context=context,
        last_checks=last_checks,
        blockers_count=blockers,
    )
    return {
        "status": "idle" if not state else "ok",
        "next_action": next_action,
        "allowed_actions": sorted(NEXT_ACTIONS),
        "goal_id": state.goal_id if state else None,
        "goal": state.goal if state else None,
        "current_part_index": state.current_part_index if state else None,
        "parts_count": len(state.parts) if state else 0,
        "last_verdict": _last_verdict(state),
        "last_part_status": _last_part_status(state),
        "blockers_count": blockers,
        "summary": goal_progress_summary(state, next_action=next_action, blockers_count=blockers) if state else "",
        "reason": _supervisor_reason(next_action, state, blockers),
    }


def _supervisor_reason(next_action: str, state: GoalState | None, blockers: int) -> str:
    if not state:
        return "No active goal."
    if blockers:
        return "Last checks reported blockers; user/developer decision is needed."
    if next_action == "run_check":
        return "New work exists or last status is not clearly done; run goal alignment/checks."
    if next_action == "run_final":
        return "Current goal part is done and this is the last part; run final overall checks."
    if next_action == "complete":
        return "Final checks passed or no active goal remains."
    return "Continue implementing the current goal part."


def _parse_parts(plan: str, goal: str) -> list[str]:
    parts: list[str] = []
    in_parts = False
    for raw in plan.splitlines():
        line = raw.strip()
        lower = line.lower()
        if lower.startswith(("parts:", "subgoals:", "steps:")):
            in_parts = True
            continue
        if in_parts and lower.startswith(("acceptance:", "first action:", "done when:")):
            break
        match = re.match(r"^(?:[-*]|\d+[.)])\s+(.+)$", line)
        if match and (in_parts or not parts):
            in_parts = True
            parts.append(match.group(1).strip())
    if not parts:
        parts = [goal]
    return parts[:8]


def init_static_goal(goal: str, context: str | None = None, *, source: str = "static") -> dict[str, Any]:
    """Create an active goal without calling an LLM.

    Client prompt hooks use this so goal alignment exists even when the agent
    forgets to call goal_autopilot(mode=init) before coding.
    """
    normalized = _clean_text(goal).strip()
    if not normalized:
        return {"error": "goal is required"}
    fingerprint = _goal_fingerprint(goal)
    path = _state_path()
    with _state_lock(path):
        # Keep conflict detection and state creation in one interprocess lock.
        existing = _load_goal_state_from(path)
        if existing and existing.status == "active":
            if existing.goal_fingerprint != fingerprint:
                return {
                    "status": "conflict_active_goal",
                    "goal_id": existing.goal_id,
                    "goal": existing.goal,
                    "current_part": existing.parts[existing.current_part_index] if existing.parts else existing.goal,
                    "state_file": str(path),
                    "source": source,
                    "next_action": "Active goal belongs to a different prompt; ask the user or finish/cancel the existing goal before auto-initializing a new one.",
                }
            return {
                "status": "existing_active",
                "goal_id": existing.goal_id,
                "goal": existing.goal,
                "parts": existing.parts,
                "current_part": existing.parts[existing.current_part_index] if existing.parts else existing.goal,
                "state_file": str(path),
            }
        context_text = _short_text(context or "", 1200)
        parts = [
            "Run pre-code lifecycle gates: BA/spec/context/research checks that match the prompt.",
            "Implement the requested change in scoped batches while keeping repo boundaries intact.",
            "After each meaningful edit batch, run auto_trigger(stage=post_edit) and goal_supervisor.",
            "Before reporting done, run final checks and complete the goal only when supervisor allows complete.",
        ]
        plan_text = (
            "Plan: Static hook-created execution plan for a multi-step coding prompt.\n"
            "Parts:\n"
            + "\n".join(f"{idx + 1}. {part}" for idx, part in enumerate(parts))
            + "\nAcceptance: The requested outcome is implemented, preflight guidance was considered before code, "
            "post-edit/final checks pass, and no active goal blocker remains.\n"
            "First action: Review the injected pre-code lifecycle snapshot before editing."
        )
        if context_text:
            plan_text += "\nContext: " + context_text
        state = GoalState(goal=normalized, plan=_short_text(plan_text, 2400), parts=parts, goal_fingerprint=fingerprint)
        _save_goal_state_unlocked(path, state)
    return {
        "status": "initialized_static",
        "goal_id": state.goal_id,
        "goal": state.goal,
        "plan": state.plan,
        "parts": state.parts,
        "current_part": state.parts[0],
        "state_file": str(path),
        "source": source,
        "next_action": "Primary agent must run preflight-required items before coding, then use auto_trigger and goal_supervisor after edits.",
    }


async def _init_goal(goal: str, context: str | None = None) -> dict[str, Any]:
    normalized = _clean_text(goal).strip()
    if not normalized:
        return {"error": "goal is required for mode=init"}

    plan = await _worker(
        "Turn this user goal into a short execution plan and acceptance criteria. "
        "Do not ask follow-up questions unless the goal is impossible to start. "
        "Use this exact shape: Plan: ... Parts: 1. ... 2. ... Acceptance: ... First action: ...",
        "\n\n".join(p for p in [normalized, context or ""] if p.strip()),
    )
    plan_text = _short_text(plan.get("output") or "", 2400)
    state = GoalState(goal=normalized, plan=plan_text, parts=_parse_parts(plan_text, normalized))
    path = _state_path()
    with _state_lock(path):
        existing = _load_goal_state_from(path)
        if existing and existing.status == "active":
            if existing.goal_fingerprint != state.goal_fingerprint:
                return {
                    "status": "conflict_active_goal",
                    "goal_id": existing.goal_id,
                    "goal": existing.goal,
                    "current_part": existing.parts[existing.current_part_index] if existing.parts else existing.goal,
                    "state_file": str(path),
                    "next_action": "Active goal belongs to a different prompt; ask the user or finish/cancel the existing goal before initializing a new one.",
                }
            return {
                "status": "existing_active",
                "goal_id": existing.goal_id,
                "goal": existing.goal,
                "parts": existing.parts,
                "current_part": existing.parts[existing.current_part_index] if existing.parts else existing.goal,
                "state_file": str(path),
            }
        _save_goal_state_unlocked(path, state)
    return {
        "status": "initialized",
        "goal_id": state.goal_id,
        "goal": state.goal,
        "plan": state.plan,
        "parts": state.parts,
        "current_part": state.parts[0] if state.parts else state.goal,
        "state_file": str(path),
        "next_action": "Primary agent should execute the current part; auto_trigger(mode=max) will run checks and goal alignment after edits.",
        "warnings": [plan["error"]] if plan.get("error") else [],
    }


async def check_goal(
    changed_files: list[str] | None = None,
    diff: str | None = None,
    task: str | None = None,
    context: str | None = None,
    _retry_on_stale: int = 2,
) -> dict[str, Any]:
    path = _state_path()
    clean_changed_files = _clean_file_list(changed_files)
    state = _load_goal_state_from(path)
    if not state or state.status != "active":
        return {"status": "idle", "message": "No active goal"}
    checked_part_index = state.current_part_index

    payload = "\n\n".join(
        p for p in [
            f"Goal:\n{state.goal}",
            f"Plan:\n{state.plan}",
            "Parts:\n" + "\n".join(f"{i + 1}. {p}" for i, p in enumerate(state.parts)),
            f"Current part:\n{state.parts[state.current_part_index] if state.parts else state.goal}",
            f"Task/context:\n{task or context or ''}",
            "Changed files:\n" + "\n".join(clean_changed_files),
            f"Diff:\n{diff or ''}",
        ] if p.strip()
    )
    review = await _worker(
        "Check whether the current work is aligned with the active goal. "
        "First line must be exactly one of: verdict: pass, verdict: unclear, verdict: fix_first. "
        "Second line must be exactly one of: part_status: done, part_status: in_progress, part_status: blocked. "
        "Then give missing work and the next action in plain text.",
        payload,
    )
    output = _short_text(review.get("output") or review.get("error") or "verdict: unclear", 1800)
    lower = output.lower()
    verdict = "fix_first" if "verdict: fix_first" in lower else "pass" if "verdict: pass" in lower else "unclear"
    part_status = "done" if "part_status: done" in lower else "blocked" if "part_status: blocked" in lower else "in_progress"

    stale = False
    with _state_lock(path):
        fresh = _load_goal_state_from(path)
        if (
            not fresh
            or fresh.goal_id != state.goal_id
            or fresh.status != "active"
            or fresh.current_part_index != checked_part_index
            or fresh.revision != state.revision
        ):
            stale = True
        else:
            if (
                part_status == "done"
                and fresh.current_part_index == checked_part_index
                and fresh.current_part_index < len(fresh.parts) - 1
            ):
                fresh.current_part_index += 1
            fresh.checks_run += 1
            fresh.last_result = {
                "verdict": verdict,
                "part_status": part_status,
                "summary": output,
                "changed_files": clean_changed_files,
                "checked_at": _now(),
            }
            _save_goal_state_unlocked(path, fresh)
            state = fresh
    if stale:
        if _retry_on_stale > 0:
            await asyncio.sleep(0.05)
            return await check_goal(
                changed_files=changed_files,
                diff=diff,
                task=task,
                context=context,
                _retry_on_stale=_retry_on_stale - 1,
            )
        return {"status": "idle", "message": "Goal changed during check"}
    return {
        "status": "checked",
        "goal_id": state.goal_id,
        "goal": state.goal,
        "verdict": verdict,
        "part_status": part_status,
        "parts": state.parts,
        "current_part_index": state.current_part_index,
        "current_part": state.parts[state.current_part_index] if state.parts else state.goal,
        "summary": output,
        "checks_run": state.checks_run,
        "warnings": [review["error"]] if review.get("error") else [],
    }


async def _finish_goal(
    mode: str,
    note: str | None = None,
    changed_files: list[str] | None = None,
    diff: str | None = None,
) -> dict[str, Any]:
    path = _state_path()
    clean_changed_files = _clean_file_list(changed_files)
    state = _load_goal_state_from(path)
    if not state or state.status != "active":
        return {"status": "idle", "message": "No active goal"}

    final_check = None
    attempt_id = ""
    if mode == "complete":
        with _state_lock(path):
            fresh = _load_goal_state_from(path)
            if not fresh or fresh.goal_id != state.goal_id or fresh.status != "active":
                return {"status": "idle", "message": "Goal changed before final check", "final_check": None}
            parts_count = len(fresh.parts) or 1
            if fresh.current_part_index < parts_count - 1:
                return {
                    "status": "blocked",
                    "error": "Cannot complete goal before all parts reach the final part.",
                    "goal_id": fresh.goal_id,
                    "goal": fresh.goal,
                    "current_part_index": fresh.current_part_index,
                    "parts_count": parts_count,
                    "current_part": fresh.parts[fresh.current_part_index] if fresh.parts else fresh.goal,
                    "next_action": "continue_part",
                    "final_check": None,
                    "state_file": str(path),
                }
            if fresh.final_result:
                final_check = fresh.final_result
                state = fresh
            elif fresh.final_attempt_id and _now() - float(fresh.final_started_at or 0) < 300:
                return {
                    "status": "blocked",
                    "message": "Final goal check already in progress; wait for the active attempt before retrying.",
                    "goal_id": fresh.goal_id,
                    "goal": fresh.goal,
                    "state_file": str(path),
                    "final_attempt_id": fresh.final_attempt_id,
                    "next_action": "run_final",
                    "final_check": None,
                }
            else:
                attempt_id = f"final-{uuid.uuid4().hex[:8]}"
                fresh.final_attempt_id = attempt_id
                fresh.final_started_at = _now()
                fresh.final_result = None
                _save_goal_state_unlocked(path, fresh)
                state = fresh
        from . import auto as auto_mod
        from runtime_flags import choice_flag

        final_mode = choice_flag("HARNESS_AUTO_MODE", "safe", {"safe", "max"}, root=path.parent)

        if final_check is None:
            try:
                final_check = await auto_mod.auto_trigger(
                    changed_files=clean_changed_files,
                    diff=diff,
                    task=f"Final overall goal acceptance check:\n{state.goal}\n\n{note or ''}",
                    stage="final",
                    mode=final_mode,
                )
            except Exception as exc:
                final_check = {
                    "status": "error",
                    "stage": "final",
                    "mode": final_mode,
                    "blockers_count": 1,
                    "error": f"{type(exc).__name__}: {exc}",
                }

    final_failed = bool(
        mode == "complete"
        and final_check
        and (
            final_check.get("status") != "completed"
            or _safe_blockers_count(final_check.get("blockers_count"), 1) > 0
        )
    )

    with _state_lock(path):
        fresh = _load_goal_state_from(path)
        if not fresh or fresh.goal_id != state.goal_id or fresh.status != "active":
            return {"status": "idle", "message": "Goal changed before finish", "final_check": final_check}
        if mode == "complete" and attempt_id and fresh.final_attempt_id != attempt_id:
            return {
                "status": "blocked",
                "message": "Another final goal attempt took ownership before finish; rerun supervisor.",
                "goal_id": fresh.goal_id,
                "goal": fresh.goal,
                "state_file": str(path),
                "final_check": final_check,
                "next_action": "run_final",
            }
        parts_count = len(fresh.parts) or 1
        if mode == "complete" and fresh.current_part_index < parts_count - 1:
            return {
                "status": "blocked",
                "message": "Goal moved away from the final part during final check; rerun supervisor before completing.",
                "goal_id": fresh.goal_id,
                "goal": fresh.goal,
                "state_file": str(path),
                "final_check": final_check,
                "next_action": "run_check",
            }
        if mode == "complete":
            fresh.final_result = final_check
        fresh.status = "completed" if mode == "complete" and not final_failed else "blocked"
        fresh.completion_note = (note or "").strip()
        if final_failed:
            fresh.completion_note = (fresh.completion_note + "\nFinal check returned blockers.").strip()
        _save_goal_state_unlocked(path, fresh)
        state = fresh
    return {
        "status": state.status,
        "goal_id": state.goal_id,
        "goal": state.goal,
        "parts": state.parts,
        "final_check": final_check,
        "completion_note": state.completion_note,
        "state_file": str(path),
    }


async def goal_autopilot(
    mode: str,
    goal: str | None = None,
    context: str | None = None,
    changed_files: list[str] | None = None,
    diff: str | None = None,
    task: str | None = None,
) -> dict[str, Any]:
    """Create, check, or close the single active goal for prompt-only workflows."""
    normalized = (mode or "").strip().lower()
    if normalized == "init":
        return await _init_goal(goal or "", context)
    if normalized == "check":
        return await check_goal(changed_files=changed_files, diff=diff, task=task, context=context)
    if normalized in {"complete", "block"}:
        return await _finish_goal(normalized, context or task, changed_files=changed_files, diff=diff)
    if normalized == "status":
        state = load_goal_state()
        return {"status": "idle"} if not state else {"status": "ok", "goal": state.to_dict()}
    return {"error": "mode must be one of: init, check, complete, block, status"}
