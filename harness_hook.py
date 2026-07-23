"""Client hook bridge for Agent Harness.

Hooks run outside MCP, so this file is deliberately best-effort: it must never
block prompt submission or editing. It gives lesson memory a client-side path
that does not depend on goal_runner, auto_trigger, or any MCP tool being called.
"""
from __future__ import annotations

import json
import os
import sys
import hashlib
import threading
from contextlib import contextmanager
from pathlib import Path

from tools.workspace_context import workspace_scope


EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
_WORKSPACE_ENV_LOCK = threading.RLock()


def _clean_text(value: object) -> str:
    text = str(value or "")
    return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _payload() -> dict:
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _project_dir(payload: dict) -> Path:
    candidates = (
        payload.get("cwd")
        or "",
        os.getenv("HARNESS_ACTIVE_WORKSPACE") or "",
        os.getenv("WORKSPACE_ROOT") or "",
        os.getenv("CLAUDE_PROJECT_DIR") or "",
        os.getcwd(),
    )
    for root in candidates:
        if not str(root or "").strip():
            continue
        try:
            path = Path(str(root)).expanduser().resolve()
            if path.is_dir() and _trusted_workspace_candidate(path):
                return path
        except (OSError, RuntimeError, ValueError):
            continue
    return Path.cwd().resolve()


def _trusted_workspace_candidate(path: Path) -> bool:
    try:
        resolved = path.resolve()
        cwd = Path.cwd().resolve()
        if cwd.parent == cwd:
            return resolved == cwd
        return resolved == cwd or cwd in resolved.parents
    except (OSError, RuntimeError, ValueError):
        return False


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
            return _clean_text(value).strip()
    return ""


def _relative_file(root: Path, raw: str) -> str:
    path = Path(str(raw or "")).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve().relative_to(root).as_posix()
    except Exception:
        return path.name or "<unknown>"


@contextmanager
def _workspace_env(root: Path):
    """Scope workspace for the entire hook lifecycle without mutating process env."""
    with _WORKSPACE_ENV_LOCK:
        with workspace_scope(root):
            yield


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


def _summarize_preflight(root: Path, prompt: str) -> tuple[str, dict]:
    if not prompt:
        return "", {}
    try:
        from tools.lifecycle import preflight_trigger

        preflight = preflight_trigger(task=prompt, changed_files=[], mode="safe")
    except Exception as exc:
        return f"Harness pre-code lifecycle snapshot failed: {type(exc).__name__}: {exc}", {}
    run_now = [item for item in preflight.get("run_now", []) if isinstance(item, dict)]
    required = [item for item in run_now if item.get("required") and not item.get("blocked_by_profile")]
    blocked = [item for item in run_now if item.get("blocked_by_profile")]
    workflow_routes = preflight.get("workflow_routes", {})
    route_names = [
        str(route.get("name"))
        for route in workflow_routes.get("routes", [])
        if isinstance(route, dict) and route.get("name")
    ]

    lines = [
        "Harness pre-code lifecycle snapshot for this prompt (static hook result, no 9Router call):",
        f"- phase: {preflight.get('phase', 'preflight_before_code')}",
        f"- workflow_routes: {', '.join(route_names[:8]) or 'none'}",
    ]
    if required:
        lines.append("- REQUIRED before coding:")
        for item in required[:8]:
            tool = item.get("tool")
            reason = str(item.get("reason") or "").strip()
            args = item.get("args") if isinstance(item.get("args"), dict) else {}
            arg_hint = ""
            if tool in {"ask_codebase", "consult", "alt_implementation"}:
                arg_hint = f" args={json.dumps(args, ensure_ascii=False)[:500]}"
            lines.append(f"  - {tool}: {reason[:240]}{arg_hint}")
    else:
        lines.append("- REQUIRED before coding: none selected; keep this prompt static/local unless code changes become meaningful.")
    if blocked:
        lines.append("- Blocked by current profile:")
        for item in blocked[:5]:
            lines.append(f"  - {item.get('tool')}: {item.get('reason')}")
    if any(name in {"ba_discovery", "market_research_advisor", "spec_first", "wayfinder"} for name in route_names):
        lines.append("- BA/Spec note: use the workflow route steps as the BA checklist before implementation; do not wait for auto_trigger to discover this after code.")
    lines.append("- Forbidden phase mix-up: auto_trigger is post-edit/final only; it must not replace this pre-code lifecycle.")
    return "\n".join(lines), preflight


