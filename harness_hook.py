"""Client hook bridge for Agent Harness.

Hooks run outside MCP, so this file is deliberately best-effort: it must never
block prompt submission or editing. It gives lesson memory a client-side path
that does not depend on goal_runner, auto_trigger, or any MCP tool being called.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def _payload() -> dict:
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _project_dir(payload: dict) -> Path:
    root = (
        os.getenv("CLAUDE_PROJECT_DIR")
        or os.getenv("WORKSPACE_ROOT")
        or payload.get("cwd")
        or os.getcwd()
    )
    return Path(str(root)).resolve()


def _tool_name(payload: dict) -> str:
    for key in ("tool_name", "tool", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _prompt_text(payload: dict) -> str:
    for key in ("prompt", "user_prompt", "message", "input"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _relative_file(root: Path, raw: str) -> str:
    path = Path(str(raw or "")).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve().relative_to(root).as_posix()
    except Exception:
        return path.name or "<unknown>"


def _activate_workspace(root: Path) -> None:
    os.environ["WORKSPACE_ROOT"] = str(root)
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)


def _feature_enabled(name: str, default: bool, root: Path) -> bool:
    try:
        from runtime_flags import bool_flag

        return bool_flag(name, default, root=root)
    except Exception:
        return default


def _record_project_seen(root: Path) -> None:
    _activate_workspace(root)
    try:
        from tools.core import append_lesson

        append_lesson({
            "source": "client_hook",
            "lesson_type": "project_seen",
            "title": "Harness lesson memory active",
            "outcome": "observed",
            "summary": "Client prompt hook initialized lesson memory for this project.",
            "tags": ["client_hook", "prompt", "lesson_memory"],
            "lesson_key": "client_hook:project_seen",
        })
    except Exception:
        pass


def _inject_prior_lessons(root: Path, prompt: str) -> None:
    if not prompt:
        return
    _activate_workspace(root)
    try:
        from tools.core import load_relevant_lessons_context

        ctx = load_relevant_lessons_context(prompt, limit=5)
    except Exception:
        return
    if not ctx:
        return
    msg = "Harness prior lessons auto-injected before this prompt:\n" + ctx[:6000]
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": msg,
        }
    }, ensure_ascii=False))


def _record_edit(payload: dict, root: Path, tool: str) -> None:
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    rel = _relative_file(root, str(tool_input.get("file_path") or tool_input.get("notebook_path") or ""))
    _activate_workspace(root)
    try:
        from tools.core import append_lesson

        append_lesson({
            "source": "client_hook",
            "lesson_type": "edit_event",
            "title": f"{tool} {rel}",
            "outcome": "observed",
            "summary": "Client hook observed a file edit in this project. Use run_ledger or prior lessons to trace recent work.",
            "files": [rel],
            "tags": ["client_hook", "edit_event", tool.lower()],
        })
    except Exception:
        pass


def main() -> int:
    payload = _payload()
    root = _project_dir(payload)
    if not _feature_enabled("HARNESS_HOOKS_ENABLED", True, root):
        return 0
    prompt = _prompt_text(payload)
    if prompt:
        if _feature_enabled("HARNESS_LESSONS_ENABLED", True, root):
            _record_project_seen(root)
            _inject_prior_lessons(root, prompt)
        return 0

    tool = _tool_name(payload)
    if tool in EDIT_TOOLS and _feature_enabled("HARNESS_LESSONS_ENABLED", True, root):
        _record_edit(payload, root, tool)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
