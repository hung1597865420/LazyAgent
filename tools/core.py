"""
tools/core.py — Core utilities, shared helpers and sandbox runners.
Ported from support_tools.py.
"""
import asyncio
import json
import logging
import os
import re
import subprocess
import hashlib
import sys
import shutil
import uuid
import math
import threading
from pathlib import Path
from typing import Optional
from agents import Agent, AgentRole, AgentResult
from config import WORKSPACE_ROOT, get_azure_client

_log = logging.getLogger("harness.core")

# ── Helper functions for CLI execution and LLM analysis ────────────────────────

def _run_cmd_safe(cmd: list[str], timeout: float = 15.0, cwd: str = WORKSPACE_ROOT) -> tuple[int, str, str]:
    """Chạy câu lệnh CLI an toàn, bắt timeout."""
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=timeout
        )
        return r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", f"TimeoutExpired: Command {cmd} timed out after {timeout} seconds."
    except FileNotFoundError:
        return -2, "", f"FileNotFoundError: Command {cmd[0] if cmd else ''} not found on PATH"
    except Exception as e:
        return -3, "", f"Exception: {e}"

async def _llm_analyze(prompt: str, context: str = "", role: AgentRole = AgentRole.WORKER) -> str:
    """Gọi Agent để phân tích văn bản/ngữ cảnh."""
    client = get_azure_client()
    agent = Agent(role, client)
    res = await agent.run_async(prompt, context)
    return res.result if res.status == "success" else f"Error from Agent: {res.error}"

# ── Limits cho file context ───────────────────────────────────────────────────
MAX_FILE_BYTES        = 200_000     # per file
MAX_TOTAL_BYTES       = 400_000     # tổng cho review/consult/fix tools
MAX_TOTAL_BYTES_BIG   = 2_500_000   # ask_codebase — manager có 1M context

# ── Git diff helper ───────────────────────────────────────────────────────────

def _git_diff(
    staged: bool = False,
    since_commit: str = "",
    cwd: str = WORKSPACE_ROOT,
) -> tuple[str, str]:
    """Chạy git diff và trả về (diff_text, error_msg)."""
    if since_commit:
        cmd = ["git", "diff", f"{since_commit}..HEAD", "--unified=5"]
    elif staged:
        cmd = ["git", "diff", "--cached", "--unified=5"]
    else:
        cmd = ["git", "diff", "HEAD", "--unified=5"]

    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True,
            text=True, encoding="utf-8", timeout=15,
        )
    except FileNotFoundError:
        return "", "git không có trên PATH"
    except subprocess.TimeoutExpired:
        return "", "git diff timeout (>15s)"

    if r.returncode != 0:
        err = r.stderr.strip()
        if "not a git repository" in err.lower():
            return "", "Không phải git repository"
        if since_commit and "unknown revision" in err.lower():
            return "", f"Commit không tồn tại: {since_commit}"
        return "", err or f"git exit {r.returncode}"

    diff = r.stdout.strip()
    if not diff:
        label = "staged" if staged else (f"since {since_commit}" if since_commit else "HEAD")
        return "", f"Không có thay đổi ({label})"

    # Giới hạn kích thước — diff quá lớn sẽ làm tràn context
    if len(diff.encode()) > MAX_TOTAL_BYTES:
        diff = diff.encode()[:MAX_TOTAL_BYTES].decode(errors="replace")
        return diff, f"[!] Diff bị cắt ở {MAX_TOTAL_BYTES} bytes"

    return diff, ""


# ── Workspace file access ─────────────────────────────────────────────────────

def read_workspace_files(
    paths: list[str],
    total_cap: int = MAX_TOTAL_BYTES,
    number_lines: bool = True,
) -> tuple[str, list[str], int]:
    """Đọc files theo path tương đối từ WORKSPACE_ROOT."""
    if isinstance(paths, str):
        paths = [paths]
    elif not isinstance(paths, (list, tuple)):
        return "", [f"Kiểu dữ liệu files không hợp lệ: {type(paths)}. Yêu cầu danh sách file."], 0

    blocks: list[str] = []
    warnings: list[str] = []
    total = 0
    loaded = 0

    for p in paths:
        if not p or not isinstance(p, str) or not p.strip():
            warnings.append(f"{p!r}: path không hợp lệ — bỏ qua")
            continue
        try:
            full = os.path.realpath(os.path.join(WORKSPACE_ROOT, p))
        except (ValueError, OSError) as e:
            warnings.append(f"{p}: không thể resolve path — {e}")
            continue
        try:
            outside = os.path.commonpath([full, os.path.realpath(WORKSPACE_ROOT)]) != os.path.realpath(WORKSPACE_ROOT)
        except ValueError:
            outside = True  # different drives on Windows
        if outside:
            warnings.append(f"{p}: nằm ngoài WORKSPACE_ROOT — bỏ qua")
            continue
        if not os.path.isfile(full):
            warnings.append(f"{p}: không tồn tại")
            continue

        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                data = f.read(MAX_FILE_BYTES + 1)
        except OSError as e:
            warnings.append(f"{p}: lỗi đọc file — {e}")
            continue

        if len(data) > MAX_FILE_BYTES:
            data = data[:MAX_FILE_BYTES]
            warnings.append(f"{p}: bị cắt ở {MAX_FILE_BYTES} bytes")

        if number_lines:
            data = "\n".join(
                f"{i + 1}\t{line}" for i, line in enumerate(data.splitlines())
            )
        block = f"=== FILE: {p} ===\n{data}"

        block_bytes = len(block.encode("utf-8", errors="replace"))
        if total + block_bytes > total_cap:
            warnings.append(f"{p}: bỏ qua — vượt tổng dung lượng context ({total_cap} bytes)")
            continue
        total += block_bytes
        blocks.append(block)
        loaded += 1

    return "\n\n".join(blocks), warnings, loaded


