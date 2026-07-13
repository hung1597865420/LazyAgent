"""
Direct prompt runner for Agent Harness goals.

This is the missing "one prompt into harness" entry point: it initializes a
goal, delegates implementation to an external coding-agent command, then runs
the existing Auto-Pilot / supervisor / prod gate loop.
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .auto import auto_trigger
from .core import _get_active_workspace, _git_diff, _run_cmd_safe
from .goal import goal_autopilot, goal_supervisor, load_goal_state
from .prod import prod_readiness_gate

BLOCKING_PROD_VERDICTS = {"fix_required", "blocked_needs_user", "rollback_required"}
RUNNER_LOCK_FILE = ".harness_goal_runner.lock"


def _root() -> Path:
    return Path(_get_active_workspace()).resolve()


def _safe_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, parsed))


def _safe_float(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, parsed))


def _changed_files() -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "-z"],
            cwd=str(_root()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        proc = None
    if proc and proc.returncode == 0 and b"\0" in proc.stdout:
        return _parse_porcelain_z_bytes(proc.stdout)
    rc, out, _ = _run_cmd_safe(["git", "status", "--porcelain"], cwd=str(_root()))
    if rc != 0:
        return []
    files: list[str] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        rel = line[3:].strip()
        if " -> " in rel:
            rel = rel.rsplit(" -> ", 1)[-1].strip()
        rel = rel.strip('"')
        if rel and rel not in files:
            files.append(rel)
    return files


def _parse_porcelain_z(output: str) -> list[str]:
    return _parse_porcelain_z_bytes(output.encode("utf-8", errors="surrogateescape"))


def _parse_porcelain_z_bytes(output: bytes) -> list[str]:
    files: list[str] = []
    items = [item for item in output.split(b"\0") if item]
    i = 0
    while i < len(items):
        item = items[i]
        status = item[:2]
        rel_b = item[3:].strip() if len(item) > 3 else b""
        if status[:1] in {b"R", b"C"} or status[1:2] in {b"R", b"C"}:
            i += 1
            if i < len(items):
                rel_b = items[i].strip()
        rel = rel_b.decode("utf-8", errors="surrogateescape")
        if rel and rel not in files:
            files.append(rel)
        i += 1
    return files


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(process_query, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _process_start_id(pid: int) -> str:
    if pid <= 0:
        return ""
    if os.name == "nt":
        import ctypes

        process_query = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query, False, pid)
        if not handle:
            return ""
        try:
            creation = ctypes.c_ulonglong()
            exit_time = ctypes.c_ulonglong()
            kernel = ctypes.c_ulonglong()
            user = ctypes.c_ulonglong()
            ok = ctypes.windll.kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel),
                ctypes.byref(user),
            )
            return str(creation.value) if ok else ""
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    stat = Path(f"/proc/{pid}/stat")
    try:
        text = stat.read_text(encoding="utf-8", errors="replace")
        return text.rsplit(") ", 1)[1].split()[19]
    except Exception:
        return ""


def _read_lock(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _acquire_runner_lock() -> tuple[Path, int] | None:
    path = _root() / RUNNER_LOCK_FILE
    for attempt in range(3):
        if path.exists():
            data = _read_lock(path)
            pid = _safe_int(data.get("pid"), 0, 0, 10_000_000)
            owner_start = str(data.get("process_start_id") or "")
            current_start = _process_start_id(pid) if owner_start else ""
            if not _pid_alive(pid) or (owner_start and current_start and owner_start != current_start):
                try:
                    path.unlink()
                except OSError:
                    pass
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except OSError:
            if attempt == 2:
                return None
            time.sleep(0.05 * (attempt + 1))
    payload = json.dumps({"pid": os.getpid(), "ts": time.time(), "process_start_id": _process_start_id(os.getpid())})
    os.write(fd, payload.encode("utf-8"))
    os.close(fd)
    return path, os.getpid()


def _release_runner_lock(lock: tuple[Path, int] | None) -> None:
    if not lock:
        return
    path, pid = lock
    data = _read_lock(path)
    if _safe_int(data.get("pid"), -1, -1, 10_000_000) != pid:
        return
    owner_start = str(data.get("process_start_id") or "")
    if owner_start and owner_start != _process_start_id(pid):
        return
    try:
        path.unlink()
    except OSError:
        pass


def _current_part() -> str:
    state = load_goal_state()
    if not state:
        return ""
    if state.parts:
        idx = max(0, min(state.current_part_index, len(state.parts) - 1))
        return state.parts[idx]
    return state.goal


def _agent_prompt(prompt: str, supervisor: dict[str, Any]) -> str:
    part = _current_part() or str(supervisor.get("goal") or prompt)
    return (
        "You are the implementation agent for Agent Harness direct goal runner.\n"
        "Implement the current part directly in the workspace. Keep changes scoped. "
        "Run useful local checks if available, then exit without asking follow-up questions unless blocked.\n\n"
        f"Goal:\n{prompt}\n\n"
        f"Current part:\n{part}\n\n"
        f"Supervisor summary:\n{supervisor.get('summary') or ''}\n"
    )


def _split_command(command: str) -> list[str]:
    return shlex.split(command, posix=os.name != "nt")


def _resolve_agent_command(agent_command: str | list[str] | None, prompt: str) -> tuple[list[str], str]:
    if isinstance(agent_command, list) and agent_command and all(isinstance(item, str) and item.strip() for item in agent_command):
        return [item.replace("{prompt}", prompt) for item in agent_command], "custom_argv"
    command = (agent_command if isinstance(agent_command, str) else os.getenv("HARNESS_GOAL_AGENT_CMD") or "").strip()
    if command:
        if "{prompt}" in command:
            return _split_command(command.replace("{prompt}", prompt)), "custom"
        return _split_command(command) + [prompt], "custom"
    candidates = [
        ("claude", ["claude", "-p", prompt]),
        ("gemini", ["gemini", "-p", prompt]),
        ("codex", ["codex", "exec", prompt]),
    ]
    for name, cmd in candidates:
        if shutil.which(name):
            return cmd, name
    return [], ""


async def _run_agent(prompt: str, agent_command: str | None, timeout: float) -> dict[str, Any]:
    cmd, source = _resolve_agent_command(agent_command, prompt)
    if not cmd:
        return {
            "status": "missing_agent_command",
            "returncode": None,
            "stdout": "",
            "stderr": "Set HARNESS_GOAL_AGENT_CMD, pass agent_command, or install claude/gemini/codex CLI.",
        }
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(_root()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()  # type: ignore[name-defined]
        except Exception:
            pass
        return {"status": "timeout", "command_source": source, "returncode": None, "stdout": "", "stderr": "agent command timed out"}
    except Exception as exc:
        return {"status": "error", "command_source": source, "returncode": None, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}"}
    return {
        "status": "completed" if proc.returncode == 0 else "failed",
        "command_source": source,
        "returncode": proc.returncode,
        "stdout": stdout.decode("utf-8", errors="replace")[-4000:],
        "stderr": stderr.decode("utf-8", errors="replace")[-4000:],
    }


def _prod_gate_ok(result: dict[str, Any]) -> bool:
    blockers_raw = result.get("blockers_count", 0)
    try:
        blockers = int(blockers_raw or 0)
    except (TypeError, ValueError):
        blockers = 1
    return str(result.get("verdict") or "").lower() not in BLOCKING_PROD_VERDICTS and blockers == 0


async def goal_runner(
    prompt: str,
    *,
    max_iterations: int = 8,
    mode: str = "max",
    agent_command: str | list[str] | None = None,
    agent_timeout: float = 900.0,
    dry_run: bool = False,
    final_prod_gate: bool = True,
) -> dict[str, Any]:
    """Run a prompt through the goal/supervisor/check loop without relying on client rules."""
    prompt = (prompt or "").strip()
    if not prompt:
        return {"error": "invalid_argument", "detail": "prompt is required"}
    if agent_command is not None and not (
        isinstance(agent_command, str)
        or (isinstance(agent_command, list) and all(isinstance(item, str) and item.strip() for item in agent_command))
    ):
        return {"error": "invalid_argument", "detail": "agent_command must be a string or list of non-empty strings"}
    mode = (mode or "max").strip().lower()
    if mode not in {"safe", "max"}:
        return {"error": "invalid_argument", "detail": "mode must be one of: safe, max"}
    max_iterations = _safe_int(max_iterations, 8, 1, 30)
    agent_timeout = _safe_float(agent_timeout, 900.0, 5.0, 7200.0)

    lock = _acquire_runner_lock()
    if lock is None:
        return {"status": "blocked_goal_busy", "detail": "Another goal_runner is already active in this workspace."}
    try:
        return await _goal_runner_locked(prompt, max_iterations, mode, agent_command, agent_timeout, dry_run, final_prod_gate)
    finally:
        _release_runner_lock(lock)


async def _goal_runner_locked(
    prompt: str,
    max_iterations: int,
    mode: str,
    agent_command: str | list[str] | None,
    agent_timeout: float,
    dry_run: bool,
    final_prod_gate: bool,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    init = await goal_autopilot(mode="init", goal=prompt, context="direct goal_runner")
    events.append({"step": "init", "status": init.get("status"), "goal_id": init.get("goal_id")})
    if init.get("error"):
        return {"status": "failed", "events": events, "init": init}

    last_checks: dict[str, Any] | None = None
    changed: list[str] = []
    diff = ""
    for iteration in range(1, max_iterations + 1):
        supervisor = await goal_supervisor(changed_files=changed, diff=diff, context=prompt, last_checks=last_checks)
        action = str(supervisor.get("next_action") or "")
        events.append({"step": "supervisor", "iteration": iteration, "next_action": action, "summary": supervisor.get("summary")})

        if action == "complete":
            return {"status": "completed", "events": events, "supervisor": supervisor}
        if action == "blocked_ask_user":
            return {"status": "blocked_needs_user", "events": events, "supervisor": supervisor, "last_checks": last_checks}
        if action == "run_final":
            final = await prod_readiness_gate(changed_files=changed, diff=diff, task=prompt, mode=mode) if final_prod_gate else await auto_trigger(changed_files=changed, diff=diff, task=prompt, stage="final", mode=mode)
            finish_mode = "complete" if _prod_gate_ok(final) else "block"
            finish = await goal_autopilot(mode=finish_mode, context=json.dumps(final, ensure_ascii=False)[:4000], changed_files=changed, diff=diff, task=prompt)
            events.append({"step": "final", "verdict": final.get("verdict"), "finish_status": finish.get("status")})
            return {"status": finish.get("status"), "events": events, "final": final, "finish": finish}
        if action == "run_check":
            changed = _changed_files()
            diff, _ = _git_diff()
            last_checks = await auto_trigger(changed_files=changed, diff=diff, task=prompt, stage="post_edit", mode=mode)
            events.append({"step": "check", "changed_files": changed, "status": last_checks.get("status"), "selected_tools": last_checks.get("selected_tools")})
            continue

        if action != "continue_part":
            return {"status": "blocked_unknown_action", "events": events, "supervisor": supervisor}
        if dry_run:
            return {"status": "blocked_needs_agent", "events": events, "supervisor": supervisor, "agent": {"status": "dry_run"}}
        agent = await _run_agent(_agent_prompt(prompt, supervisor), agent_command, agent_timeout)
        changed = _changed_files()
        diff, _ = _git_diff()
        events.append({"step": "agent", "iteration": iteration, "agent_status": agent.get("status"), "changed_files": changed})
        agent_status = str(agent.get("status") or "")
        if agent_status == "missing_agent_command":
            return {"status": "blocked_needs_agent", "events": events, "agent": agent}
        if agent_status in {"failed", "timeout", "error"}:
            return {"status": "blocked_agent_failed", "events": events, "agent": agent}
        if not changed:
            return {"status": "blocked_no_changes", "events": events, "agent": agent}
        last_checks = await auto_trigger(changed_files=changed, diff=diff, task=prompt, stage="post_edit", mode=mode)
        events.append({"step": "check", "changed_files": changed, "status": last_checks.get("status"), "selected_tools": last_checks.get("selected_tools")})

    return {"status": "blocked_max_iterations", "events": events, "last_checks": last_checks}
