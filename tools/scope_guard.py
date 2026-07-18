"""
Static scope-creep detection for git diffs.

Distilled from the useful idea in Shubhamsaboo/awesome-llm-apps without
vendoring its runtime. This stays local/static and is safe under profile off.
"""
from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

from .core import _get_active_workspace, _run_cmd_safe

STOP_WORDS = {
    "add", "bug", "change", "changes", "chore", "code", "develop", "development",
    "feat", "feature", "fix", "fixed", "implement", "main", "master", "the",
    "this", "to", "update", "with",
}
CONFIG_EXTS = {".toml", ".yaml", ".yml", ".ini", ".cfg"}
BUILD_FILES = {
    "cmakelists.txt", "docker-compose.yaml", "docker-compose.yml", "dockerfile",
    "makefile", "meson.build", "procfile",
}
DEPENDENCY_FILES = {
    "requirements.txt", "package.json", "pyproject.toml", "poetry.lock",
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "go.mod", "go.sum",
    "cargo.toml", "cargo.lock",
}
SYMBOL_RE = re.compile(r"^\s*(?:(?:async\s+)?def\s+([A-Za-z_]\w*)|class\s+([A-Za-z_]\w*))")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)")
JSON_PROP_RE = re.compile(r'^\s*"([A-Za-z0-9@/_.-]+)"\s*:\s*(.+?)[,]?\s*$')
PYPROJECT_STRING_RE = re.compile(r'^\s*["\']([A-Za-z0-9][A-Za-z0-9_.-]*)[^"\']*["\']\s*,?\s*$')
PYPROJECT_ASSIGN_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)\s*=\s*(.+)$")


def _root(root: str | os.PathLike[str] | None = None) -> Path:
    return Path(root or _get_active_workspace()).expanduser().resolve()


def _clean_path(value: str) -> str | None:
    value = value.strip()
    if "\t" in value:
        value = value.split("\t", 1)[0].rstrip()
    if value.startswith('"') and value.endswith('"'):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = value[1:-1]
    if value in {"/dev/null", "dev/null"}:
        return None
    if value.startswith(("a/", "b/")):
        value = value[2:]
    return value


