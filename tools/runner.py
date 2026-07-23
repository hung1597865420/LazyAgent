"""
Direct prompt runner for Agent Harness goals.

This is the missing "one prompt into harness" entry point: it initializes a
goal, delegates implementation to an external coding-agent command, then runs
the existing Auto-Pilot / supervisor / prod gate loop.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .auto import auto_trigger
from .core import _get_active_workspace, _git_diff, _run_cmd_safe, load_relevant_lessons_context, record_procedure_lesson
from .goal import goal_autopilot, goal_supervisor, load_goal_state
from .integrations import agent_guidance_for_task
from .lifecycle import preflight_trigger
from .prod import prod_readiness_gate

BLOCKING_PROD_VERDICTS = {"fix_required", "blocked_needs_user", "rollback_required"}
RUNNER_LOCK_FILE = ".harness_goal_runner.lock"
MAX_AGENT_LESSONS_CHARS = 12_000
MAX_LESSON_QUERY_CHARS = 4_000
MAX_AGENT_FIELD_CHARS = 1_500
MAX_AGENT_INTEGRATION_CHARS = 2_500
MAX_AGENT_PREFLIGHT_GATES = 6
MAX_AGENT_PROMPT_CHARS = 18_000


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


def _changed_files(root: Path | None = None) -> list[str]:
    workspace = root or _root()
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "-z"],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        proc = None
    if proc and proc.returncode == 0 and b"\0" in proc.stdout:
        return _parse_porcelain_z_bytes(proc.stdout)
    rc, out, _ = _run_cmd_safe(["git", "status", "--porcelain"], cwd=str(workspace))
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


@contextmanager
def _pinned_workspace(root: Path):
    old = {key: os.environ.get(key) for key in ("WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR", "ANTIGRAVITY_SOURCE_METADATA")}
    try:
        os.environ["WORKSPACE_ROOT"] = str(root)
        os.environ["CLAUDE_PROJECT_DIR"] = str(root)
        os.environ.pop("ANTIGRAVITY_SOURCE_METADATA", None)
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _normalize_lesson_query(text: str) -> str:
    clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text or "")
    return re.sub(r"\s+", " ", clean).strip()[:MAX_LESSON_QUERY_CHARS]


def _cap_lesson_block(text: str) -> str:
    if len(text) <= MAX_AGENT_LESSONS_CHARS:
        return text
    return text[:MAX_AGENT_LESSONS_CHARS].rstrip() + "\n- [truncated prior lessons]"


def _cap_agent_field(text: Any) -> str:
    clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", str(text or ""))
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) <= MAX_AGENT_FIELD_CHARS:
        return clean
    return clean[:MAX_AGENT_FIELD_CHARS].rstrip() + " [truncated]"


def _cap_agent_block(text: Any, max_chars: int, marker: str) -> str:
    clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", str(text or ""))
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars].rstrip() + f"\n- [{marker}]"


def _cap_agent_prompt(text: str) -> str:
    if len(text) <= MAX_AGENT_PROMPT_CHARS:
        return text
    marker = "\n\n[truncated agent prompt middle to stay within harness budget]\n\n"
    head_len = MAX_AGENT_PROMPT_CHARS // 2
    tail_len = MAX_AGENT_PROMPT_CHARS - head_len - len(marker)
    return text[:head_len].rstrip() + marker + text[-tail_len:].lstrip()


def _agent_prompt(prompt: str, supervisor: dict[str, Any], root: Path | None = None) -> str:
    part = _current_part() or str(supervisor.get("goal") or prompt)
    lesson_text = _normalize_lesson_query(" ".join(str(x or "") for x in (prompt, part, supervisor.get("summary"))))
    try:
        if root is None:
            prior_lessons = load_relevant_lessons_context(lesson_text, limit=5)
        else:
            with _pinned_workspace(root):
                prior_lessons = load_relevant_lessons_context(lesson_text, limit=5)
    except Exception:
        prior_lessons = ""
    prior_lessons = _cap_lesson_block(prior_lessons)
    prior_block = f"\nPrior lessons:\n{prior_lessons}\n" if prior_lessons else ""
    try:
        integration_guidance = agent_guidance_for_task(prompt, root=root)
    except Exception:
        integration_guidance = ""
    integration_guidance = _cap_agent_block(
        integration_guidance,
        MAX_AGENT_INTEGRATION_CHARS,
        "truncated integration guidance",
    )
    integration_block = f"\n{integration_guidance}\n\n" if integration_guidance else ""
    try:
        if root is None:
            preflight = preflight_trigger(task=prompt)
        else:
            with _pinned_workspace(root):
                preflight = preflight_trigger(task=prompt)
        required = [
            f"- {_cap_agent_field(item.get('tool'))}: {_cap_agent_field(item.get('reason'))}"
            for item in preflight.get("run_now", [])
            if isinstance(item, dict) and item.get("required") and not item.get("blocked_by_profile")
        ][:MAX_AGENT_PREFLIGHT_GATES]
    except Exception:
        required = []
    preflight_block = ""
    if required:
        preflight_block = (
            "\nPre-code lifecycle gates:\n"
            "Run/consider these before editing; auto_trigger is only for post-edit verification.\n"
            + "\n".join(required)
            + "\n\n"
        )
    assembled = (
        "You are the implementation agent for Agent Harness direct goal runner.\n"
        "Implement the current part directly in the workspace. Keep changes scoped. "
        "Run useful local checks if available, then exit without asking follow-up questions unless blocked.\n\n"
        "Use any prior lessons below as constraints and shortcuts; do not repeat a known failed approach.\n"
        "If this run discovers a reusable non-error workflow/procedure, print one final single-line marker:\n"
        "HARNESS_LESSON_JSON: {\"title\":\"...\",\"summary\":\"...\",\"steps\":[\"...\"],\"tags\":[\"...\"]}\n"
        "Only emit the marker for durable, reusable knowledge; do not include secrets.\n\n"
        f"{integration_block}"
        f"{preflight_block}"
        f"{prior_block}"
        f"Goal:\n{_cap_agent_field(prompt)}\n\n"
        f"Current part:\n{_cap_agent_field(part)}\n\n"
        f"Supervisor summary:\n{_cap_agent_field(supervisor.get('summary') or '')}\n"
    )
    return _cap_agent_prompt(assembled)


def _record_agent_lessons(prompt: str, agent: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    agent_status = str(agent.get("status") or "")
    if agent_status not in {"completed", "success"}:
        return records
    marker = "HARNESS_LESSON_JSON:"
    text = "\n".join(str(agent.get(k) or "") for k in ("stdout", "stderr"))
    pos = 0
    marker_seen = False
    while True:
        start = text.find(marker, pos)
        if start < 0:
            break
        marker_seen = True
        raw_start = start + len(marker)
        while raw_start < len(text) and text[raw_start].isspace():
            raw_start += 1
        raw_end = raw_start
        depth = 0
        in_string = False
        escaped = False
        for idx in range(raw_start, len(text)):
            ch = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    raw_end = idx + 1
                    break
        if raw_end <= raw_start:
            raw_end = text.find("\n", raw_start)
            if raw_end < 0:
                raw_end = len(text)
        raw = text[raw_start:raw_end].strip()
        pos = raw_end
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            records.append({"status": "skipped", "reason": "invalid lesson json"})
            continue
        if not isinstance(payload, dict):
            records.append({"status": "skipped", "reason": "lesson payload must be an object"})
            continue
        records.append(record_procedure_lesson(
            title=str(payload.get("title") or ""),
            summary=str(payload.get("summary") or ""),
            steps=payload.get("steps"),
            tags=payload.get("tags"),
            source="goal_runner",
            refs={"goal": prompt[:500]},
        ))
    if not records and not marker_seen:
        fallback = _infer_agent_procedure_lesson(prompt, text)
        if fallback:
            records.append(record_procedure_lesson(
                title=fallback["title"],
                summary=fallback["summary"],
                steps=fallback["steps"],
                tags=fallback["tags"],
                source="goal_runner_fallback",
                refs={"goal": prompt[:500], "extraction": "structured_output_fallback"},
            ))
    return records


def _infer_agent_procedure_lesson(prompt: str, text: str) -> dict[str, Any] | None:
    if not text.strip():
        return None
    low = text.lower()
    triggers = (
        "reusable workflow", "standard workflow", "lesson learned", "procedure:",
        "best practice", "standard way", "workflow learned", "quy trình", "bài học",
        "cách làm chuẩn", "các bước",
    )
    trigger_score = sum(1 for item in triggers if item in low)
    if trigger_score < 1 or not re.search(r"(?im)^\s*(?:steps?|procedure|workflow|các bước|quy trình)\s*:", text):
        return None
    title = _extract_labeled_value(text, ("title", "lesson", "procedure", "workflow", "quy trình", "bài học"))
    if not title:
        title = _title_from_prompt(prompt)
    title = re.sub(r"\s+", " ", title).strip(" -:")[:120]
    if not _lesson_title_is_reusable(title):
        return None
    summary = _extract_labeled_value(text, ("summary", "use when", "why", "mô tả", "khi dùng"))
    if not summary:
        return None
    summary = re.sub(r"\s+", " ", summary).strip()[:600]
    steps = _extract_structured_steps(text)
    if len(steps) < 2:
        return None
    if _imperative_step_count(steps) < 2:
        return None
    score = trigger_score * 2 + len(steps) * 3 + (4 if summary else 0) + (4 if title else 0)
    if score < 12:
        return None
    return {"title": title, "summary": summary, "steps": steps[:8], "tags": _fallback_lesson_tags(prompt, title)}


def _extract_labeled_value(text: str, labels: tuple[str, ...]) -> str:
    joined = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?im)^\s*(?:{joined})\s*:\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else ""


def _extract_structured_steps(text: str) -> list[str]:
    steps: list[str] = []
    in_steps = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if in_steps and steps:
                break
            continue
        if re.match(r"(?i)^(?:steps?|procedure|workflow|các bước|quy trình)\s*:", line):
            in_steps = True
            continue
        match = re.match(r"^(?:[-*]|\d+[.)])\s+(.+)$", line)
        if match and (in_steps or len(steps) > 0):
            step = re.sub(r"\s+", " ", match.group(1)).strip()
            if step and len(step) <= 240:
                steps.append(step)
            continue
        if in_steps and steps:
            break
    return steps


def _imperative_step_count(steps: list[str]) -> int:
    verbs = {
        "add", "apply", "build", "check", "choose", "click", "configure", "connect",
        "create", "deploy", "export", "import", "install", "open", "review", "run",
        "save", "select", "set", "sync", "test", "update", "verify", "write",
        "bật", "cấu", "chạy", "chọn", "ghi", "kiểm", "mở", "nhập", "tạo", "thêm", "xuất",
    }
    count = 0
    for step in steps:
        first = re.match(r"^[\wÀ-ỹ-]+", step.lower(), flags=re.UNICODE)
        if first and first.group(0) in verbs:
            count += 1
    return count


def _title_from_prompt(prompt: str) -> str:
    text = re.sub(r"\s+", " ", prompt or "").strip()
    return text[:100] or "Reusable workflow"


def _lesson_title_is_reusable(title: str) -> bool:
    if len(title) < 8:
        return False
    low = title.lower()
    project_specific = (".py", ".js", ".ts", ".tsx", ".json", "traceback", "exception", "bug", "fix", "patch", "diff")
    return not any(item in low for item in project_specific)


def _fallback_lesson_tags(prompt: str, title: str) -> list[str]:
    stop = {
        "the", "and", "for", "with", "from", "this", "that", "workflow", "procedure",
        "lesson", "learned", "create", "setup", "configure", "cach", "quy", "trinh",
    }
    tags: list[str] = []
    for term in re.findall(r"[\wÀ-ỹ][\wÀ-ỹ_-]{3,}", f"{title} {prompt}".lower(), flags=re.UNICODE):
        if term not in stop and term not in tags:
            tags.append(term[:40])
        if len(tags) >= 6:
            break
    return tags or ["workflow"]


def _split_command(command: str) -> list[str]:
    return shlex.split(command, posix=os.name != "nt")


def _custom_agent_command_allowed() -> bool:
    return str(os.getenv("HARNESS_ALLOW_CUSTOM_AGENT_COMMAND") or "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_agent_command(agent_command: str | list[str] | None, prompt: str) -> tuple[list[str], str]:
    if agent_command is not None and not _custom_agent_command_allowed():
        return [], "custom_disabled"
    if isinstance(agent_command, list) and agent_command and all(isinstance(item, str) and item.strip() for item in agent_command):
        return [item.replace("{prompt}", prompt) for item in agent_command], "custom_argv"
    command = (agent_command if isinstance(agent_command, str) else os.getenv("HARNESS_GOAL_AGENT_CMD") or "").strip()
    if command:
        if "{prompt}" in command:
            return _split_command(command.replace("{prompt}", prompt)), "custom" if agent_command is not None else "env"
        return _split_command(command) + [prompt], "custom" if agent_command is not None else "env"
    candidates = [
        ("claude", ["claude", "-p", prompt]),
        ("gemini", ["gemini", "-p", prompt]),
        ("codex", ["codex", "exec", prompt]),
    ]
    for name, cmd in candidates:
        if shutil.which(name):
            return cmd, name
    return [], ""


async def _run_agent(prompt: str, agent_command: str | list[str] | None, timeout: float, root: Path | None = None) -> dict[str, Any]:
    cmd, source = _resolve_agent_command(agent_command, prompt)
    if source == "custom_disabled":
        return {
            "status": "custom_agent_command_disabled",
            "returncode": None,
            "stdout": "",
            "stderr": "Per-call agent_command is disabled; set HARNESS_GOAL_AGENT_CMD server-side or HARNESS_ALLOW_CUSTOM_AGENT_COMMAND=1 for trusted local debugging.",
        }
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
            cwd=str(root or _root()),
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
    resume: bool = False,
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
    if agent_command is not None and not _custom_agent_command_allowed():
        return {
            "error": "custom_agent_command_disabled",
            "detail": "Per-call agent_command is disabled by default. Use HARNESS_GOAL_AGENT_CMD server-side or set HARNESS_ALLOW_CUSTOM_AGENT_COMMAND=1 only for trusted local debugging.",
        }
    mode = (mode or "max").strip().lower()
    if mode not in {"safe", "max"}:
        return {"error": "invalid_argument", "detail": "mode must be one of: safe, max"}
    max_iterations = _safe_int(max_iterations, 8, 1, 30)
    agent_timeout = _safe_float(agent_timeout, 900.0, 5.0, 7200.0)

    lock = _acquire_runner_lock()
    if lock is None:
        return {"status": "blocked_goal_busy", "detail": "Another goal_runner is already active in this workspace."}
    root = _root()
    try:
        result = await _goal_runner_locked(prompt, max_iterations, mode, agent_command, agent_timeout, dry_run, final_prod_gate, resume, root)
        try:
            from .ops import append_run_ledger

            append_run_ledger({"tool": "goal_runner", "prompt": prompt[:500], "status": result.get("status"), "events": result.get("events", [])})
        except Exception:
            pass
        return result
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
    resume: bool,
    root: Path,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    try:
        from .ops import harness_doctor

        doctor = await harness_doctor()
        events.append({"step": "doctor", "ready": doctor.get("ready"), "problems": doctor.get("problems", [])})
    except Exception as exc:
        events.append({"step": "doctor", "ready": False, "error": str(exc)})
    state = load_goal_state()
    if resume and state:
        init = {"status": "resumed", "goal_id": state.goal_id}
    else:
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
            with _pinned_workspace(root):
                final = await prod_readiness_gate(changed_files=changed, diff=diff, task=prompt, mode=mode) if final_prod_gate else await auto_trigger(changed_files=changed, diff=diff, task=prompt, stage="final", mode=mode)
            finish_mode = "complete" if _prod_gate_ok(final) else "block"
            finish = await goal_autopilot(mode=finish_mode, context=json.dumps(final, ensure_ascii=False)[:4000], changed_files=changed, diff=diff, task=prompt)
            events.append({"step": "final", "verdict": final.get("verdict"), "finish_status": finish.get("status")})
            return {"status": finish.get("status"), "events": events, "final": final, "finish": finish}
        if action == "run_check":
            changed = _changed_files(root)
            diff, _ = _git_diff(cwd=str(root))
            with _pinned_workspace(root):
                last_checks = await auto_trigger(changed_files=changed, diff=diff, task=prompt, stage="post_edit", mode=mode)
            events.append({"step": "check", "changed_files": changed, "status": last_checks.get("status"), "selected_tools": last_checks.get("selected_tools")})
            continue

        if action != "continue_part":
            return {"status": "blocked_unknown_action", "events": events, "supervisor": supervisor}
        if dry_run:
            return {"status": "blocked_needs_agent", "events": events, "supervisor": supervisor, "agent": {"status": "dry_run"}}
        agent = await _run_agent(_agent_prompt(prompt, supervisor, root), agent_command, agent_timeout, root)
        learned = _record_agent_lessons(prompt, agent)
        changed = _changed_files(root)
        diff, _ = _git_diff(cwd=str(root))
        event = {"step": "agent", "iteration": iteration, "agent_status": agent.get("status"), "changed_files": changed}
        if learned:
            event["lessons"] = learned
        events.append(event)
        agent_status = str(agent.get("status") or "")
        if agent_status == "missing_agent_command":
            return {"status": "blocked_needs_agent", "events": events, "agent": agent}
        if agent_status in {"failed", "timeout", "error"}:
            return {"status": "blocked_agent_failed", "events": events, "agent": agent}
        if not changed:
            return {"status": "blocked_no_changes", "events": events, "agent": agent}
        with _pinned_workspace(root):
            last_checks = await auto_trigger(changed_files=changed, diff=diff, task=prompt, stage="post_edit", mode=mode)
        events.append({"step": "check", "changed_files": changed, "status": last_checks.get("status"), "selected_tools": last_checks.get("selected_tools")})

    return {
        "status": "blocked_needs_agent",
        "reason": "max_iterations_reached",
        "max_iterations": max_iterations,
        "events": events,
        "last_checks": last_checks,
    }
