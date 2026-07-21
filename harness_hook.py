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


def _runtime_profile_context(root: Path) -> str:
    try:
        from runtime_flags import load_feature_flags

        flags = load_feature_flags(root)
    except Exception:
        flags = {}
    profile = str(flags.get("profile") or os.getenv("HARNESS_PROFILE") or "standard").strip() or "standard"
    llm = flags.get("llm") if isinstance(flags.get("llm"), dict) else {}
    auto_pilot = flags.get("auto_pilot") if isinstance(flags.get("auto_pilot"), dict) else {}
    auto_watch = flags.get("auto_watch") if isinstance(flags.get("auto_watch"), dict) else {}
    hooks = flags.get("hooks") if isinstance(flags.get("hooks"), dict) else {}
    lessons = flags.get("lessons") if isinstance(flags.get("lessons"), dict) else {}
    finops = flags.get("finops") if isinstance(flags.get("finops"), dict) else {}

    def b(obj: dict, key: str, default: bool = False) -> bool:
        value = obj.get(key, default)
        return bool(value)

    static_llm = bool(flags.get("static_llm", False))
    can_manual_llm = b(llm, "enabled", True)
    auto_mode = str(auto_pilot.get("mode", "safe") or "safe").strip().lower()
    profile_rank = {
        "off": 0, "light": 1, "standard": 2, "balanced": 4, "4": 4,
        "review": 5, "5": 5, "heavy": 7, "7": 7, "max": 9,
    }.get(profile.lower(), 2)
    if profile_rank <= 0 or not can_manual_llm:
        action_line = "Active rule: profile blocks Harness LLM/background work; use static/local checks only and say `profile off đang chặn LLM` when relevant."
    elif profile_rank >= 7:
        action_line = "Active rule: heavy/max profile allows proactive Harness checks; use auto_trigger mode=max for meaningful code batches when appropriate."
    else:
        action_line = f"Active rule: use Harness selectively under this profile; use auto_trigger mode={auto_mode or 'safe'} for post-edit/final checks and do NOT use mode=max unless the current user prompt explicitly asks for max/prod/release or the active profile is heavy/max."

    return (
        "Agent Harness runtime profile snapshot for this prompt:\n"
        f"- profile: {profile}\n"
        f"- llm.enabled: {b(llm, 'enabled', True)}; llm.static: {b(llm, 'static', static_llm)}; static_llm: {static_llm}\n"
        f"- auto_pilot.enabled: {b(auto_pilot, 'enabled', False)}; mode: {auto_pilot.get('mode', 'safe')}; llm: {b(auto_pilot, 'llm', False)}\n"
        f"- auto_watch.enabled: {b(auto_watch, 'enabled', False)}; mode: {auto_watch.get('mode', 'safe')}; llm: {b(auto_watch, 'llm', False)}\n"
        f"- hooks.enabled: {b(hooks, 'enabled', True)}; lessons.enabled: {b(lessons, 'enabled', True)}; finops.enabled: {b(finops, 'enabled', True)}\n"
        "Profile in harness.features.json wins over automatic rules. Do not change profile unless the current user prompt explicitly asks.\n"
        f"{action_line}\n"
        "Mandatory code-turn contract: if this turn edits code in a meaningful batch, run auto_trigger stage=post_edit after edits and stage=final before the final answer, or run panel_review once for the whole batch. Do not wait for the user to ask.\n"
        "For feature/product/UI/UX work, call workflow_router first; if it returns market_research_advisor, prepare a short research brief before coding when the profile permits."
    )


def _post_edit_context(root: Path) -> str:
    return (
        _runtime_profile_context(root)
        + "\n\nPost-edit Harness reminder:\n"
        "- REQUIRED: If this was a meaningful coding edit, run auto_trigger with changed_files/task/stage=post_edit using the active profile's allowed mode; balanced/review use mode=safe.\n"
        "- REQUIRED: Before final answer for code changes, run one final auto_trigger or panel_review for the whole batch unless the user explicitly asked to skip review.\n"
        "- FORBIDDEN: Do not use auto_trigger mode=max under balanced/review/standard unless the current user prompt explicitly asks for max/prod/release.\n"
        "- Never send real .env secrets into panel_review; use secret/config scanners instead."
    )


def _emit_additional_context(parts: list[str], event_name: str = "UserPromptSubmit") -> None:
    body = "\n\n".join(p.strip() for p in parts if p and p.strip())
    if not body:
        return
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": body,
        }
    }, ensure_ascii=True))


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


def _prior_lessons_context(root: Path, prompt: str) -> str:
    if not prompt:
        return ""
    _activate_workspace(root)
    try:
        from tools.core import load_relevant_lessons_context

        ctx = load_relevant_lessons_context(prompt, limit=5)
    except Exception:
        return ""
    if not ctx:
        return ""
    return "Harness prior lessons auto-injected before this prompt:\n" + ctx[:6000]


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
    prompt = _prompt_text(payload)
    if prompt:
        parts = [_runtime_profile_context(root)]
        if not _feature_enabled("HARNESS_HOOKS_ENABLED", True, root):
            _emit_additional_context(parts)
            return 0
        if _feature_enabled("HARNESS_LESSONS_ENABLED", True, root):
            _record_project_seen(root)
            parts.append(_prior_lessons_context(root, prompt))
        _emit_additional_context(parts)
        return 0

    if not _feature_enabled("HARNESS_HOOKS_ENABLED", True, root):
        return 0

    tool = _tool_name(payload)
    if tool in EDIT_TOOLS:
        if _feature_enabled("HARNESS_LESSONS_ENABLED", True, root):
            _record_edit(payload, root, tool)
        _emit_additional_context([_post_edit_context(root)], event_name="PostToolUse")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