def _get_active_workspace() -> str:
    """Runtime workspace — không freeze theo project đầu tiên khi MCP reuse process."""
    return os.path.abspath(
        os.getenv("WORKSPACE_ROOT")
        or os.getenv("CLAUDE_PROJECT_DIR")
        or "."
    )


def _wiki_roots() -> list[tuple[str, str]]:
    """Trả về [(wiki_dir, scope), ...] gồm local (runtime) và global (~/.claude/llmwiki/).
    Local ưu tiên (đứng trước), dedupe key = sub/fname."""
    roots = []
    local_wiki = os.path.join(_get_active_workspace(), "llmwiki", "wiki")
    if os.path.isdir(local_wiki):
        roots.append((local_wiki, "local"))
    global_wiki = os.path.join(os.path.expanduser("~"), ".claude", "llmwiki", "wiki")
    if os.path.isdir(global_wiki):
        roots.append((global_wiki, "global"))
    return roots


_WIKI_PAGE_CACHE: dict[str, object] = {"signature": None, "pages": []}
_WIKI_CACHE_LOCK = threading.RLock()


def _wiki_pages_cached() -> list[dict]:
    signature = []
    for wiki_root, scope in _wiki_roots():
        for sub in ["concepts", "entities"]:
            subdir = os.path.join(wiki_root, sub)
            if not os.path.isdir(subdir):
                continue
            for fname in sorted(os.listdir(subdir)):
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(subdir, fname)
                try:
                    st = os.stat(fpath)
                    signature.append((fpath, scope, sub, st.st_mtime_ns, st.st_size))
                except OSError:
                    continue

    sig_tuple = tuple(signature)
    with _WIKI_CACHE_LOCK:
        if _WIKI_PAGE_CACHE.get("signature") == sig_tuple:
            return list(_WIKI_PAGE_CACHE.get("pages", []))

    pages = []
    seen: set[str] = set()
    for fpath, scope, sub, _mtime, _size in signature:
        fname = os.path.basename(fpath)
        key = f"{sub}/{fname}"
        if key in seen:
            continue
        seen.add(key)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                pages.append({"scope": scope, "type": sub, "name": fname[:-3], "filename": fname, "content": content})
        except Exception as _e:
            _log.debug("Wiki load skip %s: %s", fname, _e)

    with _WIKI_CACHE_LOCK:
        _WIKI_PAGE_CACHE["signature"] = sig_tuple
        _WIKI_PAGE_CACHE["pages"] = pages
    return list(pages)


def _load_wiki_context_all() -> str:
    wiki_blocks = []
    for page in _wiki_pages_cached():
        sub = page["type"]
        wiki_blocks.append(f"=== WIKI {sub.upper().rstrip('S')} [{page['scope']}]: {page['name']} ===\n{page['content']}")
    return "\n\n".join(wiki_blocks)


def _load_relevant_wiki_context(target_text: str) -> str:
    if not target_text or not target_text.strip():
        return _load_wiki_context_all()

    words = re.findall(r"\b[a-zA-Z0-9_]{3,}\b", target_text.lower())
    stopwords = {
        "and", "the", "with", "for", "this", "that", "from", "cho", "cua", "trong",
        "nay", "mot", "cac", "nhung", "chua", "tren", "duoi", "lam", "viet", "chay",
        "code", "file", "folder", "directory", "error", "warning"
    }
    keywords = set(w for w in words if w not in stopwords)
    if not keywords:
        return _load_wiki_context_all()

    matched_pages: list[dict] = []
    seen: set[str] = set()
    for page in _wiki_pages_cached():
        key = f"{page['type']}/{page['filename']}"
        if key in seen:
            continue
        seen.add(key)
        content = str(page["content"])
        content_lower = content.lower()
        fname_lower = str(page["filename"]).lower()
        score = sum((5 if kw in fname_lower else 0) + content_lower.count(kw) for kw in keywords)
        if score > 0:
            matched_pages.append({**page, "score": score})

    if not matched_pages:
        return ""

    matched_pages.sort(key=lambda x: x["score"], reverse=True)
    return "\n\n".join(
        f"=== WIKI {p['type'].upper().rstrip('S')} [{p['scope']}] (score:{p['score']}): {p['name']} ===\n{p['content']}"
        for p in matched_pages[:5]
    )


