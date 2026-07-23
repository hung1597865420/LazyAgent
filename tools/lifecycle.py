"""Tool lifecycle routing for Agent Harness.

This module is intentionally static: it does not call 9Router and does not
mutate files. Its job is to keep "before code" advisors separate from
"after edit" verification so agents do not discover BA/consult work too late.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from runtime_flags import load_feature_flags
from .core import _get_active_workspace
from .integrations import integration_router, ui_skill_router
from .workflow import workflow_router


LIFECYCLE_PHASES: dict[str, dict[str, Any]] = {
    "session_start": {
        "when": "Start of each prompt/session, before deciding tool usage.",
        "purpose": "Refresh global profile, agent parity, context/tool health.",
        "tools": [
            "policy_profile", "harness_doctor", "adapter_parity_doctor",
            "mcp_inventory", "context_budget", "agent_adapters",
            "install_manifest", "list_agents", "router_quota_status",
            "tool_lifecycle",
        ],
    },
    "orchestration_loop": {
        "when": "When the user wants a multi-step goal managed by harness.",
        "purpose": "Track goal state and decide whether to continue, check, finalize, or ask user.",
        "tools": [
            "goal_runner", "goal_autopilot", "goal_supervisor",
            "goal_runner_control", "run_ledger", "benchmark_runner",
        ],
    },
    "preflight_before_code": {
        "when": "Before planning/reading many files/coding.",
        "purpose": "Clarify product/BA/spec/context/architecture decisions early.",
        "tools": [
            "preflight_trigger", "workflow_router", "integration_router",
            "ui_skill_router", "hallmark_bridge", "speckit_bridge",
            "bug_repro_guard", "graph_minimal_context", "semantic_search",
            "ask_codebase_health", "index_codebase", "ask_codebase", "consult",
            "alt_implementation",
        ],
    },
    "during_implementation": {
        "when": "While coding/debugging, before the batch is considered done.",
        "purpose": "Localize bugs, compare approaches, run isolated experiments.",
        "tools": [
            "suggest_fix", "telemetry_debugger", "swarm_debug", "quick_task",
            "run_single_agent", "run_in_sandbox", "patch_safety_check",
            "profiler", "benchmarker", "wiki_query", "office_bridge",
            "git_archaeologist", "incident_responder",
        ],
    },
    "post_edit_batch": {
        "when": "After a meaningful edit batch, not before coding.",
        "purpose": "Run static/static-first checks on actual changed files. Auto-Watch may only enter here.",
        "tools": [
            "auto_trigger", "scope_creep_detector", "review_context_graph",
            "secret_scanner", "env_parity_checker", "config_security_audit",
            "devops_pipeline", "complexity_analyzer", "coverage_analyzer",
            "dead_code_scanner", "duplicate_code_scanner",
            "incremental_refactor_guard", "dependency_graph_visualizer",
            "migration_validator", "sql_query_analyzer", "openapi_spec_sync",
            "api_contract_tester", "data_flow_taint_analyzer",
            "auth_matrix_auditor", "container_linter",
            "ci_pipeline_validator", "license_scanner", "schema_drift",
            "a11y_auditor", "i18n_auditor", "polyglot_reviewer",
            "performance_regression_detector", "visual_reviewer",
        ],
    },
    "background_watch": {
        "when": "Background file watcher detects a debounced project file change.",
        "purpose": "Register repos and run safe post-edit checks without pre-code advisors or watcher LLM.",
        "tools": [
            "auto_trigger", "scope_creep_detector", "review_context_graph",
            "secret_scanner", "env_parity_checker", "config_security_audit",
            "complexity_analyzer", "harness_trace_viewer",
        ],
    },
    "final_review": {
        "when": "Before reporting completion for a code batch.",
        "purpose": "One final batch review, then fix/verify blockers.",
        "tools": [
            "auto_trigger", "panel_review", "security_autofix",
            "auto_tester", "pr_generator", "doc_sync",
        ],
    },
    "release_gate": {
        "when": "Before deploy/release/production-ready claims.",
        "purpose": "Gate release evidence and hard blockers.",
        "tools": [
            "prod_readiness_gate", "release_orchestrator",
            "provenance_checker", "sbom_generator", "changelog_generator",
            "breaking_change_detector", "dependency_upgrader",
            "flaky_test_detector", "mutation_tester", "load_tester",
            "chaos_tester", "feature_flag_auditor",
        ],
    },
    "memory_docs_ops": {
        "when": "On demand or after relevant artifacts change.",
        "purpose": "Memory/wiki/docs/ledger/FinOps maintenance.",
        "tools": [
            "wiki_ingest", "wiki_lint", "doc_sync", "lesson_curator",
            "finops_stats", "context_auditor", "graph_health",
            "graph_minimal_context",
        ],
    },
}

TOOL_PHASE: dict[str, str] = {
    tool: phase
    for phase, data in LIFECYCLE_PHASES.items()
    for tool in data["tools"]
}

POST_CODE_ONLY = {
    "auto_trigger", "panel_review", "prod_readiness_gate", "visual_reviewer",
    "a11y_auditor", "i18n_auditor", "security_autofix", "auto_tester",
}

WATCHER_ALLOWED_TOOLS = {
    "auto_trigger", "scope_creep_detector", "review_context_graph",
    "secret_scanner", "env_parity_checker", "config_security_audit",
    "complexity_analyzer", "harness_trace_viewer",
}

WATCHER_BLOCKED_TOOLS = {
    "preflight_trigger", "workflow_router", "integration_router", "ui_skill_router",
    "hallmark_bridge", "speckit_bridge", "ask_codebase", "consult",
    "alt_implementation", "panel_review", "prod_readiness_gate",
    "goal_runner", "goal_autopilot", "goal_supervisor", "quick_task",
    "suggest_fix", "swarm_debug", "visual_reviewer",
}

LLM_PREFLIGHT_TOOLS = {"ask_codebase", "consult", "alt_implementation"}

FEATURE_WORDS = {
    "feature", "product", "workflow", "screen", "flow", "module", "api",
    "auth", "dashboard", "upload", "payment", "realtime", "new", "spec",
    "tính năng", "luồng", "màn", "nghiệp vụ", "thiết kế",
}
UI_WORDS = {"ui", "ux", "frontend", "component", "layout", "css", "jsx", "tsx", "screen", "design", "redesign"}
DEBUG_WORDS = {"bug", "debug", "traceback", "exception", "crash", "500", "regression", "lỗi", "fail"}
ARCH_WORDS = {"architecture", "schema", "database", "migration", "concurrency", "cache", "queue", "security", "auth", "api", "rls", "jwt", "permission", "trade-off", "a hay b", "nên"}
RELEASE_WORDS = {"release", "deploy", "production", "prod", "changelog", "tag"}
REFACTOR_WORDS = {"refactor", "rename", "delete", "remove", "dead code", "duplicate", "split", "extract"}


def _norm_files(files: list[str] | tuple[str, ...] | set[str] | str | None) -> list[str]:
    if isinstance(files, str):
        items: Any = [files]
    elif isinstance(files, (list, tuple, set)):
        items = files
    else:
        items = []
    out: list[str] = []
    seen: set[str] = set()
    root = Path(_get_active_workspace()).resolve()
    for item in items:
        if not isinstance(item, str) or not item.strip():
            continue
        raw = item.strip().replace("\\", "/")
        try:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = root / candidate
            resolved = candidate.resolve(strict=False)
            if root != resolved and root not in resolved.parents:
                continue
            rel = resolved.relative_to(root).as_posix()
        except Exception:
            continue
        if rel not in seen:
            seen.add(rel)
            out.append(rel)
    return out


def _has_any(text: str, words: set[str]) -> bool:
    lower = text.lower()
    for word in words:
        needle = str(word or "").strip().lower()
        if not needle:
            continue
        asciiish = bool(re.fullmatch(r"[a-z0-9_][a-z0-9_ -]*[a-z0-9_]", needle) or re.fullmatch(r"[a-z0-9_]", needle))
        if asciiish:
            pattern = r"(?<![a-z0-9])" + re.escape(needle).replace(r"\ ", r"[\s_-]+") + r"(?![a-z0-9])"
            if re.search(pattern, lower):
                return True
        elif needle in lower:
            return True
    return False


def _is_ui(files: list[str], text: str) -> bool:
    return _has_any(text, UI_WORDS) or any(f.lower().endswith((".html", ".css", ".jsx", ".tsx", ".vue", ".svelte", ".astro")) for f in files)


def _features() -> dict[str, Any]:
    data = load_feature_flags(root=_get_active_workspace())
    return data if isinstance(data, dict) else {}


def _profile_snapshot() -> dict[str, Any]:
    flags = _features()
    llm = flags.get("llm") if isinstance(flags.get("llm"), dict) else {}
    return {
        "profile": str(flags.get("profile") or "off"),
        "llm_enabled": bool(llm.get("enabled")),
        "auto_watch_enabled": bool((flags.get("auto_watch") or {}).get("enabled")) if isinstance(flags.get("auto_watch"), dict) else False,
    }


def tool_lifecycle() -> dict[str, Any]:
    """Return the full static lifecycle allocation for all registered tools."""
    return {
        "status": "completed",
        "tool_count": len(TOOL_PHASE),
        "phases": LIFECYCLE_PHASES,
        "tool_phase": TOOL_PHASE,
        "rules": [
            "Preflight tools run before code and may guide the plan.",
            "auto_trigger is post-edit/final verification; it must not be used as the first BA/consult step.",
            "auto_watch may only run background_watch/post_edit_batch safe static checks; it must not run BA/ask_codebase/consult/panel_review/goal_runner.",
            "panel_review is final batch review, not per-file review.",
            "prod_readiness_gate is release/deploy only.",
            "Profile gates always win over lifecycle recommendations.",
        ],
        "watcher_policy": {
            "phase": "background_watch",
            "allowed_tools": sorted(WATCHER_ALLOWED_TOOLS),
            "blocked_tools": sorted(WATCHER_BLOCKED_TOOLS),
            "llm": "blocked unless a future explicit watcher-LLM profile opt-in is added; current default is static-safe only",
            "notes": [
                "Watcher responds to file changes after debounce, so it cannot replace preflight_before_code.",
                "Watcher ignores runtime/temp artifacts and dependency lockfiles are kept watchable.",
                "Watcher should never escalate safe mode to max by itself.",
            ],
        },
    }


def preflight_trigger(
    task: str | None = None,
    changed_files: list[str] | tuple[str, ...] | set[str] | str | None = None,
    diff: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Static pre-code router for BA/context/consult/spec/UI work."""
    files = _norm_files(changed_files)
    text = "\n".join([task or "", diff or "", "\n".join(files)])
    profile = _profile_snapshot()
    workflow = workflow_router(task=task, changed_files=files, diff=diff)
    integration = integration_router(task=task, changed_files=files, diff=diff)
    ui_route = ui_skill_router(task=task, changed_files=files) if _is_ui(files, text) else {"status": "skipped", "reason": "not UI/UX"}

    run_now: list[dict[str, Any]] = []

    def add(tool: str, reason: str, *, args: dict[str, Any] | None = None, required: bool = False, llm: bool = False) -> None:
        blocked = bool(llm and not profile["llm_enabled"])
        run_now.append({
            "tool": tool,
            "phase": TOOL_PHASE.get(tool, "preflight_before_code"),
            "required": required,
            "llm": llm,
            "blocked_by_profile": blocked,
            "reason": reason if not blocked else f"profile {profile['profile']} blocks LLM tool; use static fallback",
            "args": args or {},
        })

    add("workflow_router", "Classify BA/spec/debug/review workflow before planning.", args={"task": task or "", "changed_files": files})
    add("integration_router", "Classify Hallmark/UI Skills/Spec Kit bridges before planning.", args={"task": task or "", "changed_files": files})

    broad_or_multifile = len(files) > 1 or _has_any(text, FEATURE_WORDS | REFACTOR_WORDS)
    if broad_or_multifile:
        add("graph_minimal_context", "Get cheap graph context before expensive codebase Q&A.", args={"changed_files": files}, required=False)
        add("ask_codebase", "Understand cross-file flow before reading/editing many files.", args={"question": task or "Summarize relevant code flow before implementation", "files": files}, required=True, llm=True)
    elif files:
        add("semantic_search", "Single/small-file task: local symbol search is enough before reading exact lines.", args={"query": task or files[0]})

    if _has_any(text, FEATURE_WORDS) or any(route.get("name") == "ba_discovery" for route in workflow.get("routes", [])):
        add("workflow_router", "BA discovery must happen before spec/tickets/code; use returned BA checklist.", args={"task": task or "", "changed_files": files}, required=True)
        add("speckit_bridge", "Read spec state/snapshot before implementing feature workflow.", args={"action": "snapshot", "task": task or ""}, required=False)

    if _is_ui(files, text):
        add("ui_skill_router", "Pick compact UI/UX checklists before UI implementation.", args={"task": task or "", "changed_files": files}, required=True)
        add("hallmark_bridge", "Run UI preflight before touching layout/components.", args={"action": "preflight", "task": task or "", "files": files}, required=True)

    if _has_any(text, ARCH_WORDS):
        add("consult", "Resolve architecture/security/API/schema/concurrency decision before coding.", args={"question": task or "Review implementation approach before coding", "files": files}, required=True, llm=True)

    if _has_any(text, {"module", "component", "function", "reuse", "refactor lớn", "independent"}):
        add("alt_implementation", "Compare two implementation approaches before committing to one.", args={"spec": task or "Compare implementation approaches", "files": files}, required=False, llm=True)

    if _has_any(text, DEBUG_WORDS):
        add("bug_repro_guard", "Require red-capable repro before hypothesis-first fixing.", args={"task": task or "", "changed_files": files, "diff": diff or ""}, required=True)
        add("telemetry_debugger", "Use only when log/stack trace exists and bug localization is needed.", args={"log_content": task or ""}, required=False)

    if _has_any(text, RELEASE_WORDS):
        add("prod_readiness_gate", "Release gates are not pre-code; run after implementation/final checks.", args={"changed_files": files, "task": task or "", "mode": mode or "safe"})

    return {
        "status": "completed",
        "phase": "preflight_before_code",
        "profile": profile,
        "files": files,
        "summary": f"preflight selected {len(run_now)} action(s); run required non-blocked items before coding.",
        "run_now": run_now,
        "workflow_routes": workflow,
        "integration_routes": integration,
        "ui_routes": ui_route,
        "do_not_run_yet": [
            {"tool": tool, "reason": "post-code/final/release phase; run only after edits or before deploy"}
            for tool in sorted(POST_CODE_ONLY)
        ],
        "watcher_note": "auto_watch is background post-edit only; it must not run this preflight plan because the code may already be written by then.",
        "next_phase_after_code": "auto_trigger(stage='post_edit') for changed files, then auto_trigger(stage='final') or panel_review before reporting done.",
    }
