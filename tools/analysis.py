"""
tools/analysis.py — Codebase semantic search, schema drift, telemetry debugging, and static code profiling.
Ported from support_tools.py.
"""
import asyncio
import ast
import ipaddress
import json
import logging
import math
import os
import re
import socket
import statistics
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from config import WORKSPACE_ROOT
from agents import AgentRole
from .fix import suggest_fix

_log = logging.getLogger("harness.analysis")


def _optional_llm_enabled() -> bool:
    return os.getenv("HARNESS_STATIC_LLM", "").strip().lower() in {"1", "true", "yes", "on"}


async def schema_drift(baseline_schema: Optional[str] = None) -> dict:
    """Quét các Pydantic models và so sánh với baseline để phát hiện drift."""
    warnings = []
    
    py_files = []
    for r_dir, _, files_in_dir in os.walk(WORKSPACE_ROOT):
        if any(p in r_dir for p in [".git", "node_modules", ".harness_worktree", ".gemini", ".claude"]):
            continue
        for f in files_in_dir:
            if f.endswith(".py"):
                py_files.append(os.path.join(r_dir, f))
                
    current_schema = {}
    
    for py_file in py_files:
        rel_path = os.path.relpath(py_file, WORKSPACE_ROOT)
        try:
            with open(py_file, "r", encoding="utf-8", errors="ignore") as f:
                tree = ast.parse(f.read())
        except Exception:
            continue
            
        file_models = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                is_model = False
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id == "BaseModel":
                        is_model = True
                    elif isinstance(base, ast.Attribute) and base.attr == "BaseModel":
                        is_model = True
                        
                if is_model:
                    fields = []
                    for item in node.body:
                        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                            f_name = item.target.id
                            try:
                                f_type = ast.unparse(item.annotation)
                            except Exception:
                                f_type = "unknown"
                            fields.append({"name": f_name, "type": f_type})
                    if fields:
                        file_models[node.name] = fields
                        
        if file_models:
            current_schema[rel_path] = file_models
            
    baseline = {}
    baseline_file = os.path.join(WORKSPACE_ROOT, ".harness_schema_baseline.json")
    
    if baseline_schema:
        try:
            baseline = json.loads(baseline_schema)
        except Exception:
            warnings.append("Không thể parse baseline_schema từ input, dùng baseline file thay thế")
            
    if not baseline and os.path.isfile(baseline_file):
        try:
            with open(baseline_file, "r", encoding="utf-8") as f:
                baseline = json.load(f)
        except Exception:
            warnings.append("Lỗi đọc file baseline .harness_schema_baseline.json")
            
    drift = {
        "added": {},
        "removed": {},
        "changed": {}
    }
    
    for file_path, file_models in current_schema.items():
        if file_path not in baseline:
            drift["added"][file_path] = file_models
        else:
            added_classes = {}
            removed_classes = {}
            changed_classes = {}
            
            curr_classes = file_models
            base_classes = baseline[file_path]
            
            for cls_name, cls_fields in curr_classes.items():
                if cls_name not in base_classes:
                    added_classes[cls_name] = cls_fields
                else:
                    curr_fields_map = {f["name"]: f["type"] for f in cls_fields}
                    base_fields_map = {f["name"]: f["type"] for f in base_classes[cls_name]}
                    
                    fields_drift = {"added": [], "removed": [], "changed": []}
                    for f_name, f_type in curr_fields_map.items():
                        if f_name not in base_fields_map:
                            fields_drift["added"].append({"name": f_name, "type": f_type})
                        elif base_fields_map[f_name] != f_type:
                            fields_drift["changed"].append({
                                "name": f_name,
                                "old_type": base_fields_map[f_name],
                                "new_type": f_type
                            })
                    for f_name, f_type in base_fields_map.items():
                        if f_name not in curr_fields_map:
                            fields_drift["removed"].append({"name": f_name, "type": f_type})
                            
                    if fields_drift["added"] or fields_drift["removed"] or fields_drift["changed"]:
                        changed_classes[cls_name] = fields_drift
                        
            for cls_name, cls_fields in base_classes.items():
                if cls_name not in curr_classes:
                    removed_classes[cls_name] = cls_fields
                    
            if added_classes or removed_classes or changed_classes:
                drift["changed"][file_path] = {
                    "added_classes": added_classes,
                    "removed_classes": removed_classes,
                    "changed_classes": changed_classes
                }
                
    for file_path, file_models in baseline.items():
        if file_path not in current_schema:
            drift["removed"][file_path] = file_models
            
    if not os.path.isfile(baseline_file):
        try:
            with open(baseline_file, "w", encoding="utf-8") as f:
                json.dump(current_schema, f, ensure_ascii=False, indent=2)
            warnings.append("Đã tự tạo file baseline mới tại .harness_schema_baseline.json")
        except Exception:
            pass
            
    has_drift = bool(drift["added"] or drift["removed"] or drift["changed"])
    return {
        "drift_detected": has_drift,
        "drift": drift,
        "current_schema": current_schema,
        "warnings": warnings
    }