def _assemble_context(
    files: Optional[list[str]] = None,
    diff: Optional[str] = None,
    code: Optional[str] = None,
    context: Optional[str] = None,
    total_cap: int = MAX_TOTAL_BYTES,
) -> tuple[str, list[str]]:
    parts: list[str] = []
    warnings: list[str] = []
    
    # Collect text to match wiki keywords
    target_text_parts = []
    if diff:
        target_text_parts.append(diff)
    if code:
        target_text_parts.append(code)
    if context:
        target_text_parts.append(context)
    if files:
        target_text_parts.extend(files)
        for fpath in files[:3]:
            try:
                full_path = os.path.realpath(os.path.join(WORKSPACE_ROOT, fpath))
                if os.path.isfile(full_path):
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        target_text_parts.append(f.read(1000))
            except Exception:
                pass
    target_text = "\n".join(target_text_parts)
    
    # Auto-inject Wiki Context selectively
    wiki_ctx = _load_relevant_wiki_context(target_text)
    if wiki_ctx:
        parts.append(f"=== PROJECT WIKI CONTEXT (SELECTIVE) ===\n{wiki_ctx}")
        
    if files:
        file_block, file_warns, _ = read_workspace_files(files, total_cap)
        warnings = file_warns
        if file_block:
            parts.append(file_block)
    if diff:
        parts.append(f"=== DIFF ===\n{diff}")
    if code:
        numbered = "\n".join(f"{i + 1}\t{ln}" for i, ln in enumerate(code.splitlines()))
        parts.append(f"=== CODE (inline) ===\n{numbered}")
    if context:
        parts.append(f"=== ADDITIONAL CONTEXT ===\n{context}")
    return "\n\n".join(parts), warnings


# ── JSON parsing (chịu được model trả markdown fence) ────────────────────────

def _parse_json_findings(raw: str) -> list[dict]:
    obj = _parse_json_object(raw)
    findings = obj.get("findings", []) if isinstance(obj, dict) else []
    return findings if isinstance(findings, list) else []


def _parse_json_object(raw: str) -> dict:
    if not isinstance(raw, str):
        return {}
    cleaned = raw.lstrip("\ufeff").strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        pass
        
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
            
    s, e = cleaned.find("{"), cleaned.rfind("}") + 1
    if s != -1 and e > s:
        try:
            return json.loads(cleaned[s:e])
        except json.JSONDecodeError:
            pass
            
    # Fallback to search candidates
    for candidate in re.findall(r"\{.*?\}", cleaned, re.DOTALL):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
            
    return {}


def _result_meta(r: AgentResult) -> dict:
    return {
        "role": r.agent_role.value, "model": r.model_used,
        "status": r.status, "duration_ms": r.duration_ms,
        **({"error": r.error} if r.error else {}),
    }


# ── Helper functions for caching, report export, and patching ─────────────────

def _calculate_review_hash(
    files: Optional[list[str]],
    diff: Optional[str],
    code: Optional[str],
    focus: Optional[str],
    staged: bool,
    since_commit: str,
) -> str:
    hasher = hashlib.sha256()
    if files:
        for fpath in sorted(files):
            hasher.update(fpath.encode(errors="replace"))
            try:
                full_path = os.path.realpath(os.path.join(WORKSPACE_ROOT, fpath))
                if os.path.isfile(full_path):
                    with open(full_path, "rb") as f:
                        while chunk := f.read(8192):
                            hasher.update(chunk)
            except Exception:
                pass
    for val in [diff, code, focus, str(staged), since_commit]:
        if val:
            val_str = val if isinstance(val, str) else str(val)
            hasher.update(val_str.encode(errors="replace"))
    return hasher.hexdigest()


