"""
tools/swarm.py — Multi-Agent Swarm, ask_codebase, and quick_task.
Ported from support_tools.py.
"""
import asyncio
import os
import re
import time
import uuid
import json
import unicodedata
from pathlib import Path
from typing import Optional
from config import WORKSPACE_ROOT, get_azure_client
from agents import Agent, AgentRole, AgentResult
from .core import (
    read_workspace_files,
    _load_relevant_wiki_context,
    _parse_json_object,
    _result_meta,
    _extract_and_apply_patch,
    _restore_session_backups,
    _cleanup_session_backups,
    run_in_sandbox,
    _get_active_workspace,
    MAX_TOTAL_BYTES_BIG
)


def _run_reproducer_in_sandbox(reproducer_code: str) -> dict:
    filename = f"test_swarm_reproducer_{uuid.uuid4().hex}.py"
    payload = (
        "import pathlib, subprocess, sys\n"
        f"filename = {filename!r}\n"
        f"pathlib.Path(filename).write_text({reproducer_code!r}, encoding='utf-8')\n"
        "r = subprocess.run([sys.executable, '-m', 'pytest', filename], "
        "capture_output=True, text=True, encoding='utf-8', errors='replace')\n"
        "print(r.stdout)\n"
        "print(r.stderr)\n"
        "sys.exit(r.returncode)\n"
    )
    return run_in_sandbox(payload, timeout=30)


def _sandbox_failure_kind(result: dict) -> str:
    if result.get("status") != "success":
        return "infra"
    output = ((result.get("stdout") or "") + "\n" + (result.get("stderr") or "")).lower()
    if "no module named pytest" in output or "module named 'pytest'" in output:
        return "infra"
    return "none" if result.get("returncode") == 0 else "test_failed"


def _ask_codebase_timeout() -> float:
    try:
        return max(5.0, float(os.getenv("HARNESS_ASK_CODEBASE_TIMEOUT", "45")))
    except (TypeError, ValueError):
        return 45.0


def _ask_codebase_context_cap() -> int:
    try:
        return max(20_000, int(os.getenv("HARNESS_ASK_CODEBASE_CONTEXT_BYTES", "650000")))
    except (TypeError, ValueError):
        return 650_000


def _ask_codebase_load_cap() -> int:
    try:
        return max(20_000, int(os.getenv("HARNESS_ASK_CODEBASE_LOAD_BYTES", str(MAX_TOTAL_BYTES_BIG))))
    except (TypeError, ValueError):
        return MAX_TOTAL_BYTES_BIG


def _ask_codebase_use_spares() -> bool:
    return os.getenv("HARNESS_ASK_CODEBASE_USE_SPARES", "0").strip().lower() not in {"0", "false", "no", "off"}


def _ask_codebase_timeout_retries() -> int:
    try:
        return max(0, int(os.getenv("HARNESS_ASK_CODEBASE_TIMEOUT_RETRIES", "0")))
    except (TypeError, ValueError):
        return 0


def _ask_codebase_include_wiki() -> bool:
    return os.getenv("HARNESS_ASK_CODEBASE_INCLUDE_WIKI", "0").strip().lower() in {"1", "true", "yes", "on"}


_ASK_CODEBASE_MAX_FILES = 15
_ASK_DIRECT_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".harness_cache",
    ".harness_smoke", ".harness_sandbox", ".gemini", ".claude", ".Codex",
    "llmwiki", "dist", "build", "coverage",
}
_ASK_DIRECT_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb", ".php",
    ".cs", ".sql", ".html", ".css", ".json", ".yaml", ".yml", ".toml", ".md",
}
_ASK_DIRECT_SCAN_FILE_LIMIT = 5000

_ASK_STOPWORDS = {
    "the", "and", "for", "with", "what", "where", "how", "why", "file", "code",
    "this", "that", "from", "into", "are", "you", "can", "could", "would",
    "cho", "cua", "của", "trong", "ngoai", "ngoài", "nay", "này", "kia",
    "mot", "một", "cac", "các", "nhung", "những", "chua", "chưa", "tren",
    "trên", "duoi", "dưới", "lam", "làm", "viet", "viết", "chay", "chạy",
    "xem", "check", "thu", "thử", "sao", "nhu", "như", "nao", "nào",
    "dang", "đang", "duoc", "được", "khong", "không", "co", "có",
}

