"""
Static workflow routers distilled from mattpocock/skills.

These helpers do not call LLMs and do not mutate files. They give the active
agent a cheap way to choose the right workflow before spending model budget.
"""
from __future__ import annotations

import re
from typing import Any


DEBUG_WORDS = {
    "bug", "debug", "diagnose", "crash", "exception", "traceback", "stack trace",
    "fail", "failing", "failed", "timeout", "slow", "regression", "500", "lỗi",
}
FEATURE_WORDS = {
    "feature", "build", "implement", "new module", "new api", "schema", "auth",
    "workflow", "dashboard", "payment", "upload", "realtime", "project", "múc",
}
CREATE_WORDS = {
    "build", "implement", "create", "develop", "scaffold", "new", "add",
    "múc", "làm", "xây", "xây dựng", "thêm",
}
BA_WORDS = {
    "business analyst", "requirement", "requirements", "stakeholder", "persona",
    "actor", "user story", "use case", "acceptance criteria", "business process",
    "business rule", "workflow mới", "feature mới", "project mới", "sản phẩm",
}
AMBIGUITY_WORDS = {"unclear", "ambiguous", "mơ hồ", "chưa rõ", "làm rõ", "scope", "phạm vi"}
REVIEW_WORDS = {"review", "audit", "check", "kiểm", "đánh giá"}
DOC_WORDS = {"doc", "docs", "documentation", "readme", "agents.md", "policy", "chú thích", "tài liệu"}
MAINTENANCE_WORDS = {"fix", "update", "cleanup", "refactor", "test", "sửa", "cập nhật", "dọn"}
ARCH_WORDS = {"architecture", "refactor", "module", "interface", "seam", "adapter", "dependency", "coupling"}
DOMAIN_WORDS = {"domain", "glossary", "adr", "context.md", "term", "terminology", "business rule"}
TDD_WORDS = {"tdd", "test-first", "red-green", "regression test", "seam test"}
UX_WORDS = {
    "ui", "ux", "frontend", "front-end", "design", "redesign", "layout", "screen",
    "component", "landing", "homepage", "dashboard", "modal", "form", "usability",
    "user flow", "interaction", "microcopy", "visual", "responsive",
}
RESEARCH_WORDS = {
    "research", "market", "competitor", "benchmark", "best practice", "pattern",
    "người ta làm", "thị trường", "đối thủ", "tham khảo", "soi", "học cách",
}
UI_ITERATION_WORDS = {"redesign", "fix", "update", "polish", "cleanup", "layout", "ui", "ux", "visual", "responsive", "sửa", "cập nhật"}
NEW_FEATURE_WORDS = {"new", "build", "implement", "create", "develop", "scaffold", "project", "new app", "new module", "new api", "múc", "xây", "xây dựng"}
BA_DONE_WORDS = {"ba discovery is complete", "requirements finalized", "prd approved", "requirements approved", "move to design", "move to build", "ba xong", "đã chốt requirement"}
EXISTING_RESEARCH_WORDS = {"already-approved", "already approved", "existing research", "approved market research", "from the doc", "based on research", "research đã có", "đã research"}
UI_EXTS = {".html", ".css", ".scss", ".sass", ".less", ".jsx", ".tsx", ".vue", ".svelte", ".astro"}
CODE_EXTS = UI_EXTS | {".py", ".js", ".ts", ".go", ".rs", ".java", ".kt", ".cs", ".php", ".rb", ".sql"}
DOC_EXTS = {".md", ".mdx", ".rst", ".txt"}