async def telemetry_debugger(log_content: str) -> dict:
    """Chẩn đoán lỗi từ log telemetry (ví dụ: stack trace)."""
    warnings = []
    
    matches = re.findall(r"file\s+\"([^\"]+\.py)\",\s+line\s+(\d+)", log_content.lower())
    target_files = []
    for fpath, line in matches:
        rel_p = os.path.relpath(fpath, WORKSPACE_ROOT)
        if not rel_p.startswith("..") and os.path.exists(os.path.join(WORKSPACE_ROOT, rel_p)):
            target_files.append(rel_p)
            
    target_files = list(set(target_files))
    
    if not target_files:
        for r_dir, _, files_in_dir in os.walk(WORKSPACE_ROOT):
            if any(p in r_dir for p in [".git", "node_modules", ".harness_worktree"]):
                continue
            for f in files_in_dir:
                if f.endswith(".py"):
                    target_files.append(os.path.relpath(os.path.join(r_dir, f), WORKSPACE_ROOT))
                    if len(target_files) >= 3:
                        break
            if len(target_files) >= 3:
                break
                
    _log.debug("[Harness Telemetry Debugger] Phát hiện %d file liên quan", len(target_files))
    fix_res = await suggest_fix(
        error=f"Lỗi telemetry phát hiện crash:\n{log_content}",
        files=target_files if target_files else None
    )
    
    if not isinstance(fix_res, dict):
        fix_res = {}
    fix_res["root_cause"] = str(fix_res.get("root_cause") or "")
    fix_res["patch"] = str(fix_res.get("patch") or "")
    raw_w = fix_res.get("warnings", [])
    fix_res["warnings"] = [w for w in raw_w if isinstance(w, str)] if isinstance(raw_w, list) else []

    return {
        "files_analyzed": target_files,
        "fix_result": fix_res,
        "warnings": warnings
    }


async def semantic_search(query: str, top_k: int = 5) -> dict:
    """Tìm kiếm file/hàm/class trong codebase (polyglot, 158 ngôn ngữ) dựa trên FTS5 + tree-sitter."""
    from .codebase_index import get_index
    idx = get_index()
    top_k = max(1, min(100, int(top_k)))
    results = idx.search(query, top_k=top_k)
    return {"query": query, "results": results, "warnings": []}


async def dead_code_scanner() -> dict:
    """Quét codebase polyglot để phát hiện mã nguồn chết (dead code) — hàm/class không được gọi từ bất cứ đâu."""
    from .codebase_index import get_index
    idx = get_index()
    dead = idx.find_dead_code()

    # LLM đánh giá impact và priority cho từng dead symbol
    llm_analysis: dict = {}
    if dead:
        from .core import _llm_analyze, _parse_json_object
        dead_ctx = "\n".join(
            f"- {s.get('symbol', '?')} ({s.get('kind', '?')}) tại {s.get('file', '?')}:{s.get('line', '?')}"
            for s in dead[:40]
        )
        prompt = (
            "Bạn là code quality expert. Phân tích danh sách dead code (symbols không có caller nào).\n"
            "Với mỗi symbol, đánh giá:\n"
            "1. SAFE_TO_DELETE: Rõ ràng là dead, không có side-effect khi xóa\n"
            "2. VERIFY_FIRST: Có thể được gọi qua reflection/dynamic dispatch/plugin/entry-point — cần kiểm tra\n"
            "3. KEEP: Có lý do chính đáng (public API, __all__, abstract method, test fixture)\n\n"
            f"Dead symbols:\n{dead_ctx}\n\n"
            "Trả về JSON:\n"
            "{\n"
            '  "analysis": [{"symbol": "...", "verdict": "SAFE_TO_DELETE|VERIFY_FIRST|KEEP", "reason": "..."}],\n'
            '  "safe_to_delete_count": 0,\n'
            '  "verify_first_count": 0,\n'
            '  "summary": "..."\n'
            "}"
        )
        if _optional_llm_enabled():
            try:
                raw = await asyncio.wait_for(_llm_analyze(prompt, role=AgentRole.SCANNER), timeout=30)
                llm_analysis = _parse_json_object(raw) or {}
            except Exception as _e:
                llm_analysis = {"warning": f"LLM analysis bỏ qua: {_e}"}
        else:
            llm_analysis = {"summary": "Static scan only. Set HARNESS_STATIC_LLM=1 to add LLM impact analysis."}

    return {
        "dead_symbols": dead,
        "dead_symbols_count": len(dead),
        "llm_analysis": llm_analysis,
        "warnings": [],
    }