_SECRET_NAME = r"(?:api[_-]?key|access[_-]?key|secret[_-]?key|token|password|passwd|pwd|authorization)"
_SENSITIVE_PATTERNS = (
    re.compile(rf"(?i)\b{_SECRET_NAME}\b\s*[:=]\s*(['\"])[^'\"]{{3,}}\1"),
    re.compile(rf"(?i)\b{_SECRET_NAME}\b\s*[:=]\s*[^\s,;}}]{{3,}}"),
    re.compile(r"\b(?:sk_live_|sk_test_|ghp_|github_pat_)[A-Za-z0-9_=-]{12,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
)


def _query_terms(question: str) -> set[str]:
    terms: set[str] = set()
    for raw in re.findall(r"[\w./:-]{3,}", question.lower(), flags=re.UNICODE):
        for part in re.split(r"[./:-]+", raw):
            if len(part) >= 3 and part not in _ASK_STOPWORDS:
                terms.add(part)
    for token in list(terms):
        for part in re.findall(r"[a-z]?[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", token):
            part = part.lower()
            if len(part) >= 3 and part not in _ASK_STOPWORDS:
                terms.add(part)
    return terms


def _iter_file_lines(context: str) -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    current_file = ""
    for line in context.splitlines():
        m_file = re.match(r"^=== FILE: (.+?) ===$", line)
        if m_file:
            current_file = m_file.group(1)
            continue
        m_line = re.match(r"^(\d+)\t(.*)$", line)
        if current_file and m_line:
            rows.append((current_file, int(m_line.group(1)), m_line.group(2)))
    return rows


def _score_code_line(path: str, line: str, terms: set[str]) -> tuple[int, list[str]]:
    haystack = f"{path}\n{line}".lower()
    matched = sorted(t for t in terms if t in haystack)
    score = len(matched) * 4
    if not matched:
        return 0, []
    stripped = line.strip()
    if re.search(r"\b(class|def|async def|function|const|let|var|export|interface|type)\b", stripped):
        score += 10
    if any("_" in t and t in stripped.lower() for t in matched):
        score += 8
    if re.search(r"\b(route|router|endpoint|handler|controller|service|repository|schema|model)\b", haystack):
        score += 2
    if re.search(r"\b(todo|fixme|error|raise|except|catch|warning|fallback|timeout)\b", haystack):
        score += 1
    if stripped.startswith(("#", "//", "/*", "*")):
        score -= 1
    if path.lower().endswith((".md", ".txt", ".rst", ".adoc")):
        score -= 4
    return score, matched


def _context_snippet(rows: list[tuple[str, int, str]], idx: int, radius: int = 1) -> str:
    path, line_no, _ = rows[idx]
    snippets = []
    start = max(0, idx - radius)
    end = min(len(rows), idx + radius + 1)
    for j in range(start, end):
        p2, ln2, text = rows[j]
        if p2 != path:
            continue
        prefix = ">" if ln2 == line_no else " "
        snippets.append(f"{prefix}{ln2}: {text.rstrip()[:180]}")
    return "\n".join(snippets)


def _truncate_bytes(text: str, max_bytes: int) -> str:
    return text.encode("utf-8", errors="replace")[:max_bytes].decode("utf-8", errors="ignore")


def _redact_sensitive_text(text: str) -> str:
    redacted = unicodedata.normalize("NFKC", text)
    for pattern in _SENSITIVE_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def _direct_workspace_hits(question: str, limit: int = 10) -> list[str]:
    terms = _query_terms(question)
    if not terms:
        return []
    try:
        root = Path(_get_active_workspace()).expanduser().resolve()
    except (OSError, ValueError):
        return []
    if not root.is_dir():
        return []
    scored: list[tuple[int, str]] = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _ASK_DIRECT_SKIP_DIRS and not d.startswith(".harness_worktree_"))
        for fname in sorted(filenames):
            if fname.lower().startswith(".env"):
                continue
            path = Path(dirpath) / fname
            suffix = path.suffix.lower()
            if suffix not in _ASK_DIRECT_EXTS:
                continue
            try:
                if path.stat().st_size > 250_000:
                    continue
                resolved = path.resolve()
                try:
                    if os.path.commonpath([str(resolved), str(root)]) != str(root):
                        continue
                except ValueError:
                    continue
                rel = path.relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            scanned += 1
            path_lower = rel.lower()
            score = 0
            for term in terms:
                if term in path_lower:
                    score += 12
            try:
                with path.open("r", encoding="utf-8", errors="replace") as f:
                    for line_no, line in enumerate(f, start=1):
                        lower = line.lower()
                        for term in terms:
                            count = lower.count(term)
                            if count:
                                score += min(30, count * (8 if "_" in term else 3))
                        if score >= 60 or line_no >= 1200:
                            break
            except OSError:
                continue
            if suffix in {".md", ".txt", ".rst", ".adoc"}:
                score -= 8
            if "/test" in path_lower or path_lower.startswith("test_") or path_lower.endswith("_test.py"):
                score -= 6
            if score > 0:
                scored.append((score, rel))
            if scanned >= _ASK_DIRECT_SCAN_FILE_LIMIT:
                break
        if scanned >= _ASK_DIRECT_SCAN_FILE_LIMIT:
            break
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [rel for _score, rel in scored[:limit]]


def _skip_auto_selected_file(path: str) -> bool:
    rel = path.replace("\\", "/").strip("/")
    first = rel.split("/", 1)[0]
    name = Path(rel).name.lower()
    return first in _ASK_DIRECT_SKIP_DIRS or name.startswith(".env") or name.startswith(".harness_")


def _sanitize_ask_files(files: list[str] | None) -> tuple[list[str], list[str]]:
    safe: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    raw_files = list(files or [])
    if len(raw_files) > 1000:
        warnings.append(f"ask_codebase file list truncated from {len(raw_files)} to 1000 before sanitize")
        raw_files = raw_files[:1000]
    for raw in raw_files:
        if not isinstance(raw, str) or not raw.strip():
            warnings.append(f"{raw!r}: ask_codebase file path invalid — skipped")
            continue
        rel = raw.replace("\\", "/").strip()
        p = Path(rel)
        if p.is_absolute() or ".." in p.parts:
            warnings.append(f"{raw}: ask_codebase rejects absolute/path traversal — skipped")
            continue
        normalized = p.as_posix()
        if _skip_auto_selected_file(normalized):
            warnings.append(f"{raw}: ask_codebase skips harness/env/wiki artifact — skipped")
            continue
        if normalized not in seen:
            seen.add(normalized)
            safe.append(normalized)
    return safe, warnings


