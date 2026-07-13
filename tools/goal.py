"""
Prompt-only goal autopilot for Agent Harness.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from config import WORKSPACE_ROOT

GOAL_STATE_FILE = ".harness_goal_state.json"
MAX_TEXT = 6000
NEXT_ACTIONS = {"continue_part", "run_check", "run_final", "blocked_ask_user", "complete"}


def _state_path() -> Path:
    # ponytail: one active goal per workspace; add per-client goal ids if concurrent prompts need isolation.
    workspace = (os.getenv("CLAUDE_PROJECT_DIR") or "").strip()
    if not workspace:
        meta = os.getenv("ANTIGRAVITY_SOURCE_METADATA")
        if meta:
            try:
                workspace = str(json.loads(meta).get("tool", {}).get("workspacePath") or "").strip()
            except Exception:
                workspace = None
    workspace = workspace or (os.getenv("WORKSPACE_ROOT") or "").strip()
    workspace = str(workspace or WORKSPACE_ROOT).strip() or WORKSPACE_ROOT
    for candidate in (workspace, WORKSPACE_ROOT, os.getcwd(), tempfile.gettempdir()):
        try:
            canonical = os.path.normcase(str(Path(str(candidate)).expanduser().resolve()))
            return Path(canonical) / GOAL_STATE_FILE
        except (OSError, ValueError, RuntimeError):
            continue
    return Path(tempfile.gettempdir()) / GOAL_STATE_FILE


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
            json.dump(data, tmp, ensure_ascii=False, indent=2, sort_keys=True)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


@dataclass
class GoalState:
    goal: str
    goal_id: str = field(default_factory=lambda: f"goal-{uuid.uuid4().hex[:8]}")
    status: str = "active"
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    checks_run: int = 0
    plan: str = ""
    parts: list[str] = field(default_factory=list)
    current_part_index: int = 0
    last_result: dict[str, Any] | None = None
    completion_note: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoalState | None":
        goal = str(data.get("goal", "")).strip()
        if not goal:
            return None
        parts_data = data.get("parts", [])
        parts = [str(p).strip() for p in parts_data if str(p).strip()] if isinstance(parts_data, list) else []
        idx = max(0, _safe_int(data.get("current_part_index"), 0))
        if parts:
            idx = min(idx, len(parts) - 1)
        return cls(
            goal=goal,
            goal_id=str(data.get("goal_id") or f"goal-{uuid.uuid4().hex[:8]}"),
            status=str(data.get("status") or "active"),
            created_at=_safe_float(data.get("created_at"), _now()),
            updated_at=_safe_float(data.get("updated_at"), _now()),
            checks_run=_safe_int(data.get("checks_run"), 0),
            plan=str(data.get("plan") or ""),
            parts=parts,
            current_part_index=idx,
            last_result=data.get("last_result") if isinstance(data.get("last_result"), dict) else None,
            completion_note=str(data.get("completion_note") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _load_goal_state_from(path: Path) -> GoalState | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
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
    state.updated_at = _now()
    _atomic_write_json(path, state.to_dict())


async def _worker(instruction: str, context: str) -> dict[str, Any]:
    from .swarm import quick_task

    try:
        return await quick_task(instruction=instruction, context=context[:MAX_TEXT])
    except Exception as e:
        return {"output": None, "error": f"{type(e).__name__}: {e}"}


def _short_text(value: Any, limit: int = 1200) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:limit]


def _one_line(value: Any, limit: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
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
            explicit += max(0, int(item.get("blockers_count") or 0))
        except (TypeError, ValueError):
            pass
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


async def _init_goal(goal: str, context: str | None = None) -> dict[str, Any]:
    normalized = goal.strip()
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
            "Changed files:\n" + "\n".join(changed_files or []),
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
                "changed_files": changed_files or [],
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
    state = _load_goal_state_from(path)
    if not state or state.status != "active":
        return {"status": "idle", "message": "No active goal"}

    final_check = None
    if mode == "complete":
        from . import auto as auto_mod

        final_check = await auto_mod.auto_trigger(
            changed_files=changed_files,
            diff=diff,
            task=f"Final overall goal acceptance check:\n{state.goal}\n\n{note or ''}",
            stage="final",
            mode="max",
        )

    final_failed = bool(
        mode == "complete"
        and final_check
        and (
            final_check.get("status") != "completed"
            or int(final_check.get("blockers_count") or 0) > 0
        )
    )

    with _state_lock(path):
        fresh = _load_goal_state_from(path)
        if not fresh or fresh.goal_id != state.goal_id or fresh.status != "active":
            return {"status": "idle", "message": "Goal changed before finish", "final_check": final_check}
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