def _export_review_report(result: dict) -> None:
    report_path = os.path.join(WORKSPACE_ROOT, "REVIEW_REPORT.md")
    verdict = result.get("verdict", "unknown").upper()
    summary = result.get("summary", "Không có tóm tắt.")
    findings = result.get("findings", [])
    badge = "🟢 APPROVE" if verdict == "APPROVE" else "🔴 FIX FIRST"
    
    lines = [
        "# Agent Harness - Báo cáo Review Code tự động",
        f"\n## Kết luận: **{badge}**",
        f"\n### Tóm tắt:\n{summary}",
        "\n## Chi tiết các Findings",
    ]
    if not findings:
        lines.append("\n✅ Không tìm thấy lỗi nào!")
    else:
        lines.append("\n| Tập tin | Dòng | Mức độ | Nhóm | Lỗi phát hiện | Gợi ý sửa lỗi | Phát hiện bởi |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for f in findings:
            file_name = f.get("file", "N/A")
            line_no = f.get("line") or "N/A"
            severity = f.get("severity", "low").upper()
            category = f.get("category", "N/A")
            issue = f.get("issue", "N/A").replace("\n", " ")
            suggested_fix = f.get("suggested_fix", "N/A").replace("\n", "<br>")
            found_by = ", ".join(f.get("found_by", [])) if isinstance(f.get("found_by"), list) else str(f.get("found_by", "N/A"))
            lines.append(f"| {file_name} | {line_no} | {severity} | {category} | {issue} | {suggested_fix} | {found_by} |")
            
    lines.append("\n## Chi tiết cuộc họp Panel")
    lines.append("| Agent Role | Model sử dụng | Trạng thái | Thời gian phản hồi |")
    lines.append("| :--- | :--- | :--- | :--- |")
    for p in result.get("panel", []):
        role = p.get("role", "N/A").upper()
        model = p.get("model", "N/A")
        status = "✅" if p.get("status") == "success" else "❌"
        duration = f"{p.get('duration_ms', 0)/1000:.2f}s"
        lines.append(f"| {role} | {model} | {status} | {duration} |")
        
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        _log.warning("Lỗi xuất báo cáo review: %s", e)


def _extract_and_apply_patch(files: Optional[list[str]], fix_text: str) -> tuple[bool, str, Optional[str]]:
    m = re.search(r"```(?:diff|patch)?\s*(.*?)\s*```", fix_text, re.DOTALL)
    if m:
        diff_content = m.group(1).strip()
    else:
        if "--- " in fix_text and "+++ " in fix_text and "@@ " in fix_text:
            diff_content = fix_text.strip()
        else:
            return False, "Không tìm thấy block diff/patch (fenced hoặc raw) trong câu trả lời của agent", None
    if not diff_content:
        return False, "Block diff rỗng", None
        
    target_file = None
    for line in diff_content.splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            parts = line.split()
            if len(parts) >= 2:
                fpath = parts[1]
                if fpath.startswith("a/") or fpath.startswith("b/"):
                    fpath = fpath[2:]
                if fpath in ("dev/null", "/dev/null"):
                    continue
                full = os.path.realpath(os.path.join(WORKSPACE_ROOT, fpath))
                try:
                    outside = os.path.commonpath([full, os.path.realpath(WORKSPACE_ROOT)]) != os.path.realpath(WORKSPACE_ROOT)
                except ValueError:
                    outside = True
                if not outside:
                    target_file = fpath
                    break
                        
    if not target_file and files:
        for f in files:
            full = os.path.realpath(os.path.join(WORKSPACE_ROOT, f))
            try:
                outside = os.path.commonpath([full, os.path.realpath(WORKSPACE_ROOT)]) != os.path.realpath(WORKSPACE_ROOT)
            except ValueError:
                outside = True
            if not outside and os.path.isfile(full):
                target_file = f
                break
                
    if not target_file:
        return False, "Không xác định được file đích cần vá (patch)", None
        
    full_target_path = os.path.realpath(os.path.join(WORKSPACE_ROOT, target_file))
    is_new_file = not os.path.exists(full_target_path)
    
    if is_new_file:
        target_lines = []
    else:
        try:
            with open(full_target_path, "r", encoding="utf-8") as f:
                target_lines = f.readlines()
        except Exception as e:
            return False, f"Không thể đọc file {target_file}: {e}", None
        
    hunks = []
    current_hunk = None
    diff_lines = diff_content.splitlines()
    i = 0
    while i < len(diff_lines):
        line = diff_lines[i]
        if line.startswith("@@"):
            m_hunk = re.match(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@", line)
            if m_hunk:
                old_start = int(m_hunk.group(1))
                old_len = int(m_hunk.group(2)) if m_hunk.group(2) else 1
                new_start = int(m_hunk.group(3))
                new_len = int(m_hunk.group(4)) if m_hunk.group(4) else 1
                current_hunk = {
                    "old_start": old_start, "old_len": old_len,
                    "new_start": new_start, "new_len": new_len,
                    "lines": []
                }
                hunks.append(current_hunk)
        elif current_hunk is not None:
            if line.startswith("-") or line.startswith("+") or line.startswith(" "):
                if not line.startswith("@@"):
                    current_hunk["lines"].append(line)
        i += 1
        
    if not hunks:
        return False, "Không parse được hunk @@ nào từ unified diff", None
        
    hunks.sort(key=lambda h: h["old_start"], reverse=True)
    backup_path = full_target_path + ".bak"
    try:
        if is_new_file:
            with open(backup_path, "w", encoding="utf-8") as f:
                f.write("__NEW_FILE__")
        else:
            with open(backup_path, "w", encoding="utf-8") as f:
                f.writelines(target_lines)
    except Exception as e:
        return False, f"Không tạo được file backup {target_file}.bak: {e}", None
        
    modified_lines = list(target_lines)
    for hunk in hunks:
        old_idx = hunk["old_start"] - 1
        expected_deletes = [line[1:] for line in hunk["lines"] if line.startswith("-") or line.startswith(" ")]
        best_match_idx = -1
        
        if is_new_file or not modified_lines:
            best_match_idx = 0
        else:
            min_offset = 999999
            search_range = range(max(0, old_idx - 50), min(len(modified_lines), old_idx + 50))
            for start_offset in search_range:
                match = True
                for k, expected_line in enumerate(expected_deletes):
                    if start_offset + k >= len(modified_lines):
                        match = False
                        break
                    actual_line = modified_lines[start_offset + k].rstrip("\r\n")
                    if actual_line != expected_line.rstrip("\r\n") and actual_line.strip() != expected_line.strip():
                        match = False
                        break
                if match:
                    offset = abs(start_offset - old_idx)
                    if offset < min_offset:
                        min_offset = offset
                        best_match_idx = start_offset
                        
        if best_match_idx == -1:
            try:
                if is_new_file:
                    if os.path.exists(full_target_path):
                        os.remove(full_target_path)
                else:
                    with open(full_target_path, "w", encoding="utf-8") as f:
                        f.writelines(target_lines)
                if os.path.isfile(backup_path):
                    os.remove(backup_path)
            except Exception:
                pass
            return False, f"Không thể apply hunk tại dòng {hunk['old_start']} của file {target_file}: Context mismatch", None
            
        replacement = []
        for line in hunk["lines"]:
            if line.startswith("+") or line.startswith(" "):
                line_content = line[1:]
                if not line_content.endswith("\n"):
                    line_content += "\n"
                replacement.append(line_content)
        num_to_delete = len([line for line in hunk["lines"] if line.startswith("-") or line.startswith(" ")])
        modified_lines[best_match_idx : best_match_idx + num_to_delete] = replacement
        
    try:
        if is_new_file:
            parent_dir = os.path.dirname(full_target_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
                
        with open(full_target_path, "w", encoding="utf-8") as f:
            f.writelines(modified_lines)
        return True, f"Đã vá thành công file {target_file} (Backup lưu tại {target_file}.bak)", backup_path
    except Exception as e:
        try:
            if is_new_file:
                if os.path.exists(full_target_path):
                    os.remove(full_target_path)
            else:
                with open(full_target_path, "w", encoding="utf-8") as f:
                    f.writelines(target_lines)
            if os.path.isfile(backup_path):
                os.remove(backup_path)
        except Exception:
            pass
        return False, f"Không thể ghi đè file vá: {e}", None


def _is_git_repo() -> bool:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=WORKSPACE_ROOT, capture_output=True, text=True
        )
        return r.returncode == 0 and r.stdout.strip() == "true"
    except Exception:
        return False


def _run_tests() -> tuple[bool, str]:
    test_script = os.path.join(WORKSPACE_ROOT, "smoke_test.py")
    if not os.path.isfile(test_script):
        return True, "Không tìm thấy smoke_test.py để chạy thử, mặc định pass"
    try:
        r = subprocess.run(
            [sys.executable or "python", "smoke_test.py"],
            cwd=WORKSPACE_ROOT,
            capture_output=True,
            text=True,
            timeout=30
        )
        success = (r.returncode == 0)
        output = (r.stdout or "") + "\n" + (r.stderr or "")
        return success, output.strip()
    except Exception as e:
        return False, f"Lỗi thực thi test suite: {e}"


def _run_tests_in_dir(target_dir: str, python_bin: str | None = None) -> tuple[bool, str]:
    if python_bin and (not os.path.isfile(python_bin) or not os.access(python_bin, os.X_OK)):
        return False, f"invalid_python_bin: {python_bin} không tồn tại hoặc không executable"
    test_script = os.path.join(target_dir, "smoke_test.py")
    if not os.path.isfile(test_script):
        return True, "Không tìm thấy smoke_test.py để chạy thử, mặc định pass"
    interpreter = python_bin or sys.executable or "python"
    try:
        r = subprocess.run(
            [interpreter, "smoke_test.py"],
            cwd=target_dir,
            capture_output=True,
            text=True,
            timeout=30
        )
        success = (r.returncode == 0)
        output = (r.stdout or "") + "\n" + (r.stderr or "")
        return success, output.strip()
    except Exception as e:
        return False, f"Lỗi thực thi test suite: {e}"


def _apply_patch_in_dir(target_dir: str, patch_content: str, files: Optional[list[str]]) -> tuple[bool, str]:
    m = re.search(r"```(?:diff|patch)?\s*(.*?)\s*```", patch_content, re.DOTALL)
    if m:
        diff_content = m.group(1).strip()
    else:
        if "--- " in patch_content and "+++ " in patch_content and "@@ " in patch_content:
            diff_content = patch_content.strip()
        else:
            return False, "Không tìm thấy block diff/patch (fenced hoặc raw) trong câu trả lời của agent"
            
    if not diff_content:
        return False, "Block diff rỗng"
        
    patch_file = os.path.join(target_dir, "patch.diff")
    try:
        with open(patch_file, "w", encoding="utf-8") as f:
            f.write(diff_content)
    except Exception as e:
        return False, f"Không thể ghi file diff tạm thời: {e}"
        
    try:
        r = subprocess.run(
            ["git", "apply", "--ignore-whitespace", "patch.diff"],
            cwd=target_dir, capture_output=True, text=True
        )
        if os.path.exists(patch_file):
            os.remove(patch_file)
            
        if r.returncode == 0:
            return True, "Áp dụng bản vá thành công"
        else:
            return False, f"git apply thất bại: {r.stderr.strip()}"
    except Exception as e:
        if os.path.exists(patch_file):
            os.remove(patch_file)
        return False, f"Lỗi khi chạy git apply: {e}"


def _apply_and_test_isolated(patch_content: str, files: Optional[list[str]]) -> tuple[bool, str, str]:
    repo_path = Path(WORKSPACE_ROOT).resolve()
    uid = uuid.uuid4().hex[:8]
    branch = f"orca-fix-{uid}"
    wt_path = repo_path / f".harness_worktree_{uid}"
    
    msg = ""
    test_log = ""
    
    try:
        r_branch = subprocess.run(
            ["git", "branch", branch],
            cwd=str(repo_path), capture_output=True, text=True
        )
        if r_branch.returncode != 0:
            return False, f"Không thể tạo nhánh git tạm thời: {r_branch.stderr.strip()}", ""
            
        r_wt = subprocess.run(
            ["git", "worktree", "add", "--detach", str(wt_path)],
            cwd=str(repo_path), capture_output=True, text=True
        )
        if r_wt.returncode != 0:
            return False, f"Không thể tạo git worktree: {r_wt.stderr.strip()}", ""
            
        patch_ok, patch_msg = _apply_patch_in_dir(str(wt_path), patch_content, files)
        if not patch_ok:
            return False, f"Vá lỗi thất bại trong worktree cô lập: {patch_msg}", ""
            
        test_ok, test_log = _run_tests_in_dir(str(wt_path))
        if not test_ok:
            msg = "Vá lỗi thành công nhưng không pass test suite"
            return False, msg, test_log
            
        r_main_dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_path), capture_output=True, text=True
        )
        if r_main_dirty.returncode == 0 and r_main_dirty.stdout.strip():
            return False, "Workspace chính đang dirty — không copy từ worktree để tránh ghi đè thay đổi local", test_log

        r_status = subprocess.run(
            ["git", "status", "--porcelain", "-z"],
            cwd=str(wt_path), capture_output=True
        )
        if r_status.returncode == 0:
            raw = r_status.stdout.decode("utf-8", errors="surrogateescape")
            entries = raw.split("\x00")
            safe_root = repo_path.resolve()
            for entry in entries:
                if not entry.strip() or len(entry) < 4:
                    continue
                xy = entry[:2]
                rel_file = entry[3:].strip()
                rel = Path(rel_file)
                if rel.is_absolute() or ".." in rel.parts:
                    continue
                dest_file = (safe_root / rel).resolve()
                if safe_root not in dest_file.parents and dest_file != safe_root:
                    continue
                src_file = wt_path / rel_file
                x_code = xy[0].strip()
                y_code = xy[1].strip()
                is_delete = (x_code == "D" or y_code == "D")
                if is_delete:
                    if dest_file.exists() and not dest_file.is_symlink():
                        dest_file.unlink()
                elif src_file.exists() and not src_file.is_symlink() and not dest_file.is_symlink():
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dest_file)
                        
        msg = "Vá lỗi thành công và vượt qua bộ kiểm thử trong worktree cô lập"
        return True, msg, test_log
        
    except Exception as e:
        return False, f"Lỗi không mong muốn trong worktree cô lập: {e}", ""
        
    finally:
        try:
            if wt_path.exists():
                subprocess.run(["git", "worktree", "remove", "--force", str(wt_path)], cwd=str(repo_path), capture_output=True)
        except Exception:
            pass
            
        try:
            subprocess.run(["git", "branch", "-D", branch], cwd=str(repo_path), capture_output=True)
        except Exception:
            pass