def _pack_file_block(path: str, lines: list[tuple[int, str]], budget: int) -> tuple[str, int]:
    header = f"=== FILE: {path} ==="
    total = len(header.encode("utf-8", errors="replace"))
    if total >= budget:
        return "", 0
    packed = []
    for line_no, text in lines:
        line = f"{line_no}\t{text}"
        line_bytes = len(("\n" + line).encode("utf-8", errors="replace"))
        if total + line_bytes > budget:
            break
        packed.append(line)
        total += line_bytes
    if not packed:
        return "", 0
    block = header + "\n" + "\n".join(packed)
    return block, len(block.encode("utf-8", errors="replace"))


def _narrow_files_for_question(question: str, files: list[str]) -> tuple[list[str], list[str]]:
    if len(files) <= _ASK_CODEBASE_MAX_FILES:
        return files, []
    warnings = []
    original = list(dict.fromkeys(files))
    allowed = set(original)
    terms = _query_terms(question)
    narrowed = [path for path in original if any(term in path.lower() for term in terms)]
    narrowed = narrowed[:_ASK_CODEBASE_MAX_FILES]
    try:
        from .codebase_index import get_index
        hits = get_index().search(question, top_k=60)
        for hit in hits:
            path = hit.get("path", "")
            if path in allowed and path not in narrowed:
                narrowed.append(path)
            if len(narrowed) >= _ASK_CODEBASE_MAX_FILES:
                break
        if narrowed:
            warnings.append(f"ask_codebase narrowed {len(original)} provided file(s) to {len(narrowed)} via CodebaseIndex")
            return narrowed, warnings
    except Exception as e:
        warnings.append(f"ask_codebase file narrowing skipped: {e}")

    scored = []
    for path in original:
        score = sum(1 for term in terms if term in path.lower())
        if score:
            scored.append((score, path))
    if scored:
        scored.sort(key=lambda item: (-item[0], item[1]))
        narrowed = [path for _score, path in scored[:_ASK_CODEBASE_MAX_FILES]]
        warnings.append(f"ask_codebase narrowed {len(original)} provided file(s) to {len(narrowed)} by path keywords")
        return narrowed, warnings
    fallback = original[:_ASK_CODEBASE_MAX_FILES]
    warnings.append(f"ask_codebase narrowing found no matches; using first {len(fallback)} provided file(s)")
    return fallback, warnings


def _prune_context_for_question(question: str, context: str, max_bytes: int) -> tuple[str, list[str]]:
    terms = _query_terms(question)
    rows = _iter_file_lines(context)
    if not terms or not rows or len(context.encode("utf-8", errors="replace")) <= max_bytes:
        return context, []

    ranked: list[tuple[int, str, int, int]] = []
    for idx, (path, line_no, text) in enumerate(rows):
        score, _matched = _score_code_line(path, text, terms)
        if score > 0:
            ranked.append((score, path, line_no, idx))
    if not ranked:
        return _truncate_bytes(context, max_bytes), [f"ask_codebase context truncated to {max_bytes} bytes; no relevance matches found"]

    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    keep: dict[str, set[int]] = {}
    for _score, path, _line_no, idx in ranked[:160]:
        bucket = keep.setdefault(path, set())
        for j in range(max(0, idx - 3), min(len(rows), idx + 4)):
            p2, ln2, _text = rows[j]
            if p2 == path:
                bucket.add(ln2)

    by_file: dict[str, list[tuple[int, str]]] = {}
    for path, line_no, text in rows:
        if line_no in keep.get(path, set()):
            by_file.setdefault(path, []).append((line_no, text))

    file_scores: dict[str, int] = {}
    for score, path, _line_no, _idx in ranked:
        file_scores[path] = file_scores.get(path, 0) + score
    blocks = []
    total = 0
    for path in sorted(by_file, key=lambda p: (-file_scores.get(p, 0), p)):
        lines = sorted(by_file[path])
        block, block_bytes = _pack_file_block(path, lines, max_bytes - total)
        if not block:
            continue
        blocks.append(block)
        total += block_bytes

    if not blocks:
        return _truncate_bytes(context, max_bytes), [f"ask_codebase context truncated to {max_bytes} bytes; relevance blocks exceeded cap"]
    original = len(context.encode("utf-8", errors="replace"))
    pruned = "\n\n".join(blocks)
    kept_files = ", ".join(sorted(by_file)[:8])
    return pruned, [f"ask_codebase pruned context {original} -> {len(pruned.encode('utf-8', errors='replace'))} bytes; top files: {kept_files}"]


def _extract_wiki_hits(context: str, terms: set[str]) -> list[str]:
    blocks = re.split(r"\n(?==== WIKI )", context)
    hits: list[tuple[int, str]] = []
    for block in blocks:
        if not block.startswith("=== WIKI "):
            continue
        lower = block.lower()
        score = sum(lower.count(t) for t in terms)
        if score:
            hits.append((score, block[:600].strip()))
    hits.sort(key=lambda item: -item[0])
    return [text for _score, text in hits[:3]]


