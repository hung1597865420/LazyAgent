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
REVIEW_WORDS = {"review", "audit", "check", "kiểm", "đánh giá"}
ARCH_WORDS = {"architecture", "refactor", "module", "interface", "seam", "adapter", "dependency", "coupling"}
DOMAIN_WORDS = {"domain", "glossary", "adr", "context.md", "term", "terminology", "business rule"}
TDD_WORDS = {"tdd", "test-first", "red-green", "regression test", "seam test"}
UI_EXTS = {".html", ".css", ".scss", ".sass", ".less", ".jsx", ".tsx", ".vue", ".svelte", ".astro"}
CODE_EXTS = UI_EXTS | {".py", ".js", ".ts", ".go", ".rs", ".java", ".kt", ".cs", ".php", ".rb", ".sql"}


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
    big = _looks_big(files, diff, task)
    routes: list[dict[str, Any]] = []

    def add(name: str, priority: str, reason: str, steps: list[str], artifacts: list[str] | None = None) -> None:
        routes.append({
            "name": name,
            "priority": priority,
            "reason": reason,
            "steps": steps,
            "artifacts": artifacts or [],
        })

    if _has_any(text, DEBUG_WORDS):
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

    if _has_any(text, FEATURE_WORDS) or big:
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

    if _has_any(text, DOMAIN_WORDS) or _has_any(text, {"schema", "auth", "billing", "order", "customer"}):
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

    if _has_any(text, REVIEW_WORDS):
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