async def index_codebase(force: bool = False) -> dict:
    """Build/rebuild persistent codebase index (tree-sitter polyglot, 158 ngôn ngữ, SQLite FTS5).

    Tự động chạy khi semantic_search/dead_code_scanner/ask_codebase được gọi lần đầu.
    Gọi với force=True để rebuild khi thêm nhiều file mới hoặc sau refactor lớn.
    """
    from .codebase_index import get_index
    idx = get_index()
    return idx.build(force=bool(force))


def profiler(code: str, iterations: int = 1) -> dict:
    """Chạy phân tích hiệu năng (profiling) một đoạn code Python sử dụng cProfile và tracemalloc."""
    import cProfile
    import pstats
    import io
    import tracemalloc
    
    warnings = []
    local_scope = {}
    global_scope = {"__builtins__": __builtins__}
    
    pr = cProfile.Profile()
    tracemalloc.start()
    
    try:
        pr.enable()
        for _ in range(iterations):
            exec(code, global_scope, local_scope)
        pr.disable()
    except Exception as e:
        tracemalloc.stop()
        return {"error": f"Lỗi thực thi code trong profiler: {e}", "warnings": warnings}
        
    peak_mem = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    
    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
    ps.print_stats(30)
    
    profile_output = s.getvalue()
    
    func_stats = []
    for func, stat in ps.stats.items():
        cc, nc, tt, ct, callers = stat
        func_name = f"{func[2]} ({func[0]}:{func[1]})"
        func_stats.append({
            "function": func_name,
            "calls": nc,
            "tottime_ms": round(tt * 1000, 3),
            "cumtime_ms": round(ct * 1000, 3)
        })
        
    func_stats.sort(key=lambda x: x["cumtime_ms"], reverse=True)

    return {
        "profile_raw": profile_output,
        "top_functions": func_stats[:15],
        "peak_memory_kb": round(peak_mem / 1024, 2),
        "warnings": warnings
    }


# ── Shared helpers for new analysis tools ─────────────────────────────────────

_TEXT_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".env", ".example", ".cfg", ".conf", ".sh", ".bash", ".zsh", ".md", ".txt",
    ".sql", ".html", ".css", ".scss", ".less", ".properties", ".java", ".go",
    ".rs", ".c", ".cpp", ".h", ".cs", ".rb", ".php",
}
_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".harness_worktree", ".harness_sandbox",
    ".harness_cache", ".gemini", ".claude",
}
_SKIP_FILENAMES = {".env", ".env.local", ".env.prod", ".env.production", ".env.staging"}
_MAX_SCAN_FILES = 2000


def _is_env_file(name: str) -> bool:
    return name.startswith(".env") or name in _SKIP_FILENAMES