def _extractive_codebase_answer(question: str, context: str, files: Optional[list[str]], reason: str) -> str:
    terms = _query_terms(question)
    rows = _iter_file_lines(context)
    ranked: list[tuple[int, str, int, str, list[str], int]] = []
    for idx, (path, line_no, text) in enumerate(rows):
        score, matched = _score_code_line(path, text, terms)
        if score > 0:
            ranked.append((score, path, line_no, text.strip(), matched, idx))

    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected = []
    per_file: dict[str, int] = {}
    for item in ranked:
        path = item[1]
        limit = 2 if path.lower().endswith((".md", ".txt", ".rst", ".adoc")) else 3
        if per_file.get(path, 0) >= limit:
            continue
        selected.append(item)
        per_file[path] = per_file.get(path, 0) + 1
        if len(selected) >= 10:
            break
    file_scores: dict[str, int] = {}
    for score, path, *_rest in ranked[:80]:
        file_scores[path] = file_scores.get(path, 0) + score
    likely_files = sorted(file_scores.items(), key=lambda item: (-item[1], item[0]))[:6]
    wiki_hits = _extract_wiki_hits(context, terms)
    file_list = ", ".join(files or []) or "index/navigation context"

    lines = [
        f"Fallback local vì Manager/Azure không trả answer usable: {reason}.",
        f"Context đã load: {file_list}.",
        "",
    ]
    if likely_files:
        lines.append("Kết luận khả dĩ:")
        for path, score in likely_files:
            lines.append(f"- `{path}` là vùng liên quan mạnh nhất (score {score}).")
        lines.append("")

    if selected:
        lines.append("Bằng chứng trực tiếp:")
        seen_locations: set[tuple[str, int]] = set()
        emitted = 0
        for score, path, line_no, text, matched, idx in selected:
            loc = (path, line_no)
            if loc in seen_locations:
                continue
            seen_locations.add(loc)
            emitted += 1
            terms_text = ", ".join(matched[:6]) if matched else "structural"
            lines.append(f"- `{path}:{line_no}` score={score}, match={terms_text}")
            lines.append("```text")
            lines.append(_context_snippet(rows, idx))
            lines.append("```")
            if emitted >= 8:
                break
    elif wiki_hits:
        lines.append("Không có line code match mạnh; wiki context liên quan:")
        lines.extend(f"- {hit.splitlines()[0]}" for hit in wiki_hits)
    else:
        lines.append("Không tìm thấy line match trực tiếp theo keyword trong context đã load.")

    lines.extend([
        "",
        "Gợi ý cho agent chính:",
        "- Nếu cần sửa code ngay, đọc trực tiếp các file trong `Kết luận khả dĩ` trước.",
        "- Nếu danh sách file lệch, gọi lại `ask_codebase` với `files` cụ thể hoặc chạy `index_codebase(force=true)` sau refactor lớn.",
    ])
    return "\n".join(lines)


def _normalize_manager_answer(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        obj = None
    if isinstance(obj, dict):
        answer = obj.get("answer") or obj.get("summary") or obj.get("result")
        if isinstance(answer, str) and answer.strip():
            return answer.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            obj = json.loads(fenced.group(1))
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            answer = obj.get("answer") or obj.get("summary") or obj.get("result")
            if isinstance(answer, str) and answer.strip():
                return answer.strip()
    return text


def _manager_answer_usable(answer: str) -> bool:
    text = (answer or "").strip()
    low = text.lower()
    weak_markers = (
        "không đủ ngữ cảnh",
        "khong du ngu canh",
        "need more context",
        "cannot determine",
        "can't determine",
        "fallback extractive",
    )
    if any(marker in low for marker in weak_markers):
        return False
    if "không tìm thấy trong context đã cung cấp" in low or "khong tim thay trong context da cung cap" in low:
        return True
    citation_patterns = (
        r"`?[\w./\\() -]+\.\w+:\d+`?",
        r"`?[\w./\\() -]+\.\w+\s+line\s+\d+`?",
        r"`?[\w./\\() -]+\.\w+#L\d+`?",
        r"\[[^\]]+\]\([^)]+\.\w+(?::\d+|#L\d+)[^)]*\)",
    )
    if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in citation_patterns):
        return True
    return False


