"""
Global runtime feature flags for Agent Harness.

This intentionally controls only non-secret runtime/background behaviour. Model
keys, router credentials, and deployment names still come from env/config.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

CONTROL_FILE = "harness.features.json"
HARNESS_ROOT = Path(__file__).resolve().parent
GLOBAL_CONTROL_DIR = Path.home() / ".agent-harness"
TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
FALSE_VALUES = {"0", "false", "no", "off", "disabled"}

_PATHS: dict[str, tuple[tuple[str, ...], ...]] = {
    "HARNESS_LLM_ENABLED": (("llm", "enabled"), ("llm_enabled",)),
    "HARNESS_FINOPS_ENABLED": (("finops", "enabled"), ("manual_features", "finops", "enabled"), ("finops_enabled",)),
    "HARNESS_HOOKS_ENABLED": (("hooks", "enabled"), ("manual_features", "hooks", "enabled"), ("hooks_enabled",)),
    "HARNESS_LESSONS_ENABLED": (("lessons", "enabled"), ("manual_features", "lessons", "enabled"), ("lessons_enabled",)),
    "HARNESS_AUTO_WATCH": (("auto_watch", "enabled"), ("auto_watch_enabled",)),
    "HARNESS_AUTO_WATCH_MODE": (("auto_watch", "mode"), ("auto_watch_mode",)),
    "HARNESS_AUTO_WATCH_LLM": (("auto_watch", "llm"), ("auto_watch_llm",)),
    "HARNESS_AUTO_WATCH_INTERVAL": (("auto_watch", "interval"), ("auto_watch_interval",)),
    "HARNESS_AUTO_WATCH_DEBOUNCE": (("auto_watch", "debounce"), ("auto_watch_debounce",)),
    "HARNESS_AUTO_PILOT": (("auto_pilot", "enabled"), ("auto_pilot_enabled",)),
    "HARNESS_AUTO_MODE": (("auto_pilot", "mode"), ("auto_mode",)),
    "HARNESS_AUTO_LLM": (("auto_pilot", "llm"), ("auto_llm",)),
    "HARNESS_STATIC_LLM": (("static_llm",), ("llm", "static")),
    "HARNESS_WIKI_ENABLED": (("wiki", "enabled"), ("manual_features", "llmwiki", "enabled"), ("wiki_enabled",)),
    "HARNESS_CODE_INDEX_ENABLED": (("code_index", "enabled"), ("manual_features", "code_index", "enabled"), ("code_index_enabled",)),
    "HARNESS_DASHBOARD_ENABLED": (("dashboard", "enabled"), ("manual_features", "dashboard", "enabled"), ("dashboard_enabled",)),
}


def _metadata_workspace() -> str:
    meta = os.getenv("ANTIGRAVITY_SOURCE_METADATA")
    if not meta:
        return ""
    try:
        return str(json.loads(meta).get("tool", {}).get("workspacePath") or "").strip()
    except Exception:
        return ""


def active_workspace_root(default: str | os.PathLike[str] | None = None) -> Path:
    if default is not None:
        return Path(str(default)).expanduser().resolve()
    root = (
        os.getenv("HARNESS_WATCH_ROOT")
        or os.getenv("CLAUDE_PROJECT_DIR")
        or _metadata_workspace()
        or os.getenv("WORKSPACE_ROOT")
        or str(default or HARNESS_ROOT)
    )
    return Path(str(root)).expanduser().resolve()


def control_file_paths(root: str | os.PathLike[str] | None = None) -> list[Path]:
    explicit = os.getenv("HARNESS_FEATURES_FILE")
    if explicit and _parse_bool(os.getenv("HARNESS_ALLOW_FEATURE_FILE_OVERRIDE")) is True:
        return [Path(explicit).expanduser()]
    paths: list[Path] = []
    paths.append(GLOBAL_CONTROL_DIR / CONTROL_FILE)

    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        try:
            resolved = str(path.resolve())
        except OSError:
            resolved = str(path.absolute())
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def load_feature_flags(root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    for path in control_file_paths(root):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def _lookup(data: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> Any:
    for parts in paths:
        current: Any = data
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                break
            current = current[part]
        else:
            return current
    return None


def raw_flag(env_name: str, default: Any = None, *, root: str | os.PathLike[str] | None = None) -> Any:
    value = _lookup(load_feature_flags(root), _PATHS.get(env_name, ()))
    if value is not None:
        return value
    return os.getenv(env_name, default)


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


def bool_flag(env_name: str, default: bool = False, *, root: str | os.PathLike[str] | None = None) -> bool:
    parsed = _parse_bool(raw_flag(env_name, None, root=root))
    return default if parsed is None else parsed


def bool_env_string(env_name: str, default: bool = False, *, root: str | os.PathLike[str] | None = None) -> str:
    return "1" if bool_flag(env_name, default, root=root) else "0"


def choice_flag(
    env_name: str,
    default: str,
    choices: set[str],
    *,
    root: str | os.PathLike[str] | None = None,
) -> str:
    raw = raw_flag(env_name, default, root=root)
    value = str(raw).strip().lower()
    return value if value in choices else default


def float_flag(
    env_name: str,
    default: float,
    min_value: float,
    max_value: float | None = None,
    *,
    root: str | os.PathLike[str] | None = None,
) -> float:
    raw = raw_flag(env_name, default, root=root)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value