def _restore_session_backups(backup_paths: list[str]):
    for bak_path in backup_paths:
        if not os.path.isfile(bak_path):
            continue
        full_path = bak_path[:-4]
        try:
            with open(bak_path, "r", encoding="utf-8", errors="ignore") as bf:
                content = bf.read().strip()
            if content == "__NEW_FILE__":
                if os.path.isfile(full_path):
                    os.remove(full_path)
                os.remove(bak_path)
                rel = os.path.relpath(full_path, WORKSPACE_ROOT)
                _log.info("[Harness] Removed new file %s created during run", rel)
            else:
                shutil.copy2(bak_path, full_path)
                os.remove(bak_path)
                rel = os.path.relpath(full_path, WORKSPACE_ROOT)
                _log.info("[Harness] Restored %s from backup", rel)
        except Exception:
            pass

def _cleanup_session_backups(backup_paths: list[str]):
    for bak_path in backup_paths:
        try:
            if os.path.isfile(bak_path):
                os.remove(bak_path)
        except Exception:
            pass


async def _extract_and_save_lesson(error: str, files: Optional[list[str]], patch: str) -> None:
    try:
        from agents import Agent, AgentRole
        from config import get_azure_client
        
        client = get_azure_client()
        system_prompt = (
            "Bạn là Wiki Ingestion Agent. Nhiệm vụ của bạn là đúc rút kinh nghiệm sửa lỗi (Lesson Learned) "
            "từ lỗi gốc và bản vá thành công vừa qua của dự án.\n\n"
            "Hãy viết một trang wiki concept mới định dạng Markdown với Front Matter:\n"
            "---\n"
            "title: Tên bài học ngắn gọn, rõ ràng (bắt đầu bằng danh từ hoặc động từ hành động)\n"
            "type: concept\n"
            "related: []\n"
            "---\n"
            "## Mô tả lỗi\n"
            "Mô tả ngắn gọn lỗi xảy ra.\n\n"
            "## Giải pháp chuẩn\n"
            "Hướng dẫn cách sửa lỗi này chuẩn.\n\n"
            "## Code ví dụ\n"
            "Cung cấp code sai và code đúng.\n\n"
            "Yêu cầu:\n"
            "- Trả về toàn bộ nội dung file markdown hoàn chỉnh.\n"
            "- Không có thêm text giải thích ngoài file markdown."
        )
        
        agent = Agent(AgentRole.WORKER, client=client, system_prompt=system_prompt)
        prompt = (
            f"Thông tin đầu vào:\n"
            f"1. Lỗi gốc: {error}\n"
            f"2. File đã sửa: {files}\n"
            f"3. Bản vá thành công:\n{patch}\n"
        )
        
        res = await agent.run_async(prompt)
        if res.status != "success" or not res.result:
            return
            
        content = res.result.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()
            
        title_match = re.search(r"title:\s*(.*?)\n", content)
        if title_match:
            title = title_match.group(1).strip()
        else:
            title = "lesson_" + str(int(asyncio.get_event_loop().time()))
            
        import unicodedata
        slug = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode('ascii').lower()
        slug = re.sub(r'[^a-z0-9_-]', '-', slug)
        slug = re.sub(r'-+', '-', slug).strip('-')
        if not slug:
            slug = "lesson"
            
        wiki_root = os.path.join(WORKSPACE_ROOT, "llmwiki", "wiki")
        concepts_dir = os.path.join(wiki_root, "concepts")
        os.makedirs(concepts_dir, exist_ok=True)
        
        filename = f"{slug}.md"
        filepath = os.path.join(concepts_dir, filename)
        
        counter = 1
        while os.path.exists(filepath):
            filepath = os.path.join(concepts_dir, f"{slug}_{counter}.md")
            counter += 1
            
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
            
        _log.info("[Harness] Đã lưu lesson wiki: wiki/concepts/%s", os.path.basename(filepath))
        
    except Exception as e:
        _log.warning("[Harness] Lỗi trích xuất lesson wiki: %s", e)