def _parse_diff(text: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    hunk: dict[str, Any] | None = None
    old_remaining = new_remaining = 0

    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            try:
                parts = shlex.split(raw)
            except ValueError:
                parts = raw.split()
            old_path = _clean_path(parts[2]) if len(parts) > 2 else None
            new_path = _clean_path(parts[3]) if len(parts) > 3 else None
            current = {"old_path": old_path, "new_path": new_path, "path": new_path or old_path or "unknown", "hunks": []}
            files.append(current)
            hunk = None
            continue
        if current is None:
            continue
        if raw.startswith("rename from "):
            current["old_path"] = _clean_path(raw[len("rename from "):])
            current["path"] = current.get("new_path") or current.get("old_path") or "unknown"
            continue
        if raw.startswith("rename to "):
            current["new_path"] = _clean_path(raw[len("rename to "):])
            current["path"] = current.get("new_path") or current.get("old_path") or "unknown"
            continue
        if raw.startswith("--- "):
            current["old_path"] = _clean_path(raw[4:])
            current["path"] = current.get("new_path") or current.get("old_path") or "unknown"
            continue
        if raw.startswith("+++ "):
            current["new_path"] = _clean_path(raw[4:])
            current["path"] = current.get("new_path") or current.get("old_path") or "unknown"
            continue
        match = HUNK_RE.match(raw)
        if match:
            old_remaining = int(match.group(2) or "1")
            new_remaining = int(match.group(4) or "1")
            hunk = {"header": raw, "lines": []}
            current["hunks"].append(hunk)
            continue
        if hunk is None or not raw:
            continue
        marker = raw[0]
        if marker not in {" ", "+", "-"}:
            continue
        hunk["lines"].append({"marker": marker, "text": raw[1:]})
        if marker != "+":
            old_remaining -= 1
        if marker != "-":
            new_remaining -= 1
        if old_remaining <= 0 and new_remaining <= 0:
            hunk = None
    return files


def _changed_lines(file_change: dict[str, Any], marker: str) -> list[str]:
    return [
        entry["text"]
        for hunk in file_change.get("hunks", [])
        for entry in hunk.get("lines", [])
        if entry.get("marker") == marker
    ]


def _tokenize(value: str) -> set[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    value = re.sub(r"[^A-Za-z0-9]+", " ", value).lower()
    return {token for token in value.split() if len(token) >= 3 and token not in STOP_WORDS}


def _config_kind(path: str) -> str | None:
    normalized = path.lower()
    name = os.path.basename(normalized)
    ext = os.path.splitext(name)[1]
    if normalized.startswith(".github/") or normalized.startswith(".gitlab/"):
        return "ci"
    if name in BUILD_FILES or name.startswith("dockerfile."):
        return "build"
    if ext in CONFIG_EXTS:
        return "config"
    return None


def _dependency_lines(file_change: dict[str, Any], marker: str) -> list[tuple[str, str]]:
    path = str(file_change.get("path", "")).lower()
    name = os.path.basename(path)
    lines = _changed_lines(file_change, marker)
    found: list[tuple[str, str]] = []
    if name.startswith("requirements") and name.endswith(".txt"):
        for line in lines:
            parsed = _requirement_dependency(line)
            if parsed:
                found.append(parsed)
        return found
    if name == "package.json":
        in_deps = False
        for hunk in file_change.get("hunks", []):
            for entry in hunk.get("lines", []):
                line = entry.get("text", "")
                top = re.match(r'^\s{0,2}"([^"]+)"\s*:', line)
                if top:
                    in_deps = top.group(1) in {"dependencies", "devDependencies", "optionalDependencies", "peerDependencies"}
                    continue
                if entry.get("marker") != marker or not in_deps:
                    continue
                match = JSON_PROP_RE.match(line)
                if match:
                    found.append((match.group(1).lower(), line.strip()))
        return found
    if name == "pyproject.toml":
        section = None
        in_project_list = False
        for hunk in file_change.get("hunks", []):
            for entry in hunk.get("lines", []):
                line = entry.get("text", "")
                section_match = re.match(r"^\s*\[([^]]+)\]\s*$", line)
                if section_match:
                    section = section_match.group(1).lower()
                    in_project_list = False
                    continue
                if section == "project" and re.match(r"^\s*dependencies\s*=\s*\[", line):
                    in_project_list = True
                    continue
                if in_project_list and "]" in line:
                    in_project_list = False
                if entry.get("marker") != marker:
                    continue
                if in_project_list:
                    match = PYPROJECT_STRING_RE.match(line)
                    if match:
                        found.append((match.group(1).lower().replace("_", "-"), line.strip()))
                elif section in {"tool.poetry.dependencies", "tool.poetry.group.dev.dependencies"}:
                    match = PYPROJECT_ASSIGN_RE.match(line)
                    if match and match.group(1).lower() != "python":
                        found.append((match.group(1).lower().replace("_", "-"), line.strip()))
        return found
    return found


def _requirement_dependency(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "-", ".")):
        return None
    match = REQ_RE.match(stripped)
    if not match:
        return None
    return match.group(1).lower().replace("_", "-"), stripped


def _find_api_renames(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    renames: list[dict[str, Any]] = []
    for file_change in files:
        path = str(file_change.get("path", ""))
        if not path.endswith(".py"):
            continue
        removed = [m.group(1) or m.group(2) for line in _changed_lines(file_change, "-") if (m := SYMBOL_RE.match(line))]
        added = [m.group(1) or m.group(2) for line in _changed_lines(file_change, "+") if (m := SYMBOL_RE.match(line))]
        for old, new in zip(removed, added):
            if old != new and not old.startswith("_") and not new.startswith("_"):
                renames.append({"path": path, "from": old, "to": new})
    return renames


def _git_diff_text(root: Path, *, staged: bool = False, base: str | None = None) -> tuple[str, str]:
    if base:
        cmd = ["git", "diff", "--no-ext-diff", "--no-textconv", f"{base}...HEAD"]
    elif staged:
        cmd = ["git", "diff", "--cached", "--no-ext-diff", "--no-textconv"]
    else:
        cmd = ["git", "diff", "--no-ext-diff", "--no-textconv"]
    rc, out, err = _run_cmd_safe(cmd, cwd=str(root), timeout=30)
    if rc != 0 and base:
        rc, out, err = _run_cmd_safe(["git", "diff", "--no-ext-diff", "--no-textconv", base], cwd=str(root), timeout=30)
    if rc != 0:
        return "", err or out or "git diff failed"
    return out, ""


def _classify(files: list[dict[str, Any]], intent: str, hunk_threshold: int) -> dict[str, Any]:
    intent_tokens = _tokenize(intent)
    new_deps: list[dict[str, Any]] = []
    api_renames = _find_api_renames(files)
    config_edits: list[dict[str, Any]] = []
    in_scope: list[dict[str, Any]] = []
    likely_creep: list[dict[str, Any]] = []

    for file_change in files:
        path = str(file_change.get("path", "unknown"))
        added = _changed_lines(file_change, "+")
        removed = _changed_lines(file_change, "-")
        added_count = len(added)
        removed_count = len(removed)
        reasons: list[str] = []
        path_tokens = _tokenize(path)
        content_tokens = _tokenize("\n".join(added[:80] + removed[:80]))
        overlap = sorted((path_tokens | content_tokens) & intent_tokens)
        name = os.path.basename(path.lower())

        for dep_name, line in _dependency_lines(file_change, "+"):
            if dep_name not in {old for old, _line in _dependency_lines(file_change, "-")}:
                new_deps.append({"path": path, "name": dep_name, "line": line})
                reasons.append("new_dependency")
        kind = _config_kind(path)
        if kind:
            config_edits.append({"path": path, "kind": kind})
            reasons.append(f"{kind}_edit")
        if name in DEPENDENCY_FILES:
            reasons.append("dependency_file")
        if file_change.get("old_path") and file_change.get("new_path") and file_change.get("old_path") != file_change.get("new_path"):
            reasons.append("rename")
        if added_count + removed_count >= hunk_threshold:
            reasons.append("large_hunk")
        if path.count("/") >= 2 and not overlap and intent_tokens:
            reasons.append("unrelated_subsystem")
        if any(r.get("path") == path for r in api_renames):
            reasons.append("public_api_rename")

        item = {
            "path": path,
            "added": added_count,
            "removed": removed_count,
            "overlap": overlap,
            "reasons": sorted(dict.fromkeys(reasons)),
        }
        risky = any(r in item["reasons"] for r in {
            "new_dependency", "dependency_file", "ci_edit", "build_edit",
            "public_api_rename", "large_hunk", "unrelated_subsystem",
        })
        if risky and not overlap:
            likely_creep.append(item)
        elif risky and any(r in item["reasons"] for r in {"new_dependency", "public_api_rename", "ci_edit", "build_edit"}):
            likely_creep.append(item)
        else:
            in_scope.append(item)

    return {
        "in_scope": sorted(in_scope, key=lambda item: item["path"]),
        "likely_creep": sorted(likely_creep, key=lambda item: item["path"]),
        "new_deps": sorted(new_deps, key=lambda item: (item["path"], item["name"])),
        "api_renames": sorted(api_renames, key=lambda item: (item["path"], item["from"])),
        "config_edits": sorted(config_edits, key=lambda item: item["path"]),
        "stats": {
            "files_changed": len(files),
            "likely_creep_files": len(likely_creep),
            "new_dependency_count": len(new_deps),
            "api_rename_count": len(api_renames),
            "config_edit_count": len(config_edits),
        },
    }


def _recommend(report: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    if report["likely_creep"]:
        recommendations.append("Split or justify files marked likely_creep before final review/commit.")
    if report["new_deps"]:
        recommendations.append("Confirm each new dependency is required by the stated task and run license/security checks.")
    if report["api_renames"]:
        recommendations.append("Treat public API renames as breaking changes unless covered by compatibility shims/tests.")
    if report["config_edits"]:
        recommendations.append("Review CI/build/config changes separately from product-code changes.")
    if not recommendations:
        recommendations.append("No obvious scope-creep signals detected.")
    return recommendations


def scope_creep_detector(
    changed_files: list[str] | None = None,
    diff: str | None = None,
    task: str | None = None,
    staged: bool = False,
    base: str | None = None,
    hunk_threshold: int = 80,
    root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Classify diff scope against the stated task using local static rules."""
    workspace = _root(root)
    if not diff:
        diff, err = _git_diff_text(workspace, staged=staged, base=base)
        if err:
            return {"status": "error", "error": err, "root": str(workspace)}
    files = _parse_diff(diff or "")
    if changed_files:
        wanted = {str(f).replace("\\", "/").strip() for f in changed_files if isinstance(f, str)}
        files = [f for f in files if str(f.get("path", "")).replace("\\", "/") in wanted] or files
    if not files:
        return {
            "status": "skipped",
            "reason": "no diff files found",
            "root": str(workspace),
            "recommendations": ["Provide diff, staged=true, base=<ref>, or make local git changes."],
        }
    threshold = max(20, min(int(hunk_threshold or 80), 500))
    report = _classify(files, task or "", threshold)
    verdict = "attention_required" if report["likely_creep"] else "in_scope"
    return {
        "status": "completed",
        "verdict": verdict,
        "root": str(workspace),
        "task": task or "",
        "staged": staged,
        "base": base or "",
        "hunk_threshold": threshold,
        **report,
        "recommendations": _recommend(report),
    }
