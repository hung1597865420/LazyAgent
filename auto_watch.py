"""
Workspace file watcher for Agent Harness Auto-Pilot.

Runs outside MCP clients, so it can trigger checks even when the main model
does not explicitly call a harness tool. Stdlib-only polling keeps install simple.
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

from config import WORKSPACE_ROOT
from runtime_flags import bool_env_string, bool_flag, choice_flag, float_flag
from tools.auto import auto_trigger
from tools.watch_registry import (
    claim_global_pid,
    clear_global_pid,
    heartbeat_global_pid,
    list_repos,
    register_repo,
)

IGNORE_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".harness", ".harness_cache", ".harness_sandbox", ".harness_smoke",
    "node_modules", "venv", ".venv", "dist", "build",
}
IGNORE_DIR_PREFIXES = (
    ".harness_sandbox_",
    ".harness_smoke_",
    ".harness_targeted_test_",
    ".harness_registry_test_",
    ".harness_worktree_",
)
IGNORE_SUFFIXES = {
    ".tmp", ".temp", ".swp", ".swo", ".pyc", ".pyo", ".log", ".lock",
    ".pid", ".processing",
}
DEPENDENCY_LOCK_FILES = {
    "poetry.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
    "pipfile.lock", "uv.lock", "cargo.lock", "composer.lock",
}
IGNORE_FILES = {
    "REVIEW_REPORT.md",
}
IGNORE_PATHS = {
    ("llmwiki", "raw", ".bootstrapped"),
}
IGNORE_ROOT_FILES = {
    ".harness_ast_graph.json",
    ".harness_coverage.json",
    ".harness_goal_state.json",
    ".harness_schema_baseline.json",
}
IGNORE_ROOT_FILE_RE = re.compile(r"^\.harness_[A-Za-z0-9_.-]+\.(?:db|jsonl|pid|lock|log)(?:\.\d+)?$")
LOCK_FILE = ".harness_auto_watch.lock"
PID_FILE = ".harness_auto_watch.pid"
LOG_FILE = ".harness_auto_watch.log"
ROTATED_LOG_RE = re.compile(r".+\.log\.\d+$", re.I)
MAX_LOG_BYTES = 2_000_000
MAX_LOG_FILES = 60
REDACT_KEYS = ("key", "token", "secret", "password", "credential", "authorization")
_last_log_warning = 0.0
_PID_TOKEN = uuid.uuid4().hex
_ENV_TRIGGER_LOCK = asyncio.Lock()


def _enabled() -> bool:
    return bool_flag("HARNESS_AUTO_WATCH", False, root=_root())


def _watch_mode() -> str:
    return choice_flag("HARNESS_AUTO_WATCH_MODE", "safe", {"safe", "max"}, root=_root())


def _watch_auto_llm() -> str | None:
    return bool_env_string("HARNESS_AUTO_WATCH_LLM", False, root=_root())


async def _auto_trigger_from_watch(*, changed_files: list[str], task: str, stage: str, root: Path | None = None) -> dict:
    async with _ENV_TRIGGER_LOCK:
        previous_auto_llm = os.getenv("HARNESS_AUTO_LLM")
        previous_watch_root = os.getenv("HARNESS_WATCH_ROOT")
        previous_workspace = os.getenv("WORKSPACE_ROOT")
        previous_claude_dir = os.getenv("CLAUDE_PROJECT_DIR")
        watch_auto_llm = _watch_auto_llm()
        if watch_auto_llm is not None:
            os.environ["HARNESS_AUTO_LLM"] = watch_auto_llm
        if root is not None:
            root_s = str(root.resolve())
            os.environ["HARNESS_WATCH_ROOT"] = root_s
            os.environ["WORKSPACE_ROOT"] = root_s
            os.environ["CLAUDE_PROJECT_DIR"] = root_s
        try:
            return await auto_trigger(
                changed_files=changed_files,
                task=task,
                stage=stage,
                mode=_watch_mode(),
            )
        finally:
            for name, old in (
                ("HARNESS_WATCH_ROOT", previous_watch_root),
                ("WORKSPACE_ROOT", previous_workspace),
                ("CLAUDE_PROJECT_DIR", previous_claude_dir),
            ):
                if old is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = old
            if watch_auto_llm is not None:
                if previous_auto_llm is None:
                    os.environ.pop("HARNESS_AUTO_LLM", None)
                else:
                    os.environ["HARNESS_AUTO_LLM"] = previous_auto_llm


def _safe_float_env(name: str, default: float, min_value: float, max_value: float | None = None) -> float:
    return float_flag(name, default, min_value, max_value, root=_root())


def _root() -> Path:
    return Path(os.getenv("HARNESS_WATCH_ROOT") or os.getenv("WORKSPACE_ROOT") or WORKSPACE_ROOT).resolve()


def _ignored(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    parts = set(rel.parts)
    if parts & IGNORE_DIRS:
        return True
    rel_parts = tuple(rel.parts)
    if any(part.startswith(IGNORE_DIR_PREFIXES) for part in rel_parts):
        return True
    if rel_parts in IGNORE_PATHS:
        return True
    if len(rel_parts) >= 2 and rel_parts[0] == ".claude" and rel_parts[1] == "audit":
        return True
    name = path.name
    root_runtime_file = len(rel_parts) == 1 and (
        name in IGNORE_ROOT_FILES or bool(IGNORE_ROOT_FILE_RE.match(name))
    )
    dependency_lock_file = name.lower() in DEPENDENCY_LOCK_FILES
    return (
        name.startswith(".#")
        or name.endswith("~")
        or name in IGNORE_FILES
        or root_runtime_file
        or (path.suffix.lower() in IGNORE_SUFFIXES and not dependency_lock_file)
        or bool(ROTATED_LOG_RE.match(name))
        or name in {LOCK_FILE, PID_FILE, LOG_FILE}
    )


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """Return relpath -> (mtime_ns, size) for watchable files."""
    state: dict[str, tuple[int, int]] = {}
    if not root.exists():
        return state
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _err: None):
        base = Path(dirpath)
        try:
            rel_base = base.relative_to(root)
        except ValueError:
            continue
        rel_parts = tuple(rel_base.parts)
        if rel_parts and _ignored(base, root):
            dirnames[:] = []
            continue
        dirnames[:] = [
            name for name in dirnames
            if name not in IGNORE_DIRS
            and not name.startswith(IGNORE_DIR_PREFIXES)
            and not (not rel_parts and name.startswith(".harness_"))
        ]
        for filename in filenames:
            path = base / filename
            try:
                if _ignored(path, root) or path.is_symlink():
                    continue
                stat = path.stat()
                state[path.relative_to(root).as_posix()] = (stat.st_mtime_ns, stat.st_size)
            except (FileNotFoundError, OSError):
                continue
    return state


def changed_files(old: dict[str, tuple[int, int]], new: dict[str, tuple[int, int]]) -> list[str]:
    changed = [path for path, meta in new.items() if old.get(path) != meta]
    deleted = [path for path in old if path not in new]
    return sorted(changed + deleted)


def _read_lock(lock: Path) -> dict | None:
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _lock_owner_alive(lock: Path) -> bool:
    data = _read_lock(lock)
    if data is None:
        return False
    try:
        return _pid_alive(int(data.get("pid", 0)))
    except (ValueError, TypeError):
        return False


def _lock_stale_and_owner_dead(lock: Path, ttl: float = 900.0) -> bool:
    data = _read_lock(lock)
    if data is None:
        return True
    try:
        pid = int(data.get("pid", 0))
        ts = float(data.get("ts", 0))
    except (ValueError, TypeError):
        return True
    expired = ts <= 0 or (time.time() - ts) > ttl
    return expired and not _pid_alive(pid)


def _acquire_lock(lock: Path, ttl: float = 900.0) -> str | None:
    if lock.exists() and _lock_stale_and_owner_dead(lock, ttl):
        try:
            lock.unlink()
        except OSError:
            pass
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(lock), flags)
    except OSError:
        return None
    token = uuid.uuid4().hex
    payload = json.dumps({"pid": os.getpid(), "ts": time.time(), "token": token})
    try:
        os.write(fd, payload.encode("utf-8", errors="ignore"))
    finally:
        os.close(fd)
    return token


def _release_lock(lock: Path, token: str) -> None:
    data = _read_lock(lock)
    if not data:
        return
    try:
        same_owner = int(data.get("pid", 0)) == os.getpid() and data.get("token") == token
    except (ValueError, TypeError):
        same_owner = False
    if same_owner:
        try:
            lock.unlink()
        except OSError:
            pass


def _pid_file_fresh(pid_file: Path, ttl: float = 60.0) -> bool:
    data = _read_lock(pid_file)
    if not data:
        return False
    try:
        pid = int(data.get("pid", 0))
        ts = float(data.get("ts", 0))
    except (ValueError, TypeError):
        return False
    if pid == os.getpid() or ts <= 0 or (time.time() - ts) > ttl:
        return False
    return _pid_alive(pid)


def _claim_pid_file(pid_file: Path) -> int | None:
    if pid_file.exists() and not _pid_file_fresh(pid_file):
        try:
            pid_file.unlink()
        except OSError:
            pass
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(pid_file), flags)
    except OSError:
        return None
    _write_pid_fd(fd)
    return fd


def _write_pid_fd(fd: int) -> None:
    payload = json.dumps({"pid": os.getpid(), "ts": time.time(), "script": __file__, "token": _PID_TOKEN})
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, payload.encode("utf-8", errors="ignore"))


def _heartbeat_pid_fd(fd: int) -> None:
    try:
        _write_pid_fd(fd)
    except OSError:
        pass


def _cleanup_pid_file(pid_file: Path) -> None:
    data = _read_lock(pid_file)
    try:
        if data and int(data.get("pid", 0)) == os.getpid() and data.get("token") == _PID_TOKEN:
            pid_file.unlink()
    except (OSError, ValueError, TypeError):
        pass


def _owns_pid_file(pid_file: Path) -> bool:
    data = _read_lock(pid_file)
    try:
        return bool(data and int(data.get("pid", 0)) == os.getpid() and data.get("token") == _PID_TOKEN)
    except (ValueError, TypeError):
        return False


def _redact(value, depth: int = 0):
    if depth > 4:
        return "<truncated>"
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            key_s = str(key)
            if any(marker in key_s.lower() for marker in REDACT_KEYS):
                out[key_s] = "<redacted>"
            else:
                out[key_s] = _redact(item, depth + 1)
        return out
    if isinstance(value, list):
        return [_redact(item, depth + 1) for item in value[:MAX_LOG_FILES]]
    if isinstance(value, str):
        masked = re.sub(r"(?i)bearer\s+[a-z0-9._\-=/+]{16,}", "Bearer <redacted>", value)
        masked = re.sub(r"\bsk-[A-Za-z0-9_\-]{12,}\b", "sk-<redacted>", masked)
        masked = re.sub(r"\b[A-Za-z0-9_\-]{32,}\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}\b", "<jwt-redacted>", masked)
        return masked[:500]
    return value


def _append_log(root: Path, payload: dict) -> None:
    global _last_log_warning
    try:
        log_path = root / LOG_FILE
        if log_path.exists() and log_path.stat().st_size > MAX_LOG_BYTES:
            rotated = root / f"{LOG_FILE}.1"
            try:
                rotated.unlink()
            except OSError:
                pass
            log_path.replace(rotated)
        payload = _redact(payload)
        if isinstance(payload.get("changed_files"), list):
            payload["changed_files"] = payload["changed_files"][:MAX_LOG_FILES]
        with (root / LOG_FILE).open("a", encoding="utf-8") as f:
            try:
                line = json.dumps(payload, ensure_ascii=False, default=str)
            except Exception as e:
                line = json.dumps({"ts": time.time(), "error": f"log_serialize_failed: {type(e).__name__}: {e!r}"})
            f.write(line + "\n")
    except OSError:
        now = time.time()
        if now - _last_log_warning > 60:
            print(f"[auto_watch] warning: failed to write {LOG_FILE}", file=sys.stderr)
            _last_log_warning = now


async def run_once(root: Path | None = None, previous: dict[str, tuple[int, int]] | None = None) -> dict:
    """Single scan cycle for tests or manual one-shot use."""
    root = (root or _root()).resolve()
    before = previous if previous is not None else snapshot(root)
    after = snapshot(root)
    files = changed_files(before, after)
    if not files:
        return {"status": "idle", "changed_files": []}
    result = await _auto_trigger_from_watch(
        changed_files=files,
        task="auto_watch detected workspace file changes",
        stage="post_edit",
        root=root,
    )
    return {"status": "triggered", "changed_files": files, "auto_trigger": result}


def _global_watch_enabled() -> bool:
    return os.getenv("HARNESS_AUTO_WATCH_SINGLE", "").strip().lower() not in {"1", "true", "yes", "on"}


def _claim_global_pid() -> str | None:
    token = uuid.uuid4().hex
    return token if claim_global_pid(token) else None


async def watch_global_forever() -> None:
    if not _enabled():
        print("[auto_watch] disabled (HARNESS_AUTO_WATCH=0)")
        return

    try:
        register_repo(_root())
    except Exception:
        pass
    token = _claim_global_pid()
    if token is None:
        print("[auto_watch] global watcher already running")
        return

    interval = _safe_float_env("HARNESS_AUTO_WATCH_INTERVAL", 3.0, 0.5, 300.0)
    debounce = _safe_float_env("HARNESS_AUTO_WATCH_DEBOUNCE", 2.0, 0.5, 300.0)
    snapshots: dict[str, dict[str, tuple[int, int]]] = {}
    print(f"[auto_watch] global watcher interval={interval}s debounce={debounce}s")
    try:
        while True:
            await asyncio.sleep(interval)
            if not heartbeat_global_pid(token):
                print("[auto_watch] global watcher ownership changed, exiting")
                return
            if not _enabled():
                print("[auto_watch] disabled by runtime feature flags, exiting")
                return
            roots = [Path(r["path"]).resolve() for r in list_repos() if r.get("path")]
            for root in roots:
                if not root.exists():
                    snapshots.pop(str(root), None)
                    continue
                before = snapshots.get(str(root))
                current = snapshot(root)
                if before is None:
                    snapshots[str(root)] = current
                    continue
                files = changed_files(before, current)
                if not files:
                    snapshots[str(root)] = current
                    continue
                await asyncio.sleep(debounce)
                current = snapshot(root)
                files = changed_files(before, current)
                if not files:
                    snapshots[str(root)] = current
                    continue
                lock_info = _acquire_lock(root / LOCK_FILE)
                if lock_info is None:
                    snapshots[str(root)] = current
                    continue
                try:
                    result = await _auto_trigger_from_watch(
                        changed_files=files[:MAX_LOG_FILES],
                        task="auto_watch global detected workspace file changes",
                        stage="post_edit",
                        root=root,
                    )
                    _append_log(root, {
                        "ts": time.time(),
                        "global": True,
                        "changed_files": files[:MAX_LOG_FILES],
                        "changed_count": len(files),
                        "result": result,
                    })
                except Exception as e:
                    _append_log(root, {"ts": time.time(), "global": True, "changed_files": files, "error": str(e)})
                finally:
                    _release_lock(root / LOCK_FILE, lock_info)
                    snapshots[str(root)] = current
    finally:
        clear_global_pid(token)


async def watch_forever() -> None:
    if not _enabled():
        print("[auto_watch] disabled (HARNESS_AUTO_WATCH=0)")
        return

    root = _root()
    if not root.exists():
        print(f"[auto_watch] workspace root does not exist: {root}")
        return
    interval = _safe_float_env("HARNESS_AUTO_WATCH_INTERVAL", 3.0, 0.5, 300.0)
    debounce = _safe_float_env("HARNESS_AUTO_WATCH_DEBOUNCE", 2.0, 0.5, 300.0)
    lock = root / LOCK_FILE
    pid_file = root / PID_FILE
    pid_fd = _claim_pid_file(pid_file)
    if pid_fd is None:
        print(f"[auto_watch] already running for {root}")
        return
    last = snapshot(root)
    missing_root_count = 0
    print(f"[auto_watch] watching {root} interval={interval}s debounce={debounce}s")

    try:
        while True:
            await asyncio.sleep(interval)
            if not _enabled():
                print("[auto_watch] disabled by runtime feature flags, exiting")
                return
            if not root.exists():
                missing_root_count += 1
                if missing_root_count >= 3:
                    print(f"[auto_watch] workspace root disappeared, exiting: {root}")
                    return
                continue
            missing_root_count = 0
            _heartbeat_pid_fd(pid_fd)
            if not _owns_pid_file(pid_file):
                print(f"[auto_watch] pid ownership changed, exiting: {root}")
                return
            current = snapshot(root)
            files = changed_files(last, current)
            if not files:
                last = current
                continue
            await asyncio.sleep(debounce)
            if not _owns_pid_file(pid_file):
                print(f"[auto_watch] pid ownership changed, exiting: {root}")
                return
            current = snapshot(root)
            files = changed_files(last, current)
            if not files:
                last = current
                continue
            if not _owns_pid_file(pid_file):
                print(f"[auto_watch] pid ownership changed, exiting: {root}")
                return
            lock_info = _acquire_lock(lock)
            if lock_info is None:
                if root.exists():
                    last = current
                continue
            lock_token = lock_info
            try:
                if not _owns_pid_file(pid_file):
                    print(f"[auto_watch] pid ownership changed, exiting: {root}")
                    return
                result = await _auto_trigger_from_watch(
                    changed_files=files[:MAX_LOG_FILES],
                    task="auto_watch detected workspace file changes",
                    stage="post_edit",
                    root=root,
                )
                _append_log(root, {
                    "ts": time.time(),
                    "changed_files": files[:MAX_LOG_FILES],
                    "changed_count": len(files),
                    "result": result,
                })
            except Exception as e:
                _append_log(root, {"ts": time.time(), "changed_files": files, "error": str(e)})
            finally:
                _release_lock(lock, lock_token)
                last = current
    finally:
        try:
            os.close(pid_fd)
        except OSError:
            pass
        _cleanup_pid_file(pid_file)


def main() -> None:
    if _global_watch_enabled():
        asyncio.run(watch_global_forever())
    else:
        asyncio.run(watch_forever())


if __name__ == "__main__":
    main()
