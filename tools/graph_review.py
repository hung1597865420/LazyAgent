"""CRG-inspired static graph review helpers.

This module deliberately reuses the existing harness codebase index instead of
vendoring code-review-graph. It gives review tools a cheap local pre-pass:
changed symbols, blast radius, test gaps, risk score, graph health, and rough
context savings.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from config import WORKSPACE_ROOT

_CODE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".go",
    ".rs", ".cs", ".php", ".rb", ".swift", ".kt", ".kts", ".sql", ".html",
    ".css", ".vue", ".svelte", ".astro",
}
_CONFIG_EXTS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env"}
_REVIEW_NAMES = {
    ".env", ".env.local", ".env.production", ".env.development", ".env.test",
    ".env.example", "dockerfile", "docker-compose.yml", "compose.yml",
}
_REVIEW_EXTS = _CODE_EXTS | _CONFIG_EXTS
_SECURITY_WORDS = {
    "auth", "jwt", "token", "secret", "password", "credential", "session",
    "cookie", "csrf", "cors", "crypto", "encrypt", "decrypt", "permission",
    "role", "admin", "login", "oauth", "apikey", "api_key",
}


def _root() -> Path:
    return Path(os.getenv("WORKSPACE_ROOT") or WORKSPACE_ROOT).resolve()


def _rel(path: str | Path, root: Path) -> str:
    p = Path(path)
    try:
        if p.is_absolute():
            return p.resolve().relative_to(root).as_posix()
        return p.as_posix()
    except Exception:
        return str(path).replace("\\", "/")


def _safe_files(files: list[str] | None, root: Path) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in files or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        rel = _rel(raw.strip(), root).strip("/")
        candidate = (root / rel).resolve()
        try:
            if root != candidate and root not in candidate.parents:
                continue
        except Exception:
            continue
        name = Path(rel).name.lower()
        if Path(rel).suffix.lower() not in _REVIEW_EXTS and name not in _REVIEW_NAMES:
            continue
        if rel not in seen:
            seen.add(rel)
            out.append(rel)
    return out


def _git(args: list[str], root: Path, timeout: int = 15) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _git_changed_files(root: Path, base: str) -> list[str]:
    files: list[str] = []
    diff = _git(["diff", "--name-only", base, "--"], root)
    if diff and diff.returncode == 0:
        files.extend(x.strip() for x in diff.stdout.splitlines() if x.strip())
    status = _git(["status", "--porcelain"], root)
    if status and status.returncode == 0:
        for line in status.stdout.splitlines():
            if len(line) >= 4:
                files.append(line[3:].strip())
    return _safe_files(files, root)


def _parse_diff_ranges(root: Path, base: str) -> dict[str, list[tuple[int, int]]]:
    diff = _git(["diff", "--unified=0", base, "--"], root)
    if not diff or diff.returncode != 0:
        return {}
    current: str | None = None
    ranges: dict[str, list[tuple[int, int]]] = {}
    file_re = re.compile(r"^\+\+\+ b/(.+)$")
    hunk_re = re.compile(r"^@@ .+? \+(\d+)(?:,(\d+))? @@")
    for line in diff.stdout.splitlines():
        fm = file_re.match(line)
        if fm:
            current = fm.group(1)
            continue
        hm = hunk_re.match(line)
        if hm and current:
            start = int(hm.group(1))
            count = int(hm.group(2) or "1")
            end = start if count == 0 else start + count - 1
            ranges.setdefault(current, []).append((start, end))
    return ranges


def _estimate_tokens(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    return max(1, (len(text) + 3) // 4) if text else 0


def _estimate_file_tokens(root: Path, files: list[str]) -> int:
    total = 0
    for rel in files:
        path = root / rel
        try:
            if path.is_file():
                total += max(1, (path.stat().st_size + 3) // 4)
        except OSError:
            pass
    return total


def _attach_savings(result: dict[str, Any], root: Path, files: list[str]) -> dict[str, Any]:
    baseline = _estimate_file_tokens(root, files)
    returned = _estimate_tokens(result)
    if baseline > 0:
        saved = max(0, baseline - returned)
        result["context_savings"] = {
            "estimated": True,
            "baseline_tokens": baseline,
            "graph_context_tokens": returned,
            "saved_tokens": saved,
            "saved_percent": round(saved * 100 / baseline) if baseline else 0,
        }
    return result


def _bare_symbols(symbol: str) -> list[str]:
    symbol = str(symbol or "").strip()
    if not symbol:
        return []
    parts = [symbol]
    if "." in symbol:
        parts.append(symbol.rsplit(".", 1)[-1])
    return list(dict.fromkeys(parts))


def _is_test_item(item: dict[str, Any]) -> bool:
    path = str(item.get("path") or "").replace("\\", "/").lower()
    name = str(item.get("symbol") or item.get("owner_symbol") or "").lower()
    base = path.rsplit("/", 1)[-1]
    return (
        base.startswith("test_")
        or base.endswith(("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))
        or "/tests/" in f"/{path}"
        or name.startswith("test")
        or "spec" in name
    )


def _is_code_item(item: dict[str, Any]) -> bool:
    path = str(item.get("path") or "").replace("\\", "/")
    return Path(path).suffix.lower() in _CODE_EXTS


def _file_symbol(rel: str) -> dict[str, Any]:
    suffix = Path(rel).suffix.lower()
    name = Path(rel).name.lower()
    language = "env" if name.startswith(".env") else suffix.lstrip(".") or "text"
    return {
        "path": rel,
        "symbol": rel,
        "kind": "file",
        "language": language,
        "line": 1,
        "end_line": 1,
        "signature": f"file {rel}",
        "score": 1.0,
        "snippet": "",
    }


def _symbol_risk(symbol: dict[str, Any], refs: list[dict[str, Any]], test_refs: list[dict[str, Any]]) -> float:
    score = 0.05
    inbound_files = {r.get("path") for r in refs if r.get("path") and r.get("path") != symbol.get("path")}
    score += min(len(refs) * 0.03, 0.25)
    score += min(len(inbound_files) * 0.05, 0.20)
    if symbol.get("kind") in {"class", "function", "async_function"} and not test_refs and not _is_test_item(symbol):
        score += 0.25
    text = " ".join(str(symbol.get(k) or "") for k in ("path", "symbol", "signature", "snippet")).lower()
    if any(word in text for word in _SECURITY_WORDS):
        score += 0.20
    path = str(symbol.get("path") or "").lower()
    name = Path(path).name
    if name.startswith(".env"):
        score += 0.30
    elif path.endswith((".sql", ".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ".conf")):
        score += 0.15
    return round(min(score, 1.0), 4)


async def review_context_graph(
    changed_files: list[str] | None = None,
    base: str = "HEAD~1",
    detail_level: str = "standard",
    max_callers_per_symbol: int = 25,
) -> dict:
    """Static review pre-pass: changed symbols, blast radius, test gaps, risk."""
    root = _root()
    from .codebase_index import get_index

    idx = get_index(str(root))
    idx.build(force=False)
    files = _safe_files(changed_files, root) if changed_files else _git_changed_files(root, base)
    if not files:
        return {
            "status": "ok",
            "summary": "No changed code files detected.",
            "changed_files": [],
            "risk_score": 0.0,
            "risk": "low",
            "warnings": [],
        }

    diff_ranges = _parse_diff_ranges(root, base)
    changed_symbols: list[dict[str, Any]] = []
    impacted_refs: list[dict[str, Any]] = []
    test_gaps: list[dict[str, Any]] = []
    priorities: list[dict[str, Any]] = []
    seen_symbols: set[tuple[str, str]] = set()
    seen_refs: set[tuple[str, str, int, str]] = set()

    for rel in files:
        symbols = idx.get_changed_symbols(rel, diff_ranges.get(rel))
        if not symbols:
            symbols = idx.get_symbols(rel)
        if not symbols:
            symbols = [_file_symbol(rel)]
        for sym in symbols:
            key = (str(sym.get("path") or rel), str(sym.get("symbol") or ""))
            if key in seen_symbols or not key[1]:
                continue
            seen_symbols.add(key)
            refs: list[dict[str, Any]] = []
            tests: list[dict[str, Any]] = []
            for name in _bare_symbols(key[1]):
                refs.extend(idx.get_refs_to(name, limit=max_callers_per_symbol))
            for ref in refs:
                rkey = (
                    str(ref.get("path") or ""),
                    str(ref.get("owner_symbol") or ""),
                    int(ref.get("line") or 0),
                    str(ref.get("kind") or ""),
                )
                if rkey not in seen_refs and ref.get("path") not in files:
                    seen_refs.add(rkey)
                    impacted_refs.append(ref)
                if _is_test_item(ref):
                    tests.append(ref)
            risk_score = _symbol_risk(sym, refs, tests)
            item = {**sym, "risk_score": risk_score, "caller_count": len(refs), "test_ref_count": len(tests)}
            changed_symbols.append(item)
            if not tests and sym.get("kind") in {"function", "async_function", "class"} and not _is_test_item(sym):
                test_gaps.append({
                    "path": sym.get("path"),
                    "symbol": sym.get("symbol"),
                    "line": sym.get("line"),
                    "reason": "No test-like caller/reference found in local index.",
                })
            priorities.append({
                "path": sym.get("path"),
                "symbol": sym.get("symbol"),
                "line": sym.get("line"),
                "risk_score": risk_score,
                "reason": "security/test/blast-radius weighted static score",
            })

    priorities.sort(key=lambda x: (-float(x.get("risk_score") or 0), str(x.get("path") or "")))
    impacted_files = sorted({str(r.get("path")) for r in impacted_refs if r.get("path")})
    overall = max((float(x.get("risk_score") or 0) for x in priorities), default=0.0)
    risk = "high" if overall >= 0.70 else "medium" if overall >= 0.40 else "low"
    result: dict[str, Any] = {
        "status": "ok",
        "summary": (
            f"Graph review: {len(files)} changed file(s), {len(changed_symbols)} changed symbol(s), "
            f"{len(impacted_files)} impacted file(s), {len(test_gaps)} test gap(s), risk={risk} ({overall:.2f})."
        ),
        "changed_files": files,
        "risk": risk,
        "risk_score": round(overall, 4),
        "changed_symbol_count": len(changed_symbols),
        "impacted_file_count": len(impacted_files),
        "test_gap_count": len(test_gaps),
        "review_priorities": priorities[:10],
        "warnings": [],
    }
    if detail_level != "minimal":
        result.update({
            "changed_symbols": changed_symbols[:100],
            "impacted_refs": impacted_refs[:200],
            "impacted_files": impacted_files[:100],
            "test_gaps": test_gaps[:100],
            "graph_stats": idx.graph_stats(),
        })
    return _attach_savings(result, root, files)


async def graph_health(limit: int = 10) -> dict:
    """Return architecture hotspots and graph knowledge gaps."""
    root = _root()
    from .codebase_index import get_index

    idx = get_index(str(root))
    idx.build(force=False)
    limit = max(1, min(int(limit), 50))
    hubs = idx.hub_nodes(limit=limit)
    bridges = idx.bridge_nodes(limit=limit)
    dead = [item for item in idx.find_dead_code() if _is_code_item(item)][:limit]
    untested_hotspots = [
        h for h in hubs
        if _is_code_item(h) and h.get("kind") in {"function", "class", "async_function"} and not _is_test_item(h)
    ][:limit]
    language_counts = idx.graph_stats().get("languages", {})
    dominant = [name for name, _count in Counter(language_counts).most_common(3)]
    suggestions = [
        "Run review_context_graph before panel_review on multi-file code changes.",
        "Inspect bridge_nodes before large refactors; they are likely architectural chokepoints.",
        "Prioritize tests for untested_hotspots with high inbound degree.",
    ]
    return {
        "status": "ok",
        "summary": f"Graph health: {len(hubs)} hub(s), {len(bridges)} bridge node(s), {len(dead)} dead-code candidate(s).",
        "hubs": hubs,
        "bridge_nodes": bridges,
        "knowledge_gaps": {
            "dead_code_candidates": dead,
            "untested_hotspots": untested_hotspots,
            "dominant_languages": dominant,
        },
        "suggested_questions": suggestions,
        "warnings": [],
    }


async def graph_minimal_context(task: str = "", changed_files: list[str] | None = None, base: str = "HEAD~1") -> dict:
    """Ultra-compact graph context for agents before expensive review/search."""
    review = await review_context_graph(changed_files=changed_files, base=base, detail_level="minimal")
    task_lower = (task or "").lower()
    if any(x in task_lower for x in ("review", "pr", "merge", "diff")):
        next_tools = ["review_context_graph", "panel_review"]
    elif any(x in task_lower for x in ("refactor", "rename", "cleanup")):
        next_tools = ["graph_health", "dead_code_scanner", "dependency_graph_visualizer"]
    elif any(x in task_lower for x in ("debug", "bug", "error")):
        next_tools = ["semantic_search", "review_context_graph", "suggest_fix"]
    else:
        next_tools = ["semantic_search", "graph_health"]
    return {
        "status": review.get("status", "ok"),
        "summary": review.get("summary", ""),
        "risk": review.get("risk"),
        "risk_score": review.get("risk_score"),
        "key_entities": [
            p.get("symbol") for p in review.get("review_priorities", [])[:5]
            if p.get("symbol")
        ],
        "next_tool_suggestions": next_tools,
        "context_savings": review.get("context_savings"),
        "warnings": review.get("warnings", []),
    }