def run_in_sandbox(code: str, timeout: float = 5.0) -> dict:
    """Chạy code Python tùy ý trong một tiến trình con cô lập."""
    import tempfile
    import time

    if not isinstance(timeout, (int, float)) or not math.isfinite(float(timeout)) or float(timeout) <= 0:
        return {"status": "error", "stdout": "", "stderr": "timeout must be a positive finite number", "duration_ms": 0}
    
    temp_dir = tempfile.mkdtemp(prefix=".harness_sandbox_", dir=WORKSPACE_ROOT)
    
    with tempfile.NamedTemporaryFile(suffix=".py", dir=temp_dir, mode="w", delete=False, encoding="utf-8") as f:
        f.write(code)
        temp_path = f.name
        
    system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT", "")
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PATHEXT": os.environ.get("PATHEXT", ""),
        "SystemRoot": system_root,
        "SYSTEMROOT": system_root,
        "WINDIR": os.environ.get("WINDIR", system_root),
        "USERPROFILE": os.environ.get("USERPROFILE", ""),
        "APPDATA": os.environ.get("APPDATA", ""),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
        "TEMP": temp_dir,
        "TMP": temp_dir,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    
    start_time = time.perf_counter()
    proc = None
    stdout = ""
    stderr = ""
    status = "success"
    
    try:
        proc = subprocess.Popen(
            [sys.executable or "python", temp_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=clean_env,
            cwd=temp_dir
        )
        
        try:
            out, err = proc.communicate(timeout=timeout)
            stdout = out
            stderr = err
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            stdout = out
            stderr = err + f"\n[Harness Sandbox Error] Lỗi quá thời gian chờ (Timeout > {timeout}s)"
            status = "timeout"
            
    except Exception as e:
        status = "error"
        stderr = f"Lỗi khởi chạy sandbox: {e}"
    finally:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        try:
            if proc and proc.poll() is None:
                proc.kill()
        except Exception:
            pass
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
            
    return {
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": duration_ms
    }


class SimpleTFIDFSearch:
    def __init__(self):
        self.stopwords = {
            "and", "or", "the", "a", "an", "of", "to", "in", "is", "that", "it", "on", 
            "for", "as", "with", "by", "at", "this", "from", "into", "def", "class", 
            "import", "from", "return", "self", "assert", "try", "except"
        }
        self.documents = []
        self.df = {}
        self.num_docs = 0
        
    def _tokenize(self, text: str) -> list[str]:
        words = re.findall(r"\b[a-zA-Z0-9_]{3,}\b", text.lower())
        return [w for w in words if w not in self.stopwords]
        
    def add_document(self, doc_id: str, path: str, name: str, doc_type: str, content: str):
        tokens = self._tokenize(content)
        self.documents.append({
            "id": doc_id,
            "path": path,
            "name": name,
            "type": doc_type,
            "content": content,
            "tokens": tokens
        })
        self.num_docs += 1
        
        seen_terms = set(tokens)
        for term in seen_terms:
            self.df[term] = self.df.get(term, 0) + 1
            
    def search(self, query: str, top_k: int = 5) -> list[dict]:
        query_tokens = self._tokenize(query)
        if not query_tokens or self.num_docs == 0:
            return []
            
        query_tf = {}
        for token in query_tokens:
            query_tf[token] = query_tf.get(token, 0) + 1
            
        query_vector = {}
        for term, count in query_tf.items():
            df_term = self.df.get(term, 0)
            idf = math.log((self.num_docs + 1) / (df_term + 1)) + 1
            query_vector[term] = count * idf
            
        results = []
        for doc in self.documents:
            dot_product = 0.0
            doc_tf = {}
            for token in doc["tokens"]:
                doc_tf[token] = doc_tf.get(token, 0) + 1
                
            doc_vector = {}
            for term, count in doc_tf.items():
                df_term = self.df.get(term, 0)
                idf = math.log((self.num_docs + 1) / (df_term + 1)) + 1
                doc_vector[term] = count * idf
                
            for term, val in query_vector.items():
                if term in doc_vector:
                    dot_product += val * doc_vector[term]
                    
            query_norm = math.sqrt(sum(v**2 for v in query_vector.values()))
            doc_norm = math.sqrt(sum(v**2 for v in doc_vector.values()))
            
            score = 0.0
            if query_norm > 0 and doc_norm > 0:
                score = dot_product / (query_norm * doc_norm)
                
            if score > 0:
                results.append({
                    "score": round(score, 4),
                    "path": doc["path"],
                    "name": doc["name"],
                    "type": doc["type"],
                    "content_snippet": doc["content"][:200] + "..."
                })
                
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]


