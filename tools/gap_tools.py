"""
Static-first autonomy gap tools.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from agents import AgentRole
from .core import _get_active_workspace, _git_diff, _llm_analyze, _parse_json_object, _run_cmd_safe

_SKIP_DIRS = {
    ".git", ".harness_cache", ".harness_smoke", ".harness_worktree", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "__pycache__", "node_modules", "venv", ".venv",
}
_CODE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".cs", ".rb", ".php"}
_SECRET_RE = re.compile(r"(?i)(api[_-]?key|authorization|password|secret|token)\s*[:=]\s*['\"]?[^'\"\s,;]+")


def _root() -> Path:
    return Path(_get_active_workspace()).resolve()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(_root()).as_posix()
    except Exception:
        return path.as_posix()


def _read(path: Path, limit: int = 120_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _iter_files(files: list[str] | None = None, exts: set[str] | None = None, limit: int = 250) -> list[Path]:
    root = _root()
    out: list[Path] = []
    if files:
        for item in files:
            if not isinstance(item, str) or not item.strip():
                continue
            path = (root / item).resolve()
            try:
                if root != path and root not in path.parents:
                    continue
            except RuntimeError:
                continue
            if path.is_file() and (not exts or path.suffix.lower() in exts):
                out.append(path)
        return out[:limit]
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".harness_worktree")]
        for name in filenames:
            path = Path(dirpath) / name
            if exts and path.suffix.lower() not in exts:
                continue
            out.append(path)
            if len(out) >= limit:
                return out
    return out


def _redact(text: str) -> str:
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}=<redacted>", text)


def _finding(file: str, category: str, severity: str, issue: str, fix: str = "") -> dict[str, Any]:
    return {"file": file, "category": category, "severity": severity, "issue": issue, "fix": fix}


def _llm_enabled(mode: str | None = None) -> bool:
    if (mode or "").strip().lower() == "max":
        return True
    return os.getenv("HARNESS_STATIC_LLM", "").strip().lower() in {"1", "true", "yes", "on"}


async def _azure_enrich(tool: str, result: dict[str, Any], role: AgentRole, mode: str | None = None) -> dict[str, Any]:
    if not _llm_enabled(mode):
        result["llm_analysis"] = {"summary": "Azure enrichment skipped. Use mode=max or HARNESS_STATIC_LLM=1."}
        return result
    prompt = (
        f"You are the Agent Harness {tool} Azure reviewer. Triage the static JSON result below. "
        "Return strict JSON with keys: verdict_adjustment, risk_summary, priority_actions, false_positive_notes. "
        "Do not include secrets; treat redacted values as redacted."
    )
    context = json.dumps(result, ensure_ascii=False, default=str)[:80_000]
    try:
        raw = await asyncio.wait_for(_llm_analyze(prompt, context, role=role), timeout=45)
        parsed = _parse_json_object(raw) or {"summary": raw[:1000]}
        result["llm_analysis"] = parsed
    except Exception as exc:
        result["llm_analysis"] = {"warning": f"Azure enrichment failed: {exc}"}
    return result


async def release_orchestrator(
    changed_files: list[str] | None = None,
    diff: str | None = None,
    context: str | None = None,
    mode: str = "safe",
) -> dict[str, Any]:
    """Coordinate pre-release evidence and return a hard release verdict."""
    root = _root()
    findings: list[dict[str, Any]] = []
    warnings: list[str] = []
    rc_branch, branch, err_branch = _run_cmd_safe(["git", "branch", "--show-current"], cwd=str(root))
    rc_head, head, err_head = _run_cmd_safe(["git", "rev-parse", "--short", "HEAD"], cwd=str(root))
    rc_status, status, _ = _run_cmd_safe(["git", "status", "--porcelain"], cwd=str(root))
    rc_tag, tag, _ = _run_cmd_safe(["git", "describe", "--tags", "--abbrev=0"], cwd=str(root))

    if rc_branch != 0:
        warnings.append(err_branch or "git branch unavailable")
    if rc_head != 0:
        findings.append(_finding("git", "NO_COMMIT", "high", err_head or "Cannot resolve HEAD"))
    if rc_status == 0 and status.strip():
        dirty = [line for line in status.splitlines() if line.strip()]
        non_artifact = [line for line in dirty if not any(x in line for x in ("REVIEW_REPORT.md", ".harness_"))]
        if non_artifact:
            findings.append(_finding("git", "DIRTY_WORKTREE", "high", f"{len(non_artifact)} non-artifact changes are uncommitted"))

    changelog_paths = [root / "CHANGELOG.md", root / "changelog.md", root / "README.md"]
    changelog = next((p for p in changelog_paths if p.exists()), None)
    changelog_ok = bool(changelog and re.search(r"(?i)(release|changelog|changes|version)", _read(changelog, 30_000)))
    if not changelog_ok:
        findings.append(_finding("CHANGELOG.md", "MISSING_CHANGELOG", "medium", "No release notes/changelog evidence found"))

    sbom_ok = any((root / name).exists() for name in ("sbom.json", "sbom.spdx.json", "bom.json"))
    if not sbom_ok and (mode or "").lower() == "max":
        findings.append(_finding("sbom.json", "MISSING_SBOM", "medium", "No SBOM artifact found before release"))

    high = any(f.get("severity") in {"critical", "high"} for f in findings)
    verdict = "blocked" if high else ("manual_steps" if findings else "ready")
    result = {
        "status": "completed",
        "verdict": verdict,
        "branch": branch.strip() if rc_branch == 0 else "",
        "commit": head.strip() if rc_head == 0 else "",
        "latest_tag": tag.strip() if rc_tag == 0 else "",
        "changelog_ok": changelog_ok,
        "sbom_ok": sbom_ok,
        "findings": findings,
        "findings_count": len(findings),
        "next_actions": _release_next_actions(verdict),
        "warnings": warnings,
    }
    return await _azure_enrich("release_orchestrator", result, AgentRole.INTEGRITY, mode)


def _release_next_actions(verdict: str) -> list[str]:
    if verdict == "ready":
        return ["Release may proceed after prod_readiness_gate returns ready_to_deploy."]
    if verdict == "manual_steps":
        return ["Add/confirm release notes or SBOM evidence, then rerun release_orchestrator."]
    return ["Commit or revert non-artifact changes, fix blockers, then rerun release_orchestrator."]


async def provenance_checker(files: list[str] | None = None, context: str | None = None, mode: str = "safe") -> dict[str, Any]:
    """Check minimal build provenance and dependency evidence."""
    root = _root()
    findings: list[dict[str, Any]] = []
    artifacts = [p for p in (root / "sbom.json", root / "sbom.spdx.json", root / "package-lock.json", root / "requirements.txt", root / "pyproject.toml") if p.exists()]
    hashes = []
    for path in artifacts[:20]:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            hashes.append({"file": _rel(path), "sha256": digest})
        except OSError as exc:
            findings.append(_finding(_rel(path), "HASH_FAILED", "medium", str(exc)))

    rc_head, head, err_head = _run_cmd_safe(["git", "rev-parse", "HEAD"], cwd=str(root))
    rc_remote, remote, _ = _run_cmd_safe(["git", "remote", "-v"], cwd=str(root))
    if rc_head != 0:
        findings.append(_finding("git", "NO_COMMIT_PROVENANCE", "high", err_head or "Cannot resolve HEAD"))
    if rc_remote != 0 or not remote.strip():
        findings.append(_finding("git", "NO_REMOTE", "medium", "No git remote configured for provenance"))
    if not artifacts:
        findings.append(_finding("dependencies", "NO_DEPENDENCY_EVIDENCE", "medium", "No SBOM/lockfile/requirements evidence found"))

    suspicious = []
    for path in _iter_files(["setup.py", "pyproject.toml", "package.json"], limit=10):
        text = _read(path, 80_000)
        if re.search(r"\b(eval|exec|os\.system|subprocess\.)\s*\(", text):
            suspicious.append(_rel(path))
    for rel in suspicious:
        findings.append(_finding(rel, "UNVERIFIED_BUILD_SCRIPT", "high", "Build metadata contains dynamic command execution"))

    score = max(0, 100 - sum(30 if f["severity"] == "high" else 15 for f in findings))
    verdict = "verified" if score >= 85 else ("review_needed" if score >= 60 else "blocked")
    result = {
        "status": "completed",
        "verdict": verdict,
        "commit": head.strip() if rc_head == 0 else "",
        "provenance_score": score,
        "artifact_hashes": hashes,
        "findings": findings,
        "findings_count": len(findings),
        "warnings": [],
    }
    return await _azure_enrich("provenance_checker", result, AgentRole.SECURITY, mode)


async def auth_matrix_auditor(files: list[str] | None = None, diff: str | None = None, context: str | None = None, mode: str = "safe") -> dict[str, Any]:
    """Build a simple endpoint/auth matrix and flag missing object-level checks."""
    endpoints: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    route_re = re.compile(r"@(app|router|bp)\.(get|post|put|patch|delete|route)\(([^)]*)\)")
    auth_words = ("Depends(", "require_auth", "permission", "has_role", "jwt", "current_user", "login_required", "authorize")
    object_words = ("owner", "tenant", "organization", "org_id", "user_id", "account_id", "workspace_id")
    for path in _iter_files(files, _CODE_EXTS, limit=180):
        text = _read(path, 180_000)
        lines = text.splitlines()
        for i, line in enumerate(lines):
            m = route_re.search(line)
            if not m:
                continue
            method = m.group(2).upper()
            raw = m.group(3)
            route = _extract_route(raw)
            window = "\n".join(lines[max(0, i - 6): min(len(lines), i + 18)])
            has_auth = any(word in window for word in auth_words)
            has_object_check = any(word in window.lower() for word in object_words)
            endpoint = {"file": _rel(path), "line": i + 1, "method": method, "path": route, "auth": has_auth, "object_check": has_object_check}
            endpoints.append(endpoint)
            if not _public_route(route) and not has_auth:
                findings.append(_finding(_rel(path), "MISSING_AUTH", "high", f"{method} {route} has no obvious auth guard"))
            elif has_auth and not has_object_check and any(x in route.lower() for x in ("{id}", "<id>", "/id", "user", "account", "tenant", "workspace")):
                findings.append(_finding(_rel(path), "MISSING_OBJECT_CHECK", "medium", f"{method} {route} has auth but no obvious ownership/tenant check"))
    verdict = "no_routes" if not endpoints else ("loose" if findings else "tight")
    result = {
        "status": "completed",
        "verdict": verdict,
        "endpoints": endpoints[:200],
        "endpoints_count": len(endpoints),
        "findings": findings[:100],
        "findings_count": len(findings),
        "warnings": [] if endpoints else ["No route handlers detected."],
    }
    return await _azure_enrich("auth_matrix_auditor", result, AgentRole.SECURITY, mode)


def _extract_route(raw: str) -> str:
    m = re.search(r"['\"]([^'\"]+)['\"]", raw)
    return m.group(1) if m else "<unknown>"


def _public_route(route: str) -> bool:
    return any(x in route.lower() for x in ("health", "ping", "docs", "openapi", "static", "public"))


async def harness_trace_viewer(limit: int = 20, include_logs: bool = False, mode: str = "safe") -> dict[str, Any]:
    """Return recent harness traces from FinOps DB and harness logs."""
    root = _root()
    try:
        limit_n = max(1, min(200, int(limit)))
    except (TypeError, ValueError):
        limit_n = 20
    traces: list[dict[str, Any]] = []
    warnings: list[str] = []
    db = root / ".harness_finops.db"
    if db.exists():
        try:
            conn = sqlite3.connect(str(db))
            conn.row_factory = sqlite3.Row
            try:
                for table in ("runs", "steps"):
                    try:
                        rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT ?", (limit_n,)).fetchall()
                    except sqlite3.Error:
                        continue
                    for row in rows:
                        data = dict(row)
                        traces.append({"source": table, **{k: _redact(str(v)) if isinstance(v, str) else v for k, v in data.items()}})
            finally:
                conn.close()
        except sqlite3.Error as exc:
            warnings.append(f"finops db read failed: {exc}")
    if include_logs:
        for log_name in (".harness_auto_watch.log", ".harness_auto_watch.bootstrap.log"):
            path = root / log_name
            if not path.exists():
                continue
            lines = _read(path, 60_000).splitlines()[-limit_n:]
            for line in lines:
                traces.append({"source": log_name, "message": _redact(line[-500:])})
    bottlenecks = sorted(
        [t for t in traces if isinstance(t.get("duration_ms"), (int, float))],
        key=lambda x: x.get("duration_ms", 0),
        reverse=True,
    )[:5]
    result = {
        "status": "completed",
        "trace": traces[: limit_n * 3],
        "trace_count": len(traces),
        "bottlenecks": bottlenecks,
        "summary": f"{len(traces)} trace/log records found.",
        "warnings": warnings,
    }
    return await _azure_enrich("harness_trace_viewer", result, AgentRole.ANALYZER, mode)


async def incremental_refactor_guard(
    files: list[str] | None = None,
    diff: str | None = None,
    since_commit: str = "",
    mode: str = "safe",
) -> dict[str, Any]:
    """Detect public Python symbol removals/signature changes in a refactor diff."""
    warnings: list[str] = []
    if not diff:
        diff, err = _git_diff(since_commit=since_commit or "")
        if err and not diff:
            warnings.append(err)
    changes: list[dict[str, Any]] = []
    if diff:
        changes.extend(_diff_symbol_changes(diff))
    for path in _iter_files(files, {".py"}, limit=80):
        text = _read(path, 120_000)
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            changes.append({"file": _rel(path), "type": "syntax_error", "symbol": "", "line": exc.lineno or 1, "severity": "high"})
    breaking = [c for c in changes if c.get("severity") == "high"]
    score = min(100, len(breaking) * 40 + max(0, len(changes) - len(breaking)) * 10)
    verdict = "breaking" if breaking else ("review_needed" if changes else "safe")
    result = {
        "status": "completed",
        "guard_verdict": verdict,
        "verdict": "fix_required" if verdict == "breaking" else "ready",
        "breaking_score": score,
        "changes": changes[:100],
        "findings": [
            _finding(c.get("file", "diff"), c.get("type", "change"), c.get("severity", "medium"), f"{c.get('symbol', '')} {c.get('type')}")
            for c in changes[:100]
        ],
        "findings_count": len(changes),
        "warnings": warnings,
    }
    return await _azure_enrich("incremental_refactor_guard", result, AgentRole.REVIEWER, mode)


def _diff_symbol_changes(diff: str) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    current_file = "diff"
    removed_by_file: dict[str, dict[str, str]] = {}
    added_by_file: dict[str, dict[str, str]] = {}
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue
        if line.startswith("-") and not line.startswith("---"):
            symbol = _symbol_from_line(line[1:])
            if symbol and not symbol.startswith("_"):
                removed_by_file.setdefault(current_file, {})[symbol.split("(", 1)[0]] = symbol
        elif line.startswith("+") and not line.startswith("+++"):
            symbol = _symbol_from_line(line[1:])
            if symbol and not symbol.startswith("_"):
                added_by_file.setdefault(current_file, {})[symbol.split("(", 1)[0]] = symbol
    for file_name, removed in removed_by_file.items():
        added = added_by_file.get(file_name, {})
        for name, old_sig in removed.items():
            new_sig = added.get(name)
            if new_sig is None:
                changes.append({"file": file_name, "type": "removed_public_symbol", "symbol": old_sig, "severity": "high"})
            elif old_sig != new_sig:
                changes.append({"file": file_name, "type": "signature_changed", "symbol": f"{old_sig} -> {new_sig}", "severity": "high"})
    return changes


def _symbol_from_line(line: str) -> str:
    m = re.match(r"\s*(?:async\s+)?def\s+([A-Za-z_]\w*\([^)]*\))\s*:", line)
    if m:
        return m.group(1)
    m = re.match(r"\s*class\s+([A-Za-z_]\w*(?:\([^)]*\))?)\s*:", line)
    return m.group(1) if m else ""