def _prompt_blocks_goal_init(prompt: str) -> bool:
    text = " ".join(str(prompt or "").lower().split())
    explicit_state_blockers = (
        "không tạo goal",
        "khong tao goal",
        "đừng tạo goal",
        "dung tao goal",
        "không ghi state",
        "khong ghi state",
        "đừng ghi state",
        "dung ghi state",
        "do not create goal",
        "do not write state",
    )
    read_only_blockers = (
        "không sửa code",
        "khong sua code",
        "không đổi code",
        "khong doi code",
        "không thay đổi code",
        "khong thay doi code",
        "không code",
        "khong code",
        "không tạo plan",
        "khong tao plan",
        "chỉ kiểm tra",
        "chi kiem tra",
        "chỉ check",
        "chi check",
        "check thôi",
        "check thoi",
        "chỉ xem",
        "chi xem",
        "do not edit files",
        "do not edit anything",
        "no code changes",
        "no edits",
        "status only",
        "check only",
        "final check only",
        "read-only",
    )
    scoped_no_edit = (
        "không sửa file",
        "khong sua file",
        "do not edit ",
    )
    edit_intents = (
        "implement",
        "fix",
        "add ",
        "update ",
        "change ",
        "refactor",
        "write ",
        "create ",
        "sửa ",
        "sua ",
        "thêm ",
        "them ",
        "làm ",
        "lam ",
        "code",
    )
    if any(blocker in text for blocker in explicit_state_blockers):
        return True
    if any(blocker in text for blocker in read_only_blockers):
        return True
    if any(blocker in text for blocker in scoped_no_edit):
        return not any(intent in text for intent in edit_intents)
    return False


def _goal_lifecycle_context(root: Path, prompt: str, preflight: dict) -> str:
    if not prompt:
        return ""
    profile = str((preflight.get("profile") or {}).get("profile") or "").lower()
    if profile == "off":
        return "Harness goal lifecycle: profile off blocks automatic goal init; use static checklist only."
    if _prompt_blocks_goal_init(prompt):
        return "Harness goal lifecycle: prompt requested read-only/no state; static goal auto-init skipped."
    run_now = [item for item in preflight.get("run_now", []) if isinstance(item, dict)]
    required_tools = {str(item.get("tool")) for item in run_now if item.get("required") and not item.get("blocked_by_profile")}
    workflow_routes = preflight.get("workflow_routes", {})
    route_names = {
        str(route.get("name"))
        for route in workflow_routes.get("routes", [])
        if isinstance(route, dict) and route.get("name")
    }
    text = prompt.lower()
    big_signal = (
        len(prompt) >= 80
        or bool(required_tools & {"ask_codebase", "consult", "ui_skill_router", "hallmark_bridge"})
        or bool(route_names & {"ba_discovery", "market_research_advisor", "spec_first", "wayfinder"})
        or any(word in text for word in ("tính năng", "feature", "workflow", "nhiều bước", "plan", "kế hoạch", "lớn", "full"))
    )
    if not big_signal:
        return "Harness goal lifecycle: no multi-step goal auto-init needed for this prompt."
    try:
        from tools.goal import init_static_goal

        result = init_static_goal(
            prompt,
            context="Hook auto-init from UserPromptSubmit so post-edit auto_trigger has an active goal.",
            source="client_hook",
        )
    except Exception as exc:
        return f"Harness goal lifecycle auto-init failed: {type(exc).__name__}: {exc}"
    status = result.get("status")
    goal_id = result.get("goal_id")
    current = result.get("current_part") or prompt[:160]
    if status == "conflict_active_goal":
        return (
            "Harness goal lifecycle for this prompt:\n"
            f"- status: {status}; existing_goal_id: {goal_id}\n"
            f"- existing_current_part: {str(current)[:260]}\n"
            "- REQUIRED before coding: resolve/finish the existing active goal or ask the user before binding this prompt to it.\n"
            "- FORBIDDEN: do not claim this new prompt is covered by the old active goal."
        )
    return (
        "Harness goal lifecycle for this prompt:\n"
        f"- status: {status}; goal_id: {goal_id}\n"
        f"- current_part: {str(current)[:260]}\n"
        "- REQUIRED after edits: run auto_trigger(stage=post_edit), then goal_supervisor(last_checks=..., changed_files=..., diff=...).\n"
        "- REQUIRED before final answer: goal_supervisor must allow run_final/complete; do not claim done only because auto_trigger returned a blob."
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
    event_id = str(payload.get("tool_use_id") or payload.get("id") or payload.get("event_id") or "")
    if not event_id:
        stable = json.dumps(tool_input, ensure_ascii=False, sort_keys=True, default=str)
        event_id = hashlib.sha256(stable.encode("utf-8", errors="replace")).hexdigest()[:16]
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
            "lesson_key": f"client_hook:edit:{tool}:{rel}:{event_id}",
        })
    except Exception:
        pass


def main() -> int:
    _configure_stdout()
    payload = _payload()
    root = _project_dir(payload)
    prompt = _prompt_text(payload)
    if prompt:
        with _workspace_env(root):
            parts = [_runtime_profile_context(root)]
            if not _feature_enabled("HARNESS_HOOKS_ENABLED", True, root):
                _emit_additional_context(parts)
                return 0
            preflight_context, preflight = _summarize_preflight(root, prompt)
            parts.append(preflight_context)
            parts.append(_goal_lifecycle_context(root, prompt, preflight))
            if _feature_enabled("HARNESS_LESSONS_ENABLED", True, root):
                _record_project_seen(root)
                parts.append(_prior_lessons_context(root, prompt))
            _emit_additional_context(parts)
            return 0

    with _workspace_env(root):
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
