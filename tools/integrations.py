"""
Distilled optional integration routing for Hallmark and Spec Kit.

This module does not vendor either project and does not execute their CLIs.
It gives Agent Harness a cheap, static decision layer that downstream agents
and goal_runner prompts can use without bypassing runtime profiles.
"""
from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from runtime_flags import load_feature_flags
from .core import _get_active_workspace

UI_EXTS = {".html", ".css", ".scss", ".sass", ".less", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".astro"}
DOC_EXTS = {".md", ".mdx", ".txt", ".rst", ".adoc"}
FEATURE_EXTS = UI_EXTS | {".py", ".go", ".rs", ".java", ".kt", ".cs", ".php", ".rb", ".sql", ".yaml", ".yml", ".json", ".toml"}

HALLMARK_TASK_WORDS = {
    "ui", "ux", "frontend", "front-end", "landing", "website", "web page", "homepage", "screen",
    "component", "button", "modal", "card", "dashboard", "redesign", "design", "layout", "responsive",
    "accessibility", "a11y", "visual", "style", "theme", "portfolio",
}
HALLMARK_EXPLICIT_WORDS = {"hallmark", "audit", "redesign", "study"}

SPECKIT_TASK_WORDS = {
    "feature", "project", "new app", "new module", "implement", "build", "spec", "specification",
    "requirements", "plan", "tasks", "roadmap", "architecture", "api", "schema", "auth", "workflow",
    "payment", "realtime", "upload", "dashboard",
}
SMALL_CHANGE_WORDS = {
    "typo", "comment", "format", "rename variable", "small fix", "quick fix", "one line", "docs only",
}

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


def _root(root: str | os.PathLike[str] | None = None) -> Path:
    return Path(root or _get_active_workspace()).expanduser().resolve()