def _norm_files(files: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in files or []:
        if not isinstance(item, str):
            continue
        rel = item.strip().replace("\\", "/")
        if rel and rel not in seen:
            seen.add(rel)
            out.append(rel)
    return out


def _ext(path: str) -> str:
    name = str(path or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return "." + name.rsplit(".", 1)[-1] if "." in name else ""


def _has_any(text: str, words: set[str]) -> bool:
    lower = str(text or "").lower()
    return any(word in lower for word in words)


def _is_doc_file(path: str) -> bool:
    lower = str(path or "").replace("\\", "/").lower()
    return _ext(lower) in DOC_EXTS or lower.endswith(("readme.md", "agents.md", "claude.md", "gemini.md")) or "/docs/" in lower


def _is_test_file(path: str) -> bool:
    lower = str(path or "").replace("\\", "/").lower()
    name = lower.rsplit("/", 1)[-1]
    return (
        "/test/" in lower
        or "/tests/" in lower
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", ".test.js", ".spec.js"))
    )


def _requests_doc_only(text: str) -> bool:
    return bool(re.search(r"(?i)\b(update|add|write|fix|cập nhật|sửa|thêm)\s+(docs?|documentation|readme|agents\.md|policy|tài liệu)\b", text or ""))


def _requests_tests_only(text: str) -> bool:
    return bool(re.search(r"(?i)\b(add|write|update|fix|cập nhật|sửa|thêm)\s+[^.;:\n]{0,60}\btests?\b|\btests?\s+for\b", text or ""))


def _looks_big(files: list[str], diff: str | None, task: str | None) -> bool:
    code_files = [f for f in files if _ext(f) in CODE_EXTS]
    return len(code_files) >= 3 or len(str(diff or "")) > 12_000 or _has_any(task or "", {"large", "big", "nhiều file", "full", "toàn bộ"})


def workflow_router(
    *,
    task: str | None = None,
    changed_files: list[str] | None = None,
    diff: str | None = None,
) -> dict[str, Any]:
    """Return static workflow guidance for feature/debug/review/domain/TDD work."""
    files = _norm_files(changed_files)
    text = "\n".join([task or "", diff or "", "\n".join(files)])
    ui_files = [f for f in files if _ext(f) in UI_EXTS]
    ux_signal = bool(ui_files) or _has_any(text, UX_WORDS)
    big = _looks_big(files, diff, task)
    debug_intent = _has_any(text, DEBUG_WORDS)
    review_intent = _has_any(text, REVIEW_WORDS)
    feature_signal = _has_any(text, FEATURE_WORDS)
    create_signal = _has_any(text, CREATE_WORDS)
    ba_done = _has_any(text, BA_DONE_WORDS)
    explicit_ba_signal = _has_any(text, BA_WORDS | AMBIGUITY_WORDS) and not ba_done
    doc_only = bool(files) and all(_is_doc_file(f) for f in files)
    test_only = bool(files) and all(_is_test_file(f) for f in files)
    doc_maintenance = (doc_only or _requests_doc_only(text)) and _has_any(text, DOC_WORDS | MAINTENANCE_WORDS) and not explicit_ba_signal
    test_maintenance = (test_only or _requests_tests_only(text)) and _has_any(text, MAINTENANCE_WORDS | TDD_WORDS) and not explicit_ba_signal
    review_only = review_intent and not create_signal and not explicit_ba_signal
    ui_iteration = ux_signal and _has_any(text, UI_ITERATION_WORDS) and not _has_any(text, NEW_FEATURE_WORDS) and not explicit_ba_signal
    ba_blocked = debug_intent or review_only or doc_maintenance or test_maintenance or ui_iteration
    planning_signal = ((feature_signal and create_signal) or big) and not ba_blocked
    ba_signal = (explicit_ba_signal or (planning_signal and not ba_done)) and not ba_blocked
    existing_research_context = _has_any(text, EXISTING_RESEARCH_WORDS) and _has_any(text, UI_ITERATION_WORDS)
    explicit_research_request = _has_any(text, RESEARCH_WORDS) and not existing_research_context
    research_signal = (
        (ux_signal and not existing_research_context)
        or planning_signal
        or explicit_ba_signal
        or explicit_research_request
    ) and not (debug_intent or review_only or doc_maintenance or test_maintenance)
    routes: list[dict[str, Any]] = []

    def add(name: str, priority: str, reason: str, steps: list[str], artifacts: list[str] | None = None) -> None:
        routes.append({
            "name": name,
            "priority": priority,
            "reason": reason,
            "steps": steps,
            "artifacts": artifacts or [],
        })

    if debug_intent:
        add(
            "bug_repro_guard",
            "P0",
            "Debug/bug signal detected; avoid hypothesis-first fixing.",
            [
                "Build one red-capable command: focused test, curl script, CLI fixture, or replay harness.",
                "Run it once and capture the exact failing symptom.",
                "Minimize the repro until every remaining input/config/step is load-bearing.",
                "List 3-5 falsifiable hypotheses, then instrument one variable at a time.",
                "Fix, add/keep the regression test at the public seam, rerun the original repro.",
            ],
            ["repro_command", "hypotheses", "regression_test"],
        )

    if ba_signal:
        add(
            "ba_discovery",
            "P0",
            "Feature/product/workflow work needs business analysis before spec and implementation.",
            [
                "Capture the business goal, success metric, stakeholders, actors, and primary user journeys.",
                "Separate must-have requirements from nice-to-have requests and explicitly list out-of-scope items.",
                "Write acceptance criteria as observable Given/When/Then or checklist outcomes.",
                "Name business rules, edge cases, permissions, data ownership, and non-functional constraints.",
                "Mark open questions and assumptions before handing the work to spec_first or implementation.",
            ],
            ["ba_brief", "actors", "journeys", "acceptance_criteria", "open_questions"],
        )

    if planning_signal:
        if research_signal:
            add(
                "market_research_advisor",
                "P0",
                "Feature/UI/UX work should get outside-market and competitor pattern research before coding.",
                [
                    "Research 3-5 comparable products, docs, pattern galleries, or UX case studies that solve the same user job.",
                    "Capture what they optimize for: acquisition, activation, speed, trust, accessibility, retention, admin control, or support cost.",
                    "Extract reusable patterns: IA, primary flow, empty/loading/error states, permission model, onboarding, pricing/upgrade, analytics, and microcopy.",
                    "Record trade-offs and anti-patterns; do not copy branding, screenshots, proprietary content, or exact UI composition.",
                    "Hand the main coding agent a short brief: sources checked, patterns to borrow, risks to avoid, and acceptance criteria to update.",
                ],
                ["market_scan", "competitor_patterns", "ux_research_brief", "borrow_avoid_list"],
            )

    if research_signal and not planning_signal:
        add(
            "market_research_advisor",
            "P0",
            "UI/UX work should get outside-market and competitor pattern research before coding.",
            [
                "Research 3-5 comparable products, docs, pattern galleries, or UX case studies that solve the same user job.",
                "Capture what they optimize for: activation, speed, trust, accessibility, retention, admin control, or support cost.",
                "Extract reusable patterns for flow, state coverage, hierarchy, interaction feedback, visual system, and microcopy.",
                "Record trade-offs and anti-patterns; do not copy branding, screenshots, proprietary content, or exact UI composition.",
                "Hand the main coding agent a short brief: sources checked, patterns to borrow, risks to avoid, and design acceptance criteria.",
            ],
            ["market_scan", "competitor_patterns", "ux_research_brief", "borrow_avoid_list"],
        )

    if planning_signal:
        add(
            "spec_first",
            "P1",
            "Feature or multi-file work should be shaped before implementation.",
            [
                "Write/update a compact spec: problem, user-visible solution, requirements, out-of-scope.",
                "Declare test seams before coding.",
                "If the work is larger than one context window, split into vertical tracer-bullet tickets.",
                "Use expand-contract for wide refactors that cannot land as vertical slices.",
            ],
            ["spec.md", "plan.md", "tasks.md"],
        )

    if review_intent:
        add(
            "code_review_axes",
            "P1",
            "Review request detected.",
            [
                "Separate Standards findings from Spec findings.",
                "Use documented repo standards first; apply smell baseline as judgement-call findings.",
                "Do not merge/rerank the two axes until the user decides trade-offs.",
            ],
            ["standards_report", "spec_report"],
        )

    if big:
        add(
            "wayfinder",
            "P1",
            "Large/foggy work needs decision tickets instead of one huge implementation prompt.",
            [
                "Name the destination in one or two lines.",
                "List open decisions as frontier tickets; keep unclear future areas in fog.",
                "Resolve one decision per session and record the answer once.",
                "Move ruled-out work to out-of-scope so future agents do not rediscover it.",
            ],
            ["decision_map", "frontier", "out_of_scope"],
        )

    if not (review_only or doc_maintenance or test_maintenance) and (
        _has_any(text, DOMAIN_WORDS) or _has_any(text, {"schema", "auth", "billing", "order", "customer"})
    ):
        add(
            "domain_context_guard",
            "P1",
            "Domain terms or hard-to-reverse decisions are involved.",
            [
                "Read CONTEXT.md if present; challenge conflicting terms.",
                "Create/update CONTEXT.md only for stable glossary terms, not implementation notes.",
                "Create ADR only when the decision is hard to reverse, surprising, and has real alternatives.",
                "Cross-check user statements against source code before recording domain truth.",
            ],
            ["CONTEXT.md", "docs/adr/*.md"],
        )

    if _has_any(text, ARCH_WORDS) or (_has_any(text, {"refactor", "clean architecture"}) and len(files) >= 2):
        add(
            "architecture_deepening",
            "P2",
            "Architecture/refactor signal detected.",
            [
                "Use vocabulary: module, interface, seam, adapter, depth, locality, leverage.",
                "Apply the deletion test: if deleting a module only moves complexity to callers, it is shallow.",
                "Do not introduce a seam for one adapter; two real adapters make a real seam.",
                "Prefer testing through the public interface instead of private internals.",
            ],
            ["deepening_candidates", "deletion_test"],
        )

    if _has_any(text, TDD_WORDS) or _has_any(text, {"regression", "test"}):
        add(
            "tdd_seam_guard",
            "P2",
            "Testing signal detected.",
            [
                "Write tests through public seams, not private internals.",
                "Avoid tautological assertions that recompute the implementation.",
                "Use one red-green slice at a time; refactor after the behavior is green.",
            ],
            ["test_seams", "focused_tests"],
        )

    if ux_signal and not doc_maintenance:
        add(
            "ui_ux_advisor",
            "P0",
            "UI/UX work needs a product-and-design advisor before implementation and after visual changes.",
            [
                "Anchor the change to one user job, target audience, success metric, and priority trade-off.",
                "Check the primary flow for first-time-user clarity, decision points, empty/loading/error states, and mobile constraints.",
                "Critique hierarchy, information scent, microcopy, affordance, spacing rhythm, typography, color semantics, and interaction feedback.",
                "Compare against existing product patterns before adding a new component or visual language.",
                "After implementation, pair static critique with a11y_auditor and visual_reviewer when a real URL or screenshot exists.",
            ],
            ["ux_advice", "flow_risks", "visual_craft_notes", "state_coverage"],
        )

    if ui_files:
        add(
            "ui_skill_router",
            "P0",
            "UI files changed; route through compact UI skills before broad visual review.",
            [
                "Select at most three UI checks: baseline, accessibility, motion, metadata, or visual.",
                "Run Hallmark preflight before major UI edits and a11y/visual review after implementation.",
            ],
            ["ui_skill_route"],
        )

    if not routes:
        add(
            "simple_static_work",
            "P0",
            "No heavyweight workflow signal detected.",
            [
                "Keep scope tight.",
                "Use local static checks and focused tests only when they match the change.",
            ],
            [],
        )

    return {
        "status": "completed",
        "task": task or "",
        "files": files,
        "routes": routes,
        "recommended": routes[0]["name"],
        "profile_note": "Static router only; respects harness profile and does not call LLM.",
    }


def bug_repro_guard(
    *,
    task: str | None = None,
    error_log: str | None = None,
    changed_files: list[str] | None = None,
    commands: list[str] | None = None,
    test_output: str | None = None,
    diff: str | None = None,
) -> dict[str, Any]:
    """Check whether a debug task has a red-capable feedback loop."""
    files = _norm_files(changed_files)
    text = "\n".join([task or "", error_log or "", test_output or "", diff or "", "\n".join(files)])
    debug_signal = _has_any(text, DEBUG_WORDS)
    command_text = "\n".join(str(c or "") for c in commands or [])
    repro_patterns = (
        r"(?i)\b(pytest|npm test|pnpm test|yarn test|go test|cargo test|mvn test|gradle test)\b",
        r"(?i)\b(curl|httpie|playwright|puppeteer|vitest|jest|pytest)\b",
        r"(?i)\b(repro|regression|failing test|red-capable)\b",
    )
    has_command = bool(command_text.strip() and any(re.search(p, command_text) for p in repro_patterns))
    has_red_output = bool(re.search(r"(?i)\b(fail|failed|failure|assert|exception|traceback|500|red)\b", test_output or ""))
    if not debug_signal:
        verdict = "not_applicable"
    elif has_command and has_red_output:
        verdict = "ready_to_debug"
    elif has_command:
        verdict = "needs_red_output"
    else:
        verdict = "needs_repro"
    return {
        "status": "completed",
        "verdict": verdict,
        "debug_signal": debug_signal,
        "has_repro_command": has_command,
        "has_red_output": has_red_output,
        "required_before_fix": [
            "Name one command that exercises the user's exact symptom.",
            "Make the command deterministic or raise the reproduction rate for flaky bugs.",
            "Capture output showing the symptom before applying the fix.",
            "Turn the minimized repro into a regression test when a correct public seam exists.",
        ],
        "hypothesis_template": [
            "If <cause A> is true, then <probe/change> will make the symptom disappear or change.",
            "If <cause B> is true, then <specific observation> should appear at <boundary>.",
            "If <cause C> is true, then old config/data/version should pass while current fails.",
        ],
        "debug_log_prefix": "[DEBUG-harness]",
    }
