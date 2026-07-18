"""
Optional OfficeCLI bridge for .docx/.xlsx/.pptx workflows.

The bridge never installs OfficeCLI and never starts watch/resident mode unless
the caller explicitly asks for a mutating action under a profile that permits it.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from runtime_flags import load_feature_flags
from .core import _get_active_workspace

READ_ACTIONS = {"status", "help", "view", "validate", "get", "query", "dump", "plugins"}
MUTATION_ACTIONS = {"create", "set", "add", "remove", "batch", "raw_set", "open", "save", "close", "watch", "unwatch", "goto"}
PROFILE_RANK = {
    "off": 0,
    "light": 1,
    "standard": 2,
    "balanced": 4,
    "4": 4,
    "review": 5,
    "5": 5,
    "heavy": 7,
    "7": 7,
    "max": 9,
}
OFFICE_EXTS = {".docx", ".xlsx", ".pptx"}


def _root(root: str | os.PathLike[str] | None = None) -> Path:
    return Path(root or _get_active_workspace()).expanduser().resolve()


def _profile(root: Path) -> tuple[str, int]:
    flags = load_feature_flags(root)
    profile = str(flags.get("profile") or os.getenv("HARNESS_PROFILE") or "standard").strip().lower()
    return profile, PROFILE_RANK.get(profile, 2)


def _safe_path(root: Path, value: str | None, *, must_exist: bool = False) -> Path | None:
    if not value:
        return None
    text = str(value).strip().strip('"').strip("'")
    if not text or "\x00" in text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = root / path
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    if must_exist and not resolved.exists():
        return None
    return resolved


def _rel_or_abs(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _clip(text: str, limit: int = 12_000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...<truncated {len(text) - limit} chars>"


def _split_command_tail(command: str | None) -> list[str]:
    if not command:
        return []
    try:
        return shlex.split(str(command), posix=os.name != "nt")
    except ValueError:
        return str(command).split()


def _run_officecli(args: list[str], root: Path, *, timeout: int = 120, no_resident: bool = True) -> dict[str, Any]:
    exe = shutil.which("officecli")
    if not exe:
        return {
            "status": "blocked",
            "reason": "officecli not found in PATH",
            "install_hint": "Install manually from iOfficeAI/OfficeCLI, then rerun office_bridge(action='status').",
        }
    env = os.environ.copy()
    if no_resident:
        env["OFFICECLI_NO_AUTO_RESIDENT"] = "1"
    try:
        proc = subprocess.run(
            [exe, *args],
            cwd=str(root),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {"status": "timeout", "command": ["officecli", *args], "timeout": timeout, "stdout": _clip(exc.stdout or ""), "stderr": _clip(exc.stderr or "")}
    except OSError as exc:
        return {"status": "error", "error": type(exc).__name__, "detail": str(exc), "command": ["officecli", *args]}
    return {
        "status": "completed" if proc.returncode == 0 else "failed",
        "command": ["officecli", *args],
        "returncode": proc.returncode,
        "stdout": _clip(proc.stdout),
        "stderr": _clip(proc.stderr),
    }


def _office_files(root: Path, limit: int = 80) -> list[str]:
    out: list[str] = []
    skip_dirs = {".git", ".venv", "venv", "node_modules", ".harness_smoke", ".harness_cache"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".harness")]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() in OFFICE_EXTS:
                out.append(_rel_or_abs(root, path))
                if len(out) >= limit:
                    return sorted(out)
    return sorted(out)


def _mutation_allowed(root: Path, action: str, allow_mutation: bool) -> tuple[bool, str]:
    if action not in MUTATION_ACTIONS:
        return True, "read-only action"
    if not allow_mutation:
        return False, "allow_mutation=true is required for OfficeCLI mutation/watch/resident actions"
    profile, rank = _profile(root)
    if rank <= 0:
        return False, f"profile {profile} is read-only; OfficeCLI mutation/watch/resident actions are blocked"
    return True, f"profile {profile}"


def office_bridge(
    *,
    action: str = "status",
    file: str | None = None,
    mode: str | None = None,
    path: str | None = None,
    selector: str | None = None,
    command: str | None = None,
    output: str | None = None,
    allow_mutation: bool = False,
    timeout: int = 120,
    root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Run guarded OfficeCLI read/validate operations and explicit mutations."""
    workspace = _root(root)
    action = str(action or "status").strip().lower().replace("-", "_")
    profile, rank = _profile(workspace)
    exe = shutil.which("officecli")
    base = {
        "status": "completed",
        "action": action,
        "root": str(workspace),
        "profile": profile,
        "profile_rank": rank,
        "officecli_found": bool(exe),
        "officecli_path": exe or "",
    }
    if action == "status":
        version = _run_officecli(["--version"], workspace, timeout=20) if exe else None
        return {
            **base,
            "version": (version or {}).get("stdout", "").strip() if version else "",
            "office_files": _office_files(workspace),
            "read_actions": sorted(READ_ACTIONS),
            "mutation_actions": sorted(MUTATION_ACTIONS),
            "notes": [
                "Bridge is optional and never installs OfficeCLI.",
                "Read actions use OFFICECLI_NO_AUTO_RESIDENT=1 to avoid background resident sessions.",
                "Mutating/watch/resident actions require allow_mutation=true and profile not off.",
            ],
        }
    if action not in READ_ACTIONS | MUTATION_ACTIONS:
        return {**base, "status": "error", "error": "invalid_argument", "detail": f"action must be one of {sorted(READ_ACTIONS | MUTATION_ACTIONS)}"}

    allowed, reason = _mutation_allowed(workspace, action, allow_mutation)
    if not allowed:
        return {**base, "status": "blocked", "reason": reason}
    if not exe:
        return {**base, "status": "blocked", "reason": "officecli not found in PATH", "install_hint": "Install OfficeCLI manually; this bridge does not auto-install."}

    if action == "help":
        args = ["help"]
        if command:
            args.extend(_split_command_tail(command))
        return {**base, **_run_officecli(args, workspace, timeout=min(timeout, 60))}
    if action == "plugins":
        return {**base, **_run_officecli(["plugins", "list"], workspace, timeout=min(timeout, 60))}

    target = _safe_path(workspace, file, must_exist=action not in {"create"})
    if not target:
        return {**base, "status": "error", "error": "invalid_file", "detail": "file must stay inside workspace and exist for this action"}
    if target.suffix.lower() not in OFFICE_EXTS:
        return {**base, "status": "error", "error": "unsupported_file", "detail": "file must be .docx, .xlsx, or .pptx"}
    rel_target = _rel_or_abs(workspace, target)

    if action == "view":
        view_mode = str(mode or "outline").strip()
        args = ["view", rel_target, view_mode]
        if output:
            out = _safe_path(workspace, output, must_exist=False)
            if not out:
                return {**base, "status": "error", "error": "invalid_output", "detail": "output must stay inside workspace"}
            args.extend(["-o", _rel_or_abs(workspace, out)])
        return {**base, "file": rel_target, **_run_officecli(args, workspace, timeout=timeout)}
    if action == "validate":
        return {**base, "file": rel_target, **_run_officecli(["validate", rel_target], workspace, timeout=timeout)}
    if action == "get":
        return {**base, "file": rel_target, **_run_officecli(["get", rel_target, path or "/", "--json"], workspace, timeout=timeout)}
    if action == "query":
        if not selector:
            return {**base, "status": "error", "error": "invalid_selector", "detail": "selector is required for query"}
        return {**base, "file": rel_target, **_run_officecli(["query", rel_target, selector], workspace, timeout=timeout)}
    if action == "dump":
        args = ["dump", rel_target]
        if path:
            args.append(path)
        if output:
            out = _safe_path(workspace, output, must_exist=False)
            if not out:
                return {**base, "status": "error", "error": "invalid_output", "detail": "output must stay inside workspace"}
            args.extend(["-o", _rel_or_abs(workspace, out)])
        return {**base, "file": rel_target, **_run_officecli(args, workspace, timeout=timeout)}
    if action == "create":
        return {**base, "file": rel_target, **_run_officecli(["create", rel_target], workspace, timeout=timeout, no_resident=False)}

    if not command:
        return {
            **base,
            "status": "blocked",
            "reason": "raw command text is required for this advanced OfficeCLI action",
            "example": "office_bridge(action='set', file='report.docx', command='/body/p[1] --prop bold=true', allow_mutation=true)",
        }
    args = [action.replace("_", "-"), rel_target, *_split_command_tail(command)]
    return {**base, "file": rel_target, **_run_officecli(args, workspace, timeout=timeout, no_resident=action not in {"open", "save", "close", "watch", "unwatch", "goto"})}