def _norm_files(files: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in files or []:
        if not isinstance(item, str):
            continue
        rel = item.strip().replace("\\", "/")
        if rel and rel not in seen:
            seen.add(rel)
            out.append(rel)
    return out


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _ext(path: str) -> str:
    name = _basename(path)
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _has_any(text: str, words: set[str]) -> bool:
    lower = text.lower()
    return any(word in lower for word in words)


def _profile(root: Path) -> tuple[str, int, bool]:
    flags = load_feature_flags(root)
    profile = str(flags.get("profile") or os.getenv("HARNESS_PROFILE") or "standard").strip().lower()
    rank = PROFILE_RANK.get(profile, 2)
    llm = flags.get("llm", {})
    llm_enabled = bool(llm.get("enabled")) if isinstance(llm, dict) and "enabled" in llm else rank >= 4
    return profile, rank, llm_enabled


def _path_exists(root: Path, rel: str) -> bool:
    try:
        return (root / rel).exists()
    except OSError:
        return False


def _skill_exists(root: Path, name: str) -> bool:
    skill_file = f"{name}/SKILL.md"
    candidates = [
        root / ".agents" / "skills" / skill_file,
        root / ".codex" / "skills" / skill_file,
        root / ".claude" / "skills" / skill_file,
        Path.home() / ".agents" / "skills" / skill_file,
        Path.home() / ".codex" / "skills" / skill_file,
        Path.home() / ".claude" / "skills" / skill_file,
    ]
    return any(path.is_file() for path in candidates)


def _speckit_project_state(root: Path) -> dict[str, Any]:
    skill_globs = [
        ".agents/skills/speckit-*",
        ".claude/skills/speckit-*",
        ".codex/skills/speckit-*",
        ".gemini/commands/speckit*",
        ".claude/commands/speckit*",
    ]
    installed_skills = []
    for pattern in skill_globs:
        installed_skills.extend(str(p.relative_to(root)).replace("\\", "/") for p in root.glob(pattern))
    has_specs = any(_path_exists(root, rel) for rel in ("specs", ".specify", ".speckit"))
    return {
        "cli": bool(shutil.which("specify")),
        "project_initialized": has_specs or bool(installed_skills),
        "installed_artifacts": sorted(installed_skills)[:12],
    }


def _frontend_signal(task: str, files: list[str]) -> bool:
    return bool(any(_ext(f) in UI_EXTS for f in files) or _has_any(task, HALLMARK_TASK_WORDS | HALLMARK_EXPLICIT_WORDS))


def _feature_signal(task: str, files: list[str]) -> bool:
    if _has_any(task, SMALL_CHANGE_WORDS):
        return False
    feature_files = [f for f in files if _ext(f) in FEATURE_EXTS]
    return bool(
        _has_any(task, SPECKIT_TASK_WORDS)
        or len(feature_files) >= 3
        or any(_basename(f) in {"spec.md", "plan.md", "tasks.md", "constitution.md"} for f in files)
    )


def _slug(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text[:60] or "feature"


def _safe_rel_path(root: Path, rel: str) -> Path | None:
    rel = str(rel or "").strip().replace("\\", "/").strip("/")
    if not rel or "\x00" in rel:
        return None
    try:
        path = (root / rel).resolve()
        path.relative_to(root)
    except (OSError, ValueError):
        return None
    return path


def _read_file_excerpt(root: Path, rel: str, limit: int = 20_000) -> str:
    path = _safe_rel_path(root, rel)
    if not path or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _profile_blocks_mutation(root: Path) -> tuple[bool, str]:
    profile, rank, llm_enabled = _profile(root)
    if rank <= 0:
        return True, f"profile {profile} is read-only; mutation actions are blocked"
    return False, f"profile {profile}, llm_enabled={llm_enabled}"


def _write_text_if_changed(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    old = ""
    try:
        old = path.read_text(encoding="utf-8")
    except OSError:
        pass
    if old == text:
        return "unchanged"
    path.write_text(text, encoding="utf-8", newline="\n")
    return "created" if not old else "updated"


def _detect_package_json(root: Path) -> dict[str, Any]:
    text = _read_file_excerpt(root, "package.json", limit=80_000)
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"parse_error": True}
    deps = {}
    for key in ("dependencies", "devDependencies"):
        value = payload.get(key)
        if isinstance(value, dict):
            deps.update(value)
    return {
        "name": payload.get("name"),
        "scripts": sorted((payload.get("scripts") or {}).keys()) if isinstance(payload.get("scripts"), dict) else [],
        "dependencies": sorted(deps.keys())[:120],
    }


def _hallmark_preflight(root: Path, files: list[str], task: str | None) -> dict[str, Any]:
    package = _detect_package_json(root)
    dep_names = set(package.get("dependencies") or [])
    framework = "unknown"
    for name, label in (
        ("next", "nextjs"),
        ("astro", "astro"),
        ("@remix-run/react", "remix"),
        ("vue", "vue"),
        ("svelte", "svelte"),
        ("react", "react"),
    ):
        if name in dep_names:
            framework = label
            break
    motion = sorted(dep_names & {"framer-motion", "motion", "gsap", "lenis", "lottie-react", "@react-spring/web"})
    font_signals = []
    if any(dep.startswith("@fontsource/") for dep in dep_names):
        font_signals.append("@fontsource")
    if "geist" in dep_names or "next" in dep_names:
        font_signals.append("next/font-or-geist-check")
    token_files = [
        rel for rel in ("design.md", "DESIGN.md", "tokens.json", "tailwind.config.js", "tailwind.config.ts", "src/styles/global.css", "app/globals.css")
        if _path_exists(root, rel)
    ]
    scope = "component" if _has_any(task or "", {"button", "input", "modal", "card", "dropdown", "tooltip", "single component"}) else "page"
    if files and len(files) == 1 and _basename(files[0]).lower()[:1].isupper():
        scope = "component"
    return {
        "framework": framework,
        "package_name": package.get("name"),
        "scripts": package.get("scripts", []),
        "font_signals": font_signals,
        "motion_libraries": motion,
        "token_or_design_files": token_files,
        "ui_files": [f for f in files if _ext(f) in UI_EXTS],
        "recommended_scope": scope,
        "must_verify_widths": [320, 375, 414, 768],
        "component_states": ["default", "hover", "focus", "active", "disabled", "loading", "error", "success"],
    }


def hallmark_bridge(
    *,
    action: str = "status",
    task: str | None = None,
    files: list[str] | None = None,
    allow_mutation: bool = False,
    root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Hallmark-compatible static bridge: status, preflight, audit_plan, write_preflight."""
    workspace = _root(root)
    action = str(action or "status").strip().lower().replace("-", "_")
    norm_files = _norm_files(files)
    route = integration_router(task=task, changed_files=norm_files, root=workspace)
    preflight = _hallmark_preflight(workspace, norm_files, task)
    installed = route["routes"]["hallmark"]["installed"]
    base = {
        "status": "completed",
        "action": action,
        "installed": installed,
        "profile": route["profile"],
        "triggered": route["routes"]["hallmark"]["triggered"],
        "route_status": route["routes"]["hallmark"]["status"],
        "preflight": preflight,
        "invocation_hint": "Use Hallmark skill verbs if installed: default, hallmark audit, hallmark redesign, hallmark study.",
    }
    if action == "status":
        return base
    if action == "preflight":
        return {**base, "hallmark_flow": route["routes"]["hallmark"]["distilled_rules"]}
    if action == "audit_plan":
        return {
            **base,
            "audit_plan": [
                "Scan existing design tokens, framework, font stack, and motion libraries before edits.",
                "Check component/page scope and preserve route/content ownership.",
                "Review WCAG, contrast, keyboard flow, form labels, focus-visible, and reduced motion.",
                "Flag AI-slop UI: fake chrome, invented metrics, generic card grids, one-note palettes, nested cards, weak mobile.",
                "After implementation, run a11y_auditor; if app URL exists, run visual_reviewer.",
            ],
            "handoff_tools": ["a11y_auditor", "visual_reviewer"],
        }
    if action == "write_preflight":
        if not allow_mutation:
            return {**base, "status": "blocked", "reason": "allow_mutation=true is required"}
        blocked, reason = _profile_blocks_mutation(workspace)
        if blocked:
            return {**base, "status": "blocked", "reason": reason}
        path = workspace / ".hallmark" / "preflight.json"
        payload = {**preflight, "task": task or "", "updated_at": int(time.time()), "source": "agent-harness hallmark_bridge"}
        write_status = _write_text_if_changed(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return {**base, "status": write_status, "path": str(path)}
    return {"error": "invalid_argument", "detail": "action must be status, preflight, audit_plan, or write_preflight"}


def _speckit_files(root: Path) -> list[str]:
    patterns = [
        "specs/**/*.md",
        ".specify/**/*.md",
        ".speckit/**/*.md",
        ".agents/skills/speckit-*/SKILL.md",
        ".claude/commands/speckit*.md",
        ".gemini/commands/speckit*.md",
    ]
    out: list[str] = []
    for pattern in patterns:
        for path in root.glob(pattern):
            try:
                out.append(str(path.relative_to(root)).replace("\\", "/"))
            except ValueError:
                continue
    return sorted(dict.fromkeys(out))[:80]


def _speckit_template(feature: str, task: str | None) -> dict[str, str]:
    title = re.sub(r"\s+", " ", (feature or task or "feature").strip())[:100] or "feature"
    slug = _slug(title)
    spec = f"""# Feature Specification: {title}

## User Story
{task or "Describe the user-visible behavior and outcome."}

## Requirements
- [ ] Define primary user flow and success state.
- [ ] Define inputs, outputs, permissions, and error states.
- [ ] Define non-goals and out-of-scope behavior.

## Acceptance Criteria
- [ ] Main flow works end to end.
- [ ] Edge cases and failure states are handled.
- [ ] Tests or verification steps cover the behavior.
"""
    plan = f"""# Implementation Plan: {title}

## Technical Approach
- [ ] Identify touched modules and existing patterns.
- [ ] Keep changes scoped to the feature contract.
- [ ] Add migrations/API/schema changes only when required.

## Verification
- [ ] Run focused tests.
- [ ] Run Agent Harness auto_trigger after edits.
"""
    tasks = f"""# Tasks: {title}

- [ ] Read existing implementation and constraints.
- [ ] Update spec/plan if discovery changes the contract.
- [ ] Implement the smallest coherent slice.
- [ ] Add or update focused tests/checks.
- [ ] Run final harness checks and summarize.
"""
    return {f"specs/{slug}/spec.md": spec, f"specs/{slug}/plan.md": plan, f"specs/{slug}/tasks.md": tasks}


def speckit_bridge(
    *,
    action: str = "status",
    task: str | None = None,
    feature: str | None = None,
    integration: str = "codex",
    allow_mutation: bool = False,
    root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Spec Kit bridge: status/snapshot plus guarded init/scaffold actions."""
    workspace = _root(root)
    action = str(action or "status").strip().lower().replace("-", "_")
    integration = str(integration or "codex").strip().lower()
    state = _speckit_project_state(workspace)
    route = integration_router(task=task or feature, changed_files=[], root=workspace)
    files = _speckit_files(workspace)
    base = {
        "status": "completed",
        "action": action,
        "profile": route["profile"],
        "route_status": route["routes"]["speckit"]["status"],
        "cli_available": state["cli"],
        "project_initialized": state["project_initialized"],
        "files": files,
        "supported_integrations": ["claude", "codex", "gemini", "agy"],
    }
    if action == "status":
        return base
    if action == "snapshot":
        excerpts = {rel: _read_file_excerpt(workspace, rel, limit=8_000) for rel in files[:12]}
        return {**base, "excerpts": excerpts}
    if action == "init":
        if not allow_mutation:
            return {**base, "status": "blocked", "reason": "allow_mutation=true is required"}
        blocked, reason = _profile_blocks_mutation(workspace)
        if blocked:
            return {**base, "status": "blocked", "reason": reason}
        if integration not in {"claude", "codex", "gemini", "agy"}:
            return {**base, "status": "blocked", "reason": "integration must be claude, codex, gemini, or agy"}
        if not shutil.which("specify"):
            return {**base, "status": "blocked", "reason": "specify CLI not found", "install_hint": "uv tool install specify-cli"}
        cmd = ["specify", "init", "--here", "--integration", integration]
        try:
            proc = subprocess.run(cmd, cwd=str(workspace), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {**base, "status": "error", "error": type(exc).__name__, "detail": str(exc)}
        return {
            **base,
            "status": "completed" if proc.returncode == 0 else "failed",
            "command": cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-4000:],
            "post_files": _speckit_files(workspace),
        }
    if action == "scaffold":
        if not allow_mutation:
            return {**base, "status": "blocked", "reason": "allow_mutation=true is required"}
        blocked, reason = _profile_blocks_mutation(workspace)
        if blocked:
            return {**base, "status": "blocked", "reason": reason}
        created: dict[str, str] = {}
        for rel, text in _speckit_template(feature or task or "feature", task).items():
            path = _safe_rel_path(workspace, rel)
            if not path:
                continue
            created[rel] = _write_text_if_changed(path, text)
        return {**base, "status": "completed", "written": created, "post_files": _speckit_files(workspace)}
    return {"error": "invalid_argument", "detail": "action must be status, snapshot, init, or scaffold"}


def integration_router(
    *,
    task: str | None = None,
    changed_files: list[str] | None = None,
    diff: str | None = None,
    root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Return static routing guidance for distilled Hallmark and Spec Kit flows."""
    workspace = _root(root)
    files = _norm_files(changed_files)
    text = "\n".join([task or "", diff or "", "\n".join(files)])
    profile, rank, llm_enabled = _profile(workspace)
    frontend = _frontend_signal(text, files)
    feature = _feature_signal(text, files)
    speckit = _speckit_project_state(workspace)
    hallmark_installed = _skill_exists(workspace, "hallmark")
    blocked = rank <= 0 or not llm_enabled

    hallmark_status = "not_triggered"
    if frontend:
        hallmark_status = "blocked_by_profile" if blocked else "route_to_agent"
    speckit_status = "not_triggered"
    if feature:
        speckit_status = "blocked_by_profile" if blocked else "route_to_spec_first"
        if not speckit["project_initialized"]:
            speckit_status = "needs_project_init" if not blocked else "blocked_by_profile"

    return {
        "status": "completed",
        "profile": profile,
        "llm_enabled": llm_enabled,
        "files": files,
        "routes": {
            "hallmark": {
                "status": hallmark_status,
                "triggered": frontend,
                "installed": hallmark_installed,
                "caller": "active coding agent or goal_runner agent prompt",
                "distilled_rules": [
                    "Run a design pre-flight before UI edits: framework, tokens, font stack, motion, spacing.",
                    "Route component-sized tasks separately from full-page tasks.",
                    "Preserve existing routes/content ownership; redesign only the visual/interaction layer unless user approves deletions.",
                    "No invented metrics, fake UI chrome, negative letter spacing, or unverified mobile layouts.",
                    "For components, cover default, hover, focus, active, disabled, loading, error, and success states.",
                ],
            },
            "speckit": {
                "status": speckit_status,
                "triggered": feature,
                "cli_available": speckit["cli"],
                "project_initialized": speckit["project_initialized"],
                "installed_artifacts": speckit["installed_artifacts"],
                "caller": "goal_runner for direct automation; active coding agent for client-side automation",
                "recommended_slug": _slug(task or "feature"),
                "distilled_flow": [
                    "For new features/projects, create or update a lightweight specification before coding.",
                    "Then derive technical plan and task checklist; implementation follows tasks, not a loose prompt.",
                    "If Spec Kit is installed, prefer its specify/plan/tasks/implement commands or skills.",
                    "If Spec Kit is not initialized, do not mutate the repo under profile off; initialize only under an allowed profile/user-selected setup.",
                    "Harness remains responsible for profile gating, checks, lessons, FinOps, and final review.",
                ],
            },
        },
    }


def agent_guidance_for_task(task: str | None, changed_files: list[str] | None = None, root: str | os.PathLike[str] | None = None) -> str:
    """Return a compact prompt block for goal_runner external agents."""
    route = integration_router(task=task, changed_files=changed_files, root=root)
    blocks: list[str] = []
    hallmark = route["routes"]["hallmark"]
    if hallmark["triggered"]:
        blocks.append(
            "Hallmark-distilled UI flow:\n"
            "- Call hallmark_bridge(action='preflight') when available to get cached/static design signals.\n"
            "- Before UI edits, scan existing design signals and preserve tokens/fonts/routes.\n"
            "- Choose component scope vs page scope; component work must include all 8 interaction states.\n"
            "- Avoid invented metrics, fake chrome, generic hero rhythm, and unverified mobile layouts.\n"
            "- If the Hallmark skill is installed, use it; otherwise apply these distilled gates directly."
        )
    speckit = route["routes"]["speckit"]
    if speckit["triggered"]:
        if speckit["project_initialized"]:
            spec_line = "Use existing Spec Kit artifacts/commands if present before implementation."
        else:
            spec_line = "Spec Kit is not initialized here; create a minimal local spec/plan/tasks note before coding unless blocked by profile."
        blocks.append(
            "Spec Kit-distilled feature flow:\n"
            "- Call speckit_bridge(action='status' or 'snapshot') when available before feature planning.\n"
            f"- {spec_line}\n"
            "- Write/update specification, then plan, then tasks; implement against those tasks.\n"
            "- Keep Harness as the review/check/profile/lesson layer after code changes."
        )
    if not blocks:
        return ""
    return "Distilled optional integration guidance:\n\n" + "\n\n".join(blocks)