def _iter_candidate_files(
    paths: list[str] | None = None,
    exts: set[str] | None = None,
    skip_env: bool = False,
) -> list[Path]:
    root = Path(WORKSPACE_ROOT).resolve()
    exts = exts or _TEXT_EXTS
    collected: list[Path] = []

    def _safe_add(p: Path) -> None:
        try:
            resolved = p.resolve()
            if root != resolved and root not in resolved.parents:
                return
            if resolved.is_file():
                if skip_env and _is_env_file(resolved.name):
                    return
                if resolved.name in _SKIP_FILENAMES and not skip_env:
                    return
                if resolved.suffix.lower() in exts or (not skip_env and resolved.name.startswith(".env")):
                    collected.append(resolved)
            elif resolved.is_dir():
                for child in resolved.rglob("*"):
                    if any(part in _SKIP_DIRS for part in child.parts):
                        continue
                    if child.is_file():
                        if skip_env and _is_env_file(child.name):
                            continue
                        if child.name in _SKIP_FILENAMES:
                            continue
                        if child.suffix.lower() in exts or (not skip_env and child.name.startswith(".env")):
                            collected.append(child.resolve())
        except Exception:
            pass

    if paths:
        for p in paths:
            if p and isinstance(p, str):
                _safe_add(root / p)
    else:
        for child in root.rglob("*"):
            if any(part in _SKIP_DIRS for part in child.parts):
                continue
            if child.is_file():
                if skip_env and _is_env_file(child.name):
                    continue
                if child.name in _SKIP_FILENAMES:
                    continue
                if child.suffix.lower() in exts or (not skip_env and child.name.startswith(".env")):
                    collected.append(child.resolve())

    seen: set[str] = set()
    unique: list[Path] = []
    for p in collected:
        key = str(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def _read_text(path: Path, limit: int = 300_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def _relpath(path: Path) -> str:
    try:
        return os.path.relpath(str(path), WORKSPACE_ROOT)
    except Exception:
        return str(path)


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _severity_rank(sev: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get((sev or "").lower(), 0)


def _parse_env_keys(path: Path) -> tuple[set[str], list[str]]:
    warnings: list[str] = []
    if not path.is_file():
        return set(), [f"{_relpath(path)}: file không tồn tại"]
    keys: set[str] = set()
    try:
        for idx, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("export "):
                stripped = stripped[7:].strip()
            if "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].strip()
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
                keys.add(key)
            else:
                warnings.append(f"{_relpath(path)}:{idx}: key không hợp lệ '{key}'")
    except Exception as e:
        warnings.append(f"{_relpath(path)}: lỗi đọc file — {e}")
    return keys, warnings


# ── AST visitors ──────────────────────────────────────────────────────────────

class _StringLiteralCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.items: list[tuple[int, str]] = []

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self.items.append((getattr(node, "lineno", 1), node.value))
        self.generic_visit(node)


class _ComplexityVisitor(ast.NodeVisitor):
    def __init__(self, rel_path: str) -> None:
        self.rel_path = rel_path
        self._stack: list[str] = []
        self.results: list[dict] = []

    def _complexity(self, node: ast.AST) -> int:
        score = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With, ast.AsyncWith)):
                score += 1
            elif isinstance(child, ast.BoolOp):
                score += max(1, len(child.values) - 1)
            elif isinstance(child, ast.IfExp):
                score += 1
            elif isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                score += len(getattr(child, "generators", []))
            elif isinstance(child, ast.comprehension):
                score += len(child.ifs)
        return score

    def _record(self, node: ast.AST, name: str, kind: str) -> None:
        qualname = ".".join(self._stack + [name]) if self._stack else name
        self.results.append({
            "file": self.rel_path,
            "name": qualname,
            "kind": kind,
            "line": getattr(node, "lineno", 1),
            "complexity": self._complexity(node),
        })

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record(node, node.name, "function")
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record(node, node.name, "async_function")
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()


# ── Secret patterns ───────────────────────────────────────────────────────────

_SECRET_PATTERNS: list[tuple[str, str, str]] = [
    ("private_key",           r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----",                          "critical"),
    ("aws_access_key",        r"\bAKIA[0-9A-Z]{16}\b",                                             "high"),
    ("github_token",          r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",                                   "high"),
    ("slack_token",           r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",                                 "high"),
    ("stripe_live_key",       r"\bsk_live_[A-Za-z0-9]{16,}\b",                                     "high"),
    ("generic_api_key",       r"(?i)\b(api[_-]?key|access[_-]?key|secret[_-]?key)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]", "medium"),
    ("token_assignment",      r"(?i)\b(token|auth[_-]?token|bearer)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]",               "medium"),
    ("password_assignment",   r"(?i)\b(password|passwd|pwd|db_password)\b\s*[:=]\s*['\"][^'\"]{3,}['\"]",            "high"),
    ("authorization_header",  r"(?i)\bAuthorization\b['\"]?\s*[:=]\s*['\"](?:Bearer|Basic)\s+[A-Za-z0-9_\-\.=:+/]{8,}['\"]", "high"),
]

_ALLOWLIST_MARKERS = ("# pragma: allowlist secret", "noqa: secret", "nosecret", "# nosec")


# ── 5 New tools ───────────────────────────────────────────────────────────────

async def secret_scanner(paths: list[str] | None = None) -> dict:
    """Scan source files for hardcoded secrets via regex + Shannon entropy on string literals."""
    findings: list[dict] = []
    warnings: list[str] = []

    files = _iter_candidate_files(paths, skip_env=True)
    if not files:
        return {"findings": [], "findings_count": 0, "scanned_files": 0, "warnings": warnings}

    files = sorted(files)  # deterministic order before quota cut
    if len(files) > _MAX_SCAN_FILES:
        skipped = len(files) - _MAX_SCAN_FILES
        warnings.append(f"Quá nhiều file ({len(files)}), chỉ quét {_MAX_SCAN_FILES} file; bỏ qua {skipped} file.")
        files = files[:_MAX_SCAN_FILES]

    for path in files:
        content = _read_text(path)
        if not content:
            continue
        rel = _relpath(path)
        lines = content.splitlines()

        for idx, line in enumerate(lines, start=1):
            if any(m in line for m in _ALLOWLIST_MARKERS):
                continue
            for secret_type, pattern, severity in _SECRET_PATTERNS:
                if re.search(pattern, line):
                    findings.append({
                        "file": rel, "line": idx, "type": secret_type,
                        "severity": severity, "snippet": line.strip()[:180],
                    })

        # Full-content scan with DOTALL to catch secrets in triple-quoted/multiline strings.
        for secret_type, pattern, severity in _SECRET_PATTERNS:
            try:
                for m in re.finditer(pattern, content, re.DOTALL | re.MULTILINE):
                    lineno = content.count("\n", 0, m.start()) + 1
                    snippet = content[m.start():m.start() + 120].replace("\n", "\\n")
                    if any(marker in snippet for marker in _ALLOWLIST_MARKERS):
                        continue
                    findings.append({
                        "file": rel, "line": lineno, "type": secret_type,
                        "severity": severity, "snippet": snippet[:180], "multiline": True,
                    })
            except re.error as exc:
                warnings.append(f"Pattern '{secret_type}' lỗi khi multiline scan: {exc}")

        if path.suffix.lower() == ".py":
            try:
                tree = ast.parse(content)
                collector = _StringLiteralCollector()
                collector.visit(tree)
                for lineno, value in collector.items:
                    candidate = value.replace("\n", "").strip()
                    if len(candidate) < 24:
                        continue
                    if not re.fullmatch(r"[A-Za-z0-9_\-=/+.]+", candidate):
                        continue
                    if any(x in candidate.lower() for x in ("example", "dummy", "sample", "test", "localhost", "changeme")):
                        continue
                    entropy = _shannon_entropy(candidate)
                    if entropy >= 4.2:
                        findings.append({
                            "file": rel, "line": lineno,
                            "type": "high_entropy_string",
                            "severity": "medium" if entropy < 4.8 else "high",
                            "snippet": candidate[:80],
                            "entropy": round(entropy, 2),
                        })
            except Exception as e:
                warnings.append(f"{rel}: AST parse error — {e}")

    dedup: dict[tuple, dict] = {}
    for f in findings:
        key = (f["file"], f["line"], f["type"], f.get("snippet", "")[:40])
        prev = dedup.get(key)
        if prev is None or _severity_rank(f["severity"]) > _severity_rank(prev["severity"]):
            dedup[key] = f

    final = sorted(dedup.values(), key=lambda x: (-_severity_rank(x.get("severity", "low")), x["file"], x["line"]))

    # LLM triage false positives và đánh giá severity thực tế
    llm_triage: dict = {}
    if final:
        from .core import _llm_analyze, _parse_json_object
        triage_ctx = "\n".join(
            f"[{i+1}] {f['file']}:{f['line']} type={f['type']} severity={f['severity']} snippet={f.get('snippet','')[:80]}"
            for i, f in enumerate(final[:30])
        )
        triage_prompt = (
            "Bạn là security expert. Xem xét danh sách potential secrets tìm được bằng regex/entropy scan.\n"
            "Với mỗi finding, đánh giá:\n"
            "1. FALSE_POSITIVE: Có phải placeholder/example/test value không? (vd: 'your-api-key-here', 'changeme', value quá ngắn)\n"
            "2. REAL_SECRET: Có format của secret thực? (key dài 32+ chars, token JWT, password thực)\n"
            "3. UNCERTAIN: Không thể xác định chắc\n\n"
            f"Findings:\n{triage_ctx}\n\n"
            "Trả về JSON:\n"
            "{\n"
            '  "triage": [{"index": 1, "verdict": "FALSE_POSITIVE|REAL_SECRET|UNCERTAIN", "reason": "..."}],\n'
            '  "false_positive_count": 0,\n'
            '  "real_secret_count": 0,\n'
            '  "summary": "..."\n'
            "}"
        )
        if _optional_llm_enabled():
            try:
                raw = await asyncio.wait_for(_llm_analyze(triage_prompt, role=AgentRole.SECURITY), timeout=30)
                llm_triage = _parse_json_object(raw) or {}
            except Exception as _e:
                llm_triage = {"warning": f"LLM triage bỏ qua: {_e}"}
        else:
            llm_triage = {"summary": "Static scan only. Set HARNESS_STATIC_LLM=1 to add LLM secret triage."}

    return {
        "findings": final[:200],
        "findings_count": len(final),
        "scanned_files": len(files),
        "llm_triage": llm_triage,
        "warnings": warnings,
    }


async def changelog_generator(since: str = "HEAD~10", until: str = "HEAD", format: str = "markdown") -> dict:
    """Generate changelog from git log, grouped by conventional-commit type."""
    warnings: list[str] = []
    if not isinstance(format, str):
        return {"error": "format phải là string ('markdown' hoặc 'text')", "warnings": warnings}
    fmt = format.strip().lower() or "markdown"
    if fmt not in {"markdown", "text"}:
        return {"error": "format chỉ hỗ trợ 'markdown' hoặc 'text'", "warnings": warnings}

    try:
        r = subprocess.run(
            ["git", "log", f"{since}..{until}", "--pretty=format:%H%x1f%s%x1f%an%x1f%ad", "--date=short", "--no-merges"],
            cwd=WORKSPACE_ROOT, capture_output=True, text=True, timeout=20,
        )
    except FileNotFoundError:
        return {"error": "git không có trên PATH", "warnings": warnings}
    except Exception as e:
        return {"error": f"Lỗi chạy git log: {e}", "warnings": warnings}

    if r.returncode != 0:
        return {"error": f"git log thất bại: {r.stderr.strip()}", "warnings": warnings}

    raw_lines = [line for line in r.stdout.splitlines() if line.strip()]
    if not raw_lines:
        return {"commits_count": 0, "changelog": "Không có commit trong khoảng chỉ định.", "warnings": warnings}

    grouped: dict[str, list[dict]] = defaultdict(list)
    first_date = last_date = None

    for line in raw_lines:
        parts = line.split("\x1f")
        if len(parts) != 4:
            warnings.append(f"Dòng git log không hợp lệ: {line[:80]}")
            continue
        commit_hash, subject, author, commit_date = parts
        first_date = first_date or commit_date
        last_date = commit_date
        m = re.match(r"^(feat|fix|chore|docs|refactor|perf|test|build|ci)(?:\([^)]+\))?!?:\s*(.+)$", subject.strip(), re.I)
        group = m.group(1).lower() if m else "other"
        summary = m.group(2).strip() if m else subject.strip()
        grouped[group].append({"hash": commit_hash[:7], "summary": summary, "author": author.strip(), "date": commit_date.strip()})

    order = ["feat", "fix", "perf", "refactor", "docs", "test", "build", "ci", "chore", "other"]
    titles = {"feat": "Features", "fix": "Fixes", "perf": "Performance", "refactor": "Refactors",
              "docs": "Documentation", "test": "Tests", "build": "Build", "ci": "CI", "chore": "Chores", "other": "Other"}
    version_header = f"{until} ({first_date or ''} → {last_date or ''})".strip()

    if fmt == "markdown":
        lines = ["# Changelog", "", f"## {version_header}", ""]
        for key in order:
            items = grouped.get(key, [])
            if not items:
                continue
            lines.append(f"### {titles[key]}")
            for item in items:
                lines.append(f"- {item['summary']} ({item['hash']}, {item['author']})")
            lines.append("")
        changelog = "\n".join(lines).strip()
    else:
        lines = [f"CHANGELOG: {version_header}", ""]
        for key in order:
            items = grouped.get(key, [])
            if not items:
                continue
            lines.append(f"[{key.upper()}]")
            for item in items:
                lines.append(f"* {item['summary']} ({item['hash']})")
            lines.append("")
        changelog = "\n".join(lines).strip()

    return {
        "commits_count": sum(len(v) for v in grouped.values()),
        "groups": {k: v for k, v in grouped.items() if v},
        "changelog": changelog,
        "warnings": warnings,
    }


async def env_parity_checker(example_file: str = ".env.example", env_file: str = ".env") -> dict:
    """Compare env keys between .env.example and .env — find missing or extra keys."""
    warnings: list[str] = []
    root = Path(WORKSPACE_ROOT).resolve()

    for raw in (example_file, env_file):
        resolved = (root / raw).resolve()
        if root != resolved and root not in resolved.parents:
            return {"error": f"Path nằm ngoài WORKSPACE_ROOT: {raw}", "warnings": warnings}

    example_keys, w1 = _parse_env_keys(root / example_file)
    env_keys, w2 = _parse_env_keys(root / env_file)
    warnings.extend(w1)
    warnings.extend(w2)

    missing = sorted(example_keys - env_keys)
    extra = sorted(env_keys - example_keys)
    score = max(0, 100 - len(missing) * 10 - len(extra) * 3)

    return {
        "example_file": example_file,
        "env_file": env_file,
        "missing_in_env": missing,
        "extra_in_env": extra,
        "common_keys_count": len(example_keys & env_keys),
        "parity_score": score,
        "ok": not missing and not extra,
        "message": "Parity OK" if not missing and not extra else f"Thiếu {len(missing)} key, dư {len(extra)} key.",
        "warnings": warnings,
    }


def _is_ssrf_blocked(url: str) -> str | None:
    """Return error message if URL targets a private/internal address, else None.
    Fail-closed: if hostname cannot be resolved, the request is blocked."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return f"Scheme không hỗ trợ: {parsed.scheme!r} (chỉ http/https)"
        hostname = parsed.hostname or ""
        if not hostname:
            return "URL thiếu hostname"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        # Resolve ALL addresses (IPv4 + IPv6); fail-closed if resolution fails.
        try:
            infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            return f"Hostname '{hostname}' không resolve được — blocked để tránh SSRF"
        if not infos:
            return f"Hostname '{hostname}' không có địa chỉ nào — blocked"
        for _fam, _type, _proto, _canon, sockaddr in infos:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                return f"Không parse được địa chỉ resolved '{ip_str}'"
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                return f"URL tới địa chỉ nội bộ/reserved không được phép: {ip}"
    except Exception as e:
        return f"URL không hợp lệ: {e}"
    return None


async def load_tester(url: str, requests_count: int = 100, concurrency: int = 10, method: str = "GET") -> dict:
    """Send concurrent HTTP requests and report p50/p95/p99 latency, error rate, RPS."""
    warnings: list[str] = []
    if not url or not isinstance(url, str):
        return {"error": "url không hợp lệ", "warnings": warnings}
    ssrf_err = _is_ssrf_blocked(url)
    if ssrf_err:
        return {"error": ssrf_err, "warnings": warnings}
    try:
        requests_count = int(requests_count)
        concurrency = int(concurrency)
    except (TypeError, ValueError):
        return {"error": "requests_count và concurrency phải là số nguyên", "warnings": warnings}
    _MAX_REQUESTS = 1000
    _MAX_CONCURRENCY = 50
    if requests_count < 1:
        return {"error": "requests_count phải >= 1", "warnings": warnings}
    if requests_count > _MAX_REQUESTS:
        warnings.append(f"requests_count capped từ {requests_count} xuống {_MAX_REQUESTS}")
        requests_count = _MAX_REQUESTS
    if concurrency < 1:
        return {"error": "concurrency phải >= 1", "warnings": warnings}
    if concurrency > _MAX_CONCURRENCY:
        warnings.append(f"concurrency capped từ {concurrency} xuống {_MAX_CONCURRENCY}")
        concurrency = _MAX_CONCURRENCY
    if not isinstance(method, str):
        return {"error": "method phải là string", "warnings": warnings}
    http_method = method.upper().strip()
    if http_method not in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}:
        return {"error": f"method không hỗ trợ: {http_method}", "warnings": warnings}

    semaphore = asyncio.Semaphore(concurrency)
    results: list[dict] = []

    async def _one(client: httpx.AsyncClient, _idx: int) -> None:
        async with semaphore:
            t0 = time.perf_counter()
            try:
                resp = await client.request(http_method, url)
                ms = (time.perf_counter() - t0) * 1000
                redirect_error = ""
                if 300 <= resp.status_code < 400 and resp.headers.get("location"):
                    redirect_url = str(resp.url.join(resp.headers["location"]))
                    blocked = _is_ssrf_blocked(redirect_url)
                    if blocked:
                        redirect_error = f"Blocked redirect target: {blocked}"
                results.append({
                    "ok": 200 <= resp.status_code < 400 and not redirect_error,
                    "status_code": resp.status_code,
                    "ms": round(ms, 2),
                    "error": redirect_error,
                })
            except Exception as e:
                ms = (time.perf_counter() - t0) * 1000
                results.append({"ok": False, "status_code": None, "ms": round(ms, 2), "error": str(e)})

    timeout = httpx.Timeout(10.0, connect=5.0)
    limits = httpx.Limits(max_connections=max(concurrency, 1), max_keepalive_connections=max(concurrency, 1))
    wall_t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=False) as client:
        await asyncio.gather(*(_one(client, i) for i in range(requests_count)))
    total_s = time.perf_counter() - wall_t0

    if not results:
        return {"error": "Không thu được kết quả", "warnings": warnings}

    latencies = sorted(r["ms"] for r in results)
    success = sum(1 for r in results if r["ok"])
    error_rate = (len(results) - success) / len(results) * 100

    def _pct(vals: list[float], p: float) -> float:
        if not vals:
            return 0.0
        k = (len(vals) - 1) * p
        f, c = int(k), math.ceil(k)
        return vals[f] if f == c else vals[f] * (c - k) + vals[c] * (k - f)

    status_dist: dict[str, int] = {}
    for r in results:
        k = "ERR" if r["status_code"] is None else str(r["status_code"])
        status_dist[k] = status_dist.get(k, 0) + 1

    return {
        "url": url, "method": http_method,
        "requests_count": len(results), "concurrency": concurrency,
        "success_count": success, "failure_count": len(results) - success,
        "error_rate_pct": round(error_rate, 2),
        "rps": round(len(results) / total_s, 2) if total_s > 0 else 0,
        "latency_ms": {
            "min": round(min(latencies), 2),
            "avg": round(statistics.mean(latencies), 2),
            "p50": round(_pct(latencies, 0.50), 2),
            "p95": round(_pct(latencies, 0.95), 2),
            "p99": round(_pct(latencies, 0.99), 2),
            "max": round(max(latencies), 2),
        },
        "status_codes": status_dist,
        "sample_errors": [r["error"] for r in results if r["error"]][:10],
        "warnings": warnings,
    }


async def complexity_analyzer(paths: list[str] | None = None, threshold: int = 10) -> dict:
    """Analyze Python cyclomatic complexity per function using AST; flag hotspots above threshold."""
    warnings: list[str] = []
    try:
        threshold = int(threshold)
    except (TypeError, ValueError):
        return {"error": "threshold phải là số nguyên", "warnings": warnings}
    if threshold < 1:
        return {"error": "threshold phải >= 1", "warnings": warnings}
    py_files = _iter_candidate_files(paths, exts={".py"})
    if not py_files:
        return {"threshold": threshold, "files_scanned": 0, "functions_analyzed": 0, "hotspots": [], "warnings": warnings}

    functions: list[dict] = []
    for path in py_files:
        rel = _relpath(path)
        content = _read_text(path)
        if not content:
            continue
        try:
            tree = ast.parse(content)
            visitor = _ComplexityVisitor(rel)
            visitor.visit(tree)
            functions.extend(visitor.results)
        except SyntaxError as e:
            warnings.append(f"{rel}: syntax error — {e}")
        except Exception as e:
            warnings.append(f"{rel}: parse error — {e}")

    hotspots = sorted([f for f in functions if f["complexity"] > threshold], key=lambda x: (-x["complexity"], x["file"], x["line"]))
    avg = round(statistics.mean([f["complexity"] for f in functions]), 2) if functions else 0.0

    # LLM suggest cách refactor cụ thể cho top hotspots
    llm_refactor: dict = {}
    if hotspots:
        from .core import _llm_analyze, _parse_json_object
        hotspot_ctx = "\n".join(
            f"- {h.get('name') or h.get('function') or '<unknown>'} ({h['file']}:{h['line']}) complexity={h['complexity']}"
            for h in hotspots[:15]
        )
        prompt = (
            "Bạn là refactoring expert. Phân tích các hàm có cyclomatic complexity cao.\n"
            "Với mỗi hàm, suggest cách cụ thể để giảm complexity:\n"
            "- Extract method: tách logic nhánh thành hàm riêng\n"
            "- Replace conditional with polymorphism\n"
            "- Early return / guard clause\n"
            "- Strategy pattern\n"
            "- Lookup table thay if/elif chains\n\n"
            f"Hotspots:\n{hotspot_ctx}\n\n"
            "Trả về JSON:\n"
            "{\n"
            '  "suggestions": [{"function": "...", "file": "...", "complexity": 0, '
            '"technique": "...", "example": "brief pseudocode or description"}],\n'
            '  "priority_fix": "Tên hàm nên refactor trước nhất",\n'
            '  "summary": "..."\n'
            "}"
        )
        if _optional_llm_enabled():
            try:
                raw = await asyncio.wait_for(_llm_analyze(prompt, role=AgentRole.REVIEWER), timeout=30)
                llm_refactor = _parse_json_object(raw) or {}
            except Exception as _e:
                llm_refactor = {"warning": f"LLM refactor bỏ qua: {_e}"}
        else:
            llm_refactor = {"summary": "Static scan only. Set HARNESS_STATIC_LLM=1 to add LLM refactor suggestions."}

    return {
        "threshold": threshold,
        "files_scanned": len(py_files),
        "functions_analyzed": len(functions),
        "average_complexity": avg,
        "max_complexity": max((f["complexity"] for f in functions), default=0),
        "hotspots": hotspots[:200],
        "llm_refactor": llm_refactor,
        "summary": {
            "low":       sum(1 for f in functions if f["complexity"] <= 5),
            "moderate":  sum(1 for f in functions if 6 <= f["complexity"] <= 10),
            "high":      sum(1 for f in functions if 11 <= f["complexity"] <= 20),
            "very_high": sum(1 for f in functions if f["complexity"] > 20),
        },
        "warnings": warnings,
    }