def build_ast_call_graph() -> dict:
    import ast
    graph = {
        "nodes": [],
        "edges": []
    }
    
    added_nodes = set()
    added_edges = set()
    
    def add_node(node_id, label, node_type, file_path):
        if node_id not in added_nodes:
            added_nodes.add(node_id)
            graph["nodes"].append({
                "id": node_id,
                "label": label,
                "type": node_type,
                "file": file_path
            })
            
    def add_edge(source, target, edge_type):
        edge_key = f"{source}->{target}"
        if edge_key not in added_edges:
            added_edges.add(edge_key)
            graph["edges"].append({
                "source": source,
                "target": target,
                "type": edge_type
            })

    py_files = []
    for r_dir, _, files_in_dir in os.walk(WORKSPACE_ROOT):
        if any(p in r_dir for p in [".git", "node_modules", ".harness_worktree", ".gemini", ".claude"]):
            continue
        for f in files_in_dir:
            if f.endswith(".py"):
                py_files.append(os.path.join(r_dir, f))
                
    for fpath in py_files:
        rel_path = os.path.relpath(fpath, WORKSPACE_ROOT)
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                tree = ast.parse(f.read())
        except Exception:
            continue
            
        current_class = None
        current_func = None
        
        class CallGraphVisitor(ast.NodeVisitor):
            def visit_ClassDef(self, node):
                nonlocal current_class, current_func
                prev_class = current_class
                current_class = node.name
                
                class_id = f"{rel_path}::{node.name}"
                add_node(class_id, node.name, "class", rel_path)
                
                self.generic_visit(node)
                current_class = prev_class
                
            def visit_FunctionDef(self, node):
                nonlocal current_class, current_func
                prev_func = current_func
                
                func_name = f"{current_class}.{node.name}" if current_class else node.name
                func_id = f"{rel_path}::{func_name}"
                current_func = func_id
                
                add_node(func_id, func_name, "function", rel_path)
                if current_class:
                    add_edge(f"{rel_path}::{current_class}", func_id, "contains")
                    
                self.generic_visit(node)
                current_func = prev_func
                
            def visit_Call(self, node):
                if current_func and isinstance(node.func, ast.Name):
                    target_name = node.func.id
                    add_edge(current_func, target_name, "calls")
                elif current_func and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    target_name = f"{node.func.value.id}.{node.func.attr}"
                    add_edge(current_func, target_name, "calls")
                self.generic_visit(node)
                
        CallGraphVisitor().visit(tree)
        
    try:
        graph_file = os.path.join(WORKSPACE_ROOT, ".harness_ast_graph.json")
        with open(graph_file, "w", encoding="utf-8") as f:
            json.dump(graph, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
        
    return graph