async def ask_codebase(
    question: str,
    files: Optional[list[str]] = None,
    index_md: Optional[str] = None,
) -> dict:
    """Hỏi đáp trên lượng code lớn (model 1M context).

    Khi `files` không được cung cấp, tự động dùng CodebaseIndex để tìm các file liên quan nhất.
    """
    warnings = []
    if files is not None and not isinstance(files, list):
        return {"error": "files must be a list of relative paths", "warnings": warnings}
    if files:
        files, sanitize_warnings = _sanitize_ask_files(files)
        warnings.extend(sanitize_warnings)
    if not files and not index_md:
        seen: dict[str, float] = {}
        direct_hits = _direct_workspace_hits(question, limit=6)
        for p in direct_hits:
            seen[p] = 1.0
        if direct_hits:
            warnings.append(f"Direct symbol scan selected {len(direct_hits)} file(s) for: {question[:80]}")
        try:
            from .codebase_index import get_index
            idx = get_index()
            hits = idx.search(question, top_k=20)
            for h in hits:
                p = h.get("path", "")
                if p and p not in seen and not _skip_auto_selected_file(p):
                    seen[p] = h.get("score", 0.0)
            files = list(seen.keys())[:_ASK_CODEBASE_MAX_FILES]
            if files:
                warnings.append(f"Auto-selected {len(files)} file(s) via direct scan/CodebaseIndex for: {question[:80]}")
        except Exception as e:
            warnings.append(f"CodebaseIndex lookup failed: {e}")
            files = list(seen.keys())[:_ASK_CODEBASE_MAX_FILES]
    if not files and not index_md:
        return {"error": "Cần cung cấp danh sách file qua `files` hoặc nội dung điều hướng qua `index_md`", "warnings": warnings}
        
    ctx_blocks = []
    loaded_count = 0
    try:
        from .goal import goal_progress_summary
        goal_summary = goal_progress_summary()
    except Exception:
        goal_summary = ""
    if goal_summary:
        ctx_blocks.append(f"=== GOAL PROGRESS ===\n{goal_summary}")

    if _ask_codebase_include_wiki():
        wiki_ctx = _load_relevant_wiki_context("\n".join([question, "\n".join(files or []), index_md or ""]))
        if wiki_ctx:
            ctx_blocks.append(f"=== PROJECT WIKI CONTEXT (SELECTIVE) ===\n{wiki_ctx}")
    
    if files:
        files, narrow_warnings = _narrow_files_for_question(question, files)
        warnings.extend(narrow_warnings)
        file_ctx, file_warns, file_loaded = read_workspace_files(
            files,
            total_cap=min(MAX_TOTAL_BYTES_BIG, _ask_codebase_load_cap()),
        )
        warnings.extend(file_warns)
        if file_ctx:
            ctx_blocks.append(file_ctx)
            loaded_count += file_loaded
            
    if index_md:
        ctx_blocks.append(f"=== INDEX / NAVIGATION CONTEXT ===\n{index_md}")
        
    ctx = "\n\n".join(ctx_blocks)
    if not ctx:
        return {"error": "Không đọc được dữ liệu ngữ cảnh nào từ files hoặc index_md", "warnings": warnings}
    ctx = _redact_sensitive_text(ctx)
    ctx, prune_warnings = _prune_context_for_question(question, ctx, _ask_codebase_context_cap())
    warnings.extend(prune_warnings)
    try:
        from .ops import context_auditor

        context_health = await context_auditor(question=question, files=None, context=ctx)
    except Exception as exc:
        context_health = {"status": "skipped", "error": str(exc)}

    timeout_s = _ask_codebase_timeout()
    task = (
        f"{question}\n\n"
        "Trả lời trực tiếp bằng Markdown tiếng Việt. BẮT BUỘC trích dẫn `file:line` cụ thể cho mọi claim về code. "
        "Nếu không thấy bằng chứng trong context, nói rõ `Không tìm thấy trong context đã cung cấp`. "
        "Không trả JSON wrapper trừ khi user hỏi rõ JSON."
    )
    try:
        result = await asyncio.wait_for(
            Agent(AgentRole.MANAGER, get_azure_client()).run_async(
                task, ctx, max_output_tokens=4096, timeout=timeout_s,
                timeout_retries=_ask_codebase_timeout_retries(),
                use_spares=_ask_codebase_use_spares(),
            ),
            timeout=timeout_s + 10,
        )
    except asyncio.TimeoutError:
        result = AgentResult(
            agent_id="manager-timeout",
            agent_role=AgentRole.MANAGER,
            model_used="manager",
            task=task,
            result="",
            duration_ms=int((timeout_s + 10) * 1000),
            status="error",
            error=f"ask_codebase hard timeout after {timeout_s + 10:.0f}s",
        )

    answer_text = _normalize_manager_answer(result.result)
    if result.status != "success" or not _manager_answer_usable(answer_text):
        reason = result.error or f"empty result with status={result.status}"
        if result.status == "success" and answer_text:
            reason = "manager answer missing usable file:line evidence"
        answer = _extractive_codebase_answer(question, ctx, files, reason)
        warnings.append(f"Manager model không trả answer usable: {reason}; dùng fallback extractive.")
        return {
            "answer": answer,
            "files_loaded": loaded_count,
            "agent": _result_meta(result),
            "fallback": True,
            "warnings": warnings,
            "context_health": context_health,
        }

    return {
        "answer": answer_text,
        "files_loaded": loaded_count,
        "agent": _result_meta(result), "warnings": warnings,
        "context_health": context_health,
    }


async def quick_task(instruction: str, context: Optional[str] = None) -> dict:
    """Việc vặt nhanh-rẻ qua model mini."""
    result = await Agent(AgentRole.WORKER, get_azure_client()).run_async(
        instruction, context or "",
    )
    return {
        "output": result.result if result.status == "success" else None,
        "agent": _result_meta(result),
    }


