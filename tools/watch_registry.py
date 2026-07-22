"""Global Auto-Watch registry.

Keeps one user-level list of repositories that Agent Harness should watch.
The watcher process can reconcile this list instead of spawning one long-lived
watch process per repo.
"""

from __future__ import annotations

import json
import os
import time
import ctypes
from pathlib import Path
from typing import Any

REGISTRY_DIR = Path.home() / ".agent-harness"
REGISTRY_FILE = REGISTRY_DIR / "watch.repos.json"
GLOBAL_PID_FILE = REGISTRY_DIR / "auto_watch.global.pid"
REGISTRY_LOCK_FILE = REGISTRY_DIR / "watch.repos.lock"
GLOBAL_PID_LOCK_FILE = REGISTRY_DIR / "auto_watch.global.lock"
LOCK_STALE_SECONDS = 15
GLOBAL_PID_TTL_SECONDS = 60
_LOCK_TOKENS: dict[int, str] = {}


def _repo_ok(path: Path) -> bool:
    return path.is_dir() and any((path / marker).exists() for marker in (".git", ".svn", ".harness_cache", ".Codex"))


def _load() -> dict[str, Any]:
    try:
        if REGISTRY_FILE.is_file():
            data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"repos": []}


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


def _lock_reclaimable(lock_file: Path) -> bool:
    try:
        if time.time() - lock_file.stat().st_mtime <= LOCK_STALE_SECONDS:
            return False
        data = json.loads(lock_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return True
        pid = int(data.get("pid", 0))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return True
    return not _pid_alive(pid)


def _claim_lock(lock_file: Path, timeout: float = 5.0) -> int | None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + max(0.1, timeout)
    while time.time() < deadline:
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            token = f"{os.getpid()}:{time.time()}:{id(lock_file)}"
            os.write(fd, json.dumps({"pid": os.getpid(), "ts": time.time(), "token": token}).encode("utf-8"))
            _LOCK_TOKENS[fd] = token
            return fd
        except OSError:
            time.sleep(0.05)
    return None


def _release_lock(lock_file: Path, fd: int | None) -> None:
    if fd is None:
        return
    token = _LOCK_TOKENS.pop(fd, None)
    try:
        os.close(fd)
    except OSError:
        pass
    if token is None:
        return
    try:
        data = json.loads(lock_file.read_text(encoding="utf-8"))
        same_owner = (
            isinstance(data, dict)
            and int(data.get("pid", 0)) == os.getpid()
            and data.get("token") == token
        )
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        same_owner = False
    if not same_owner:
        return
    try:
        lock_file.unlink()
    except OSError:
        pass


def _save(data: dict[str, Any]) -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_FILE.with_name(f"{REGISTRY_FILE.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(REGISTRY_FILE)


def register_repo(path: str | os.PathLike[str], alias: str | None = None) -> dict[str, Any]:
    try:
        resolved = Path(path).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        return {"status": "skipped", "reason": "invalid path", "path": str(path)}
    if not _repo_ok(resolved):
        return {"status": "skipped", "reason": "not a repository-like directory", "path": str(resolved)}
    alias_s = str(alias).strip() if alias is not None else resolved.name
    if not alias_s:
        alias_s = resolved.name
    fd = _claim_lock(REGISTRY_LOCK_FILE)
    if fd is None:
        return {"status": "skipped", "reason": "registry lock busy", "path": str(resolved)}
    try:
        data = _load()
        repos = [r for r in data.get("repos", []) if isinstance(r, dict)]
        now = time.time()
        found = False
        for repo in repos:
            if repo.get("path") == str(resolved):
                repo["alias"] = alias_s or str(repo.get("alias") or resolved.name)
                repo["last_seen"] = now
                found = True
                break
        if not found:
            repos.append({"path": str(resolved), "alias": alias_s, "last_seen": now})
        data["repos"] = repos
        _save(data)
        return {"status": "registered", "path": str(resolved), "alias": alias_s}
    finally:
        _release_lock(REGISTRY_LOCK_FILE, fd)


def list_repos() -> list[dict[str, Any]]:
    repos = [r for r in _load().get("repos", []) if isinstance(r, dict)]
    out: list[dict[str, Any]] = []
    for repo in repos:
        try:
            path = Path(str(repo.get("path") or "")).expanduser()
            if _repo_ok(path):
                out.append({
                    "path": str(path.resolve()),
                    "alias": str(repo.get("alias") or path.name),
                    "last_seen": repo.get("last_seen"),
                })
        except (OSError, ValueError, RuntimeError):
            continue
    return out


def write_global_pid(token: str) -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    _write_global_pid_payload(token)


def _write_global_pid_payload(token: str) -> None:
    payload = {
        "pid": os.getpid(),
        "token": token,
        "ts": time.time(),
        "heartbeat_ts": time.time(),
        "script": "auto_watch.py",
    }
    tmp = GLOBAL_PID_FILE.with_name(f"{GLOBAL_PID_FILE.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(json.dumps(payload))
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(GLOBAL_PID_FILE)


def read_global_pid() -> dict[str, Any] | None:
    try:
        if GLOBAL_PID_FILE.is_file():
            data = json.loads(GLOBAL_PID_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        pass
    return None


def global_pid_active(data: dict[str, Any] | None = None, ttl_seconds: float = GLOBAL_PID_TTL_SECONDS) -> bool:
    data = data if data is not None else read_global_pid()
    if not data:
        return False
    try:
        pid = int(data.get("pid", 0))
        heartbeat_ts = float(data.get("heartbeat_ts") or data.get("ts") or 0)
    except (TypeError, ValueError):
        return False
    if data.get("script") != "auto_watch.py":
        return False
    if heartbeat_ts <= 0 or time.time() - heartbeat_ts > ttl_seconds:
        return False
    return _pid_alive(pid)


def claim_global_pid(token: str) -> bool:
    fd = _claim_lock(GLOBAL_PID_LOCK_FILE)
    if fd is None:
        return False
    try:
        data = read_global_pid()
        if data and int(data.get("pid", 0) or 0) != os.getpid():
            if global_pid_active(data):
                return False
        _write_global_pid_payload(token)
        return True
    except (TypeError, ValueError):
        _write_global_pid_payload(token)
        return True
    finally:
        _release_lock(GLOBAL_PID_LOCK_FILE, fd)


def heartbeat_global_pid(token: str) -> bool:
    fd = _claim_lock(GLOBAL_PID_LOCK_FILE, timeout=1.0)
    if fd is None:
        return False
    try:
        data = read_global_pid()
        if not data or int(data.get("pid", 0)) != os.getpid() or data.get("token") != token:
            return False
        _write_global_pid_payload(token)
        return True
    except (TypeError, ValueError):
        return False
    finally:
        _release_lock(GLOBAL_PID_LOCK_FILE, fd)


def clear_global_pid(token: str) -> None:
    fd = _claim_lock(GLOBAL_PID_LOCK_FILE, timeout=1.0)
    if fd is None:
        return
    try:
        data = read_global_pid()
        if data and data.get("pid") == os.getpid() and data.get("token") == token:
            try:
                GLOBAL_PID_FILE.unlink()
            except OSError:
                pass
    finally:
        _release_lock(GLOBAL_PID_LOCK_FILE, fd)