async def swarm_step_architect(error_log: str, files: Optional[list[str]] = None) -> dict:
    """Bước 1: Architect phân tích lỗi và đề xuất file cần sửa."""
    swarm_logs = [{"role": "coordinator", "message": "Bắt đầu chặng 1: Architect phân tích lỗi.", "timestamp": time.time()}]
    warnings = []
    
    ctx_files = files if files else []
    workspace = os.path.realpath(_get_active_workspace())
    if not ctx_files:
        matches = re.findall(r"file\s+\"([^\"]+\.py)\",\s+line\s+(\d+)", error_log.lower())
        for fpath, line in matches:
            rel_p = os.path.relpath(fpath, workspace)
            if not rel_p.startswith("..") and os.path.exists(os.path.join(workspace, rel_p)):
                ctx_files.append(rel_p)
        ctx_files = list(set(ctx_files))
        
    ctx_block = ""
    if ctx_files:
        ctx_block, w_list, _ = read_workspace_files(ctx_files)
        warnings.extend(w_list)
        
    architect_prompt = (
        "Bạn là Architect Agent trong Swarm Debugger.\n"
        f"Lỗi hệ thống:\n{error_log}\n\n"
        f"Mã nguồn hiện tại:\n{ctx_block}\n\n"
        "Nhiệm vụ:\n"
        "1. Xác định nguyên nhân gốc rễ (Root Cause).\n"
        "2. Đề xuất phương án sửa lỗi cụ thể.\n"
        "3. Trả về phân tích dưới dạng JSON block thuần:\n"
        "{\n"
        "  \"root_cause\": \"...\",\n"
        "  \"suggested_approach\": \"...\",\n"
        "  \"target_files\": [\"file1.py\"]\n"
        "}"
    )
    
    client = get_azure_client()
    res_arch = await Agent(AgentRole.ANALYZER, client).run_async(architect_prompt)
    if res_arch.status != "success":
        return {"error": f"Architect Agent lỗi: {res_arch.error}", "logs": swarm_logs}
        
    arch_data = _parse_json_object(res_arch.result)
    root_cause = arch_data.get("root_cause", "Không rõ")
    suggested_approach = arch_data.get("suggested_approach", "")
    target_files = arch_data.get("target_files", ctx_files)
    
    if not isinstance(target_files, list):
        target_files = ctx_files
    else:
        valid_targets = []
        for tf in target_files:
            tf_str = str(tf).strip()
            full_tf = os.path.realpath(os.path.join(workspace, tf_str))
            try:
                outside = os.path.commonpath([full_tf, workspace]) != workspace
            except ValueError:
                outside = True
            if not outside:
                valid_targets.append(tf_str)
        target_files = valid_targets if valid_targets else ctx_files
        
    swarm_logs.append({"role": "architect", "message": f"Đã tìm ra Root Cause: {root_cause}", "timestamp": time.time()})
    swarm_logs.append({"role": "architect", "message": f"Đề xuất sửa các file: {target_files}", "timestamp": time.time()})
    
    return {
        "status": "success",
        "root_cause": root_cause,
        "suggested_approach": suggested_approach,
        "target_files": target_files,
        "logs": swarm_logs,
        "warnings": warnings
    }


async def swarm_step_tester(error_log: str, root_cause: str, target_files: list[str], custom_reproducer: Optional[str] = None) -> dict:
    """Bước 2: Tester tạo file test reproducer và chạy kiểm thử trong sandbox."""
    swarm_logs = [{"role": "tester", "message": "Bắt đầu chặng 2: Tester sinh và kiểm tra test reproducer.", "timestamp": time.time()}]
    warnings = []
    
    ctx_block = ""
    if target_files:
        ctx_block, w_list, _ = read_workspace_files(target_files)
        warnings.extend(w_list)
        
    if custom_reproducer:
        reproducer_code = custom_reproducer.strip()
        swarm_logs.append({"role": "tester", "message": "Sử dụng mã reproducer tùy chỉnh do người dùng cung cấp.", "timestamp": time.time()})
    else:
        tester_prompt = (
            "Bạn là Tester Agent trong Swarm Debugger.\n"
            f"Lỗi cần tái hiện:\n{error_log}\n\n"
            f"Nguyên nhân gốc rễ: {root_cause}\n"
            f"Mã nguồn liên quan:\n{ctx_block}\n\n"
            "Nhiệm vụ:\n"
            "Hãy viết một file test pytest hoàn chỉnh đặt tên là `test_swarm_reproducer.py` nhằm mục đích duy nhất là kích hoạt lỗi này (test case phải fail khi chạy trên code hiện tại).\n"
            "Yêu cầu:\n"
            "- Trả về duy nhất một block code python pytest trong markdown fence.\n"
            "- Không ghi text giải thích ngoài code block."
        )
        
        client = get_azure_client()
        res_test = await Agent(AgentRole.TESTER, client).run_async(tester_prompt)
        if res_test.status != "success":
            return {"error": f"Tester Agent lỗi: {res_test.error}", "logs": swarm_logs}
            
        reproducer_code = res_test.result.strip()
        m_code = re.search(r"```(?:python)?\s*(.*?)\s*```", reproducer_code, re.DOTALL)
        if m_code:
            reproducer_code = m_code.group(1).strip()
            
    sandbox_res = _run_reproducer_in_sandbox(reproducer_code)
    failure_kind = _sandbox_failure_kind(sandbox_res)
    reproducer_failed = failure_kind == "test_failed"
    
    if reproducer_failed:
        swarm_logs.append({"role": "tester", "message": "Xác nhận: File test reproducer đã kích hoạt lỗi thành công (FAIL as expected).", "timestamp": time.time()})
    elif failure_kind == "infra":
        warnings.append("Reproducer sandbox lỗi hạ tầng, không coi là bug reproduced.")
        swarm_logs.append({"role": "tester", "message": "Cảnh báo: Sandbox không chạy được reproducer do lỗi hạ tầng. Vẫn tiếp tục quy trình vá lỗi.", "timestamp": time.time()})
    else:
        swarm_logs.append({"role": "tester", "message": "Cảnh báo: File test reproducer không fail trên code hiện tại. Vẫn tiếp tục quy trình vá lỗi.", "timestamp": time.time()})
        
    return {
        "status": "success",
        "reproducer_code": reproducer_code,
        "reproducer_failed": reproducer_failed,
        "failure_kind": failure_kind,
        "sandbox_output": sandbox_res,
        "logs": swarm_logs,
        "warnings": warnings
    }


async def swarm_step_coder(error_log: str, suggested_approach: str, target_files: list[str], reproducer_code: str) -> dict:
    """Bước 3: Coder đề xuất bản vá lỗi unified diff."""
    swarm_logs = [{"role": "coder", "message": "Bắt đầu chặng 3: Coder sinh bản vá unified diff.", "timestamp": time.time()}]
    warnings = []
    
    ctx_block = ""
    if target_files:
        ctx_block, w_list, _ = read_workspace_files(target_files)
        warnings.extend(w_list)
        
    coder_prompt = (
        "Bạn là Coder Agent trong Swarm Debugger.\n"
        f"Lỗi: {error_log}\n"
        f"Hướng đề xuất của Architect: {suggested_approach}\n"
        f"Mã nguồn hiện tại:\n{ctx_block}\n\n"
        f"File test reproducer:\n{reproducer_code}\n\n"
        "Nhiệm vụ:\n"
        "Hãy viết một bản vá unified diff để sửa lỗi. Hãy đảm bảo bản vá sửa chính xác nguyên nhân lỗi và làm cho file test reproducer vượt qua (PASS).\n"
        "Hãy trả về kết quả định dạng:\n"
        "## Patch\n"
        "```diff\n"
        "[nội dung diff]\n"
        "```"
    )
    
    client = get_azure_client()
    res_code = await Agent(AgentRole.CODE_A, client).run_async(coder_prompt)
    if res_code.status != "success":
        return {"error": f"Coder Agent lỗi: {res_code.error}", "logs": swarm_logs}
        
    return {
        "status": "success",
        "patch": res_code.result,
        "logs": swarm_logs,
        "warnings": warnings
    }


def swarm_step_apply_and_test(target_files: list[str], patch: str, reproducer_code: str = "") -> dict:
    """Bước 4: Áp dụng bản vá thử nghiệm và chạy lại reproducer test."""
    swarm_logs = [{"role": "coder", "message": "Bắt đầu chặng 4: Áp dụng và chạy thử bản vá.", "timestamp": time.time()}]
    
    success, msg, backup_path = _extract_and_apply_patch(files=target_files, fix_text=patch)
    backup_paths = [backup_path] if backup_path else []
    
    patch_applied_successfully = success
    test_passed_after_patch = False
    failure_kind = "not_run"
    sandbox_res2 = {}
    
    if success:
        swarm_logs.append({"role": "coder", "message": "Bản vá đã được áp dụng. Đang chạy lại reproducer test trong sandbox...", "timestamp": time.time()})
        sandbox_res2 = _run_reproducer_in_sandbox(reproducer_code or "def test_placeholder():\n    assert True\n")
        failure_kind = _sandbox_failure_kind(sandbox_res2)
        test_passed_after_patch = failure_kind == "none"
        
        if test_passed_after_patch:
            swarm_logs.append({"role": "coder", "message": "Chúc mừng! File test reproducer đã PASS thành công sau khi áp dụng bản vá.", "timestamp": time.time()})
        else:
            label = "lỗi hạ tầng sandbox" if failure_kind == "infra" else "test reproducer vẫn không pass"
            swarm_logs.append({"role": "coder", "message": f"Thất bại: {label}. Chi tiết:\n{sandbox_res2.get('stdout','')}\n{sandbox_res2.get('stderr','')}", "timestamp": time.time()})
            _restore_session_backups(backup_paths)
            swarm_logs.append({"role": "coder", "message": "Đã rollback bản vá lỗi thử nghiệm.", "timestamp": time.time()})
    else:
        swarm_logs.append({"role": "coder", "message": f"Thất bại: Không thể apply bản vá. Chi tiết: {msg}", "timestamp": time.time()})
        
    return {
        "status": "success" if (patch_applied_successfully and test_passed_after_patch) else "failed",
        "patch_applied_successfully": patch_applied_successfully,
        "test_passed_after_patch": test_passed_after_patch,
        "failure_kind": failure_kind,
        "backup_paths": backup_paths,
        "sandbox_output": sandbox_res2,
        "logs": swarm_logs,
        "message": msg
    }


async def swarm_step_reviewer(target_files: list[str], patch: str) -> dict:
    """Bước 5: Thẩm định chất lượng bản vá bằng Reviewer Agent."""
    swarm_logs = [{"role": "reviewer", "message": "Bắt đầu chặng 5: Thẩm định chất lượng và độ an toàn.", "timestamp": time.time()}]
    warnings = []
    
    ctx_block = ""
    if target_files:
        ctx_block, w_list, _ = read_workspace_files(target_files)
        warnings.extend(w_list)
        
    reviewer_prompt = (
        "Bạn là Reviewer Agent trong Swarm Debugger.\n"
        f"Mã nguồn ban đầu:\n{ctx_block}\n"
        f"Bản vá đã áp dụng:\n{patch}\n\n"
        "Nhiệm vụ:\n"
        "Hãy đánh giá chất lượng, độ an toàn và side-effects của bản vá.\n"
        "Trả về JSON block thuần định dạng:\n"
        "{\n"
        "  \"verdict\": \"approve\" | \"reject\",\n"
        "  \"summary\": \"Tóm tắt review\"\n"
        "}"
    )
    
    client = get_azure_client()
    res_rev = await Agent(AgentRole.REVIEWER, client).run_async(reviewer_prompt)
    
    reviewer_verdict = "reject"
    reviewer_summary = "Lỗi gọi Reviewer Agent"
    
    if res_rev.status == "success":
        rev_data = _parse_json_object(res_rev.result)
        reviewer_verdict = str(rev_data.get("verdict", "reject")).strip().lower()
        if reviewer_verdict not in {"approve", "reject"}:
            warnings.append(f"Reviewer verdict không hợp lệ: {reviewer_verdict!r}; mặc định reject")
            reviewer_verdict = "reject"
        reviewer_summary = rev_data.get("summary", "No summary")
        swarm_logs.append({"role": "reviewer", "message": f"Kết quả thẩm định: {reviewer_verdict.upper()}. Nhận xét: {reviewer_summary}", "timestamp": time.time()})
    else:
        swarm_logs.append({"role": "reviewer", "message": f"Lỗi gọi Reviewer Agent: {res_rev.error}. Tự động reject bản vá.", "timestamp": time.time()})
        
    return {
        "status": "success",
        "verdict": reviewer_verdict,
        "summary": reviewer_summary,
        "logs": swarm_logs,
        "warnings": warnings
    }


async def swarm_debug(error_log: str, files: Optional[list[str]] = None) -> dict:
    """Kích hoạt đội ngũ Multi-Agent Swarm để chẩn đoán, vá lỗi và review bản vá."""
    swarm_logs = []
    warnings = []
    
    arch_res = await swarm_step_architect(error_log, files)
    if "error" in arch_res:
        return arch_res
    swarm_logs.extend(arch_res["logs"])
    warnings.extend(arch_res.get("warnings", []))
    
    root_cause = arch_res["root_cause"]
    suggested_approach = arch_res["suggested_approach"]
    target_files = arch_res["target_files"]
    
    tester_res = await swarm_step_tester(error_log, root_cause, target_files)
    if "error" in tester_res:
        return tester_res
    swarm_logs.extend(tester_res["logs"])
    warnings.extend(tester_res.get("warnings", []))
    if tester_res.get("failure_kind") == "infra":
        return {
            "error": "Reproducer sandbox lỗi hạ tầng; dừng swarm_debug để tránh apply/rollback sai.",
            "logs": swarm_logs,
            "warnings": warnings,
            "tester_result": tester_res,
        }
    
    reproducer_code = tester_res["reproducer_code"]
    
    coder_res = await swarm_step_coder(error_log, suggested_approach, target_files, reproducer_code)
    if "error" in coder_res:
        return coder_res
    swarm_logs.extend(coder_res["logs"])
    warnings.extend(coder_res.get("warnings", []))
    
    patch_meta = coder_res["patch"]
    
    apply_res = swarm_step_apply_and_test(target_files, patch_meta, reproducer_code)
    swarm_logs.extend(apply_res["logs"])
    
    patch_applied_successfully = apply_res["patch_applied_successfully"]
    test_passed_after_patch = apply_res["test_passed_after_patch"]
    backup_paths = apply_res["backup_paths"]
    
    reviewer_verdict = "rejected"
    reviewer_summary = "Không có bản vá hợp lệ hoặc test suite không pass."
    
    if patch_applied_successfully and test_passed_after_patch:
        rev_res = await swarm_step_reviewer(target_files, patch_meta)
        swarm_logs.extend(rev_res["logs"])
        warnings.extend(rev_res.get("warnings", []))
        
        reviewer_verdict = rev_res["verdict"]
        reviewer_summary = rev_res["summary"]
        
        if reviewer_verdict != "approve":
            _restore_session_backups(backup_paths)
            swarm_logs.append({"role": "coordinator", "message": "Quy trình kết thúc: Bản vá bị Reviewer từ chối (Đã rollback).", "timestamp": time.time()})
        else:
            _cleanup_session_backups(backup_paths)
            swarm_logs.append({"role": "coordinator", "message": "Quy trình hoàn tất thành công: Bản vá được áp dụng và nghiệm thu chính thức!", "timestamp": time.time()})
    else:
        swarm_logs.append({"role": "coordinator", "message": "Quy trình kết thúc thất bại: Bản vá không hợp lệ hoặc không vượt qua kiểm thử.", "timestamp": time.time()})
        
    return {
        "success": (reviewer_verdict == "approve"),
        "root_cause": root_cause,
        "suggested_approach": suggested_approach,
        "patch": patch_meta if patch_applied_successfully else None,
        "reproducer_test": reproducer_code,
        "logs": swarm_logs,
        "reviewer_verdict": reviewer_verdict,
        "reviewer_summary": reviewer_summary,
        "warnings": warnings
    }
