"""
tools/swarm.py — Multi-Agent Swarm, ask_codebase, and quick_task.
Ported from support_tools.py.
"""
import os
import re
import time
import uuid
import json
from typing import Optional
from config import WORKSPACE_ROOT, get_azure_client
from agents import Agent, AgentRole
from .core import (
    read_workspace_files,
    _load_relevant_wiki_context,
    _parse_json_object,
    _result_meta,
    _extract_and_apply_patch,
    _restore_session_backups,
    _cleanup_session_backups,
    run_in_sandbox,
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


def _ask_codebase_timeout() -> float:
    try:
        return max(5.0, float(os.getenv("HARNESS_ASK_CODEBASE_TIMEOUT", "45")))
    except (TypeError, ValueError):
        return 45.0


def _ask_codebase_context_cap() -> int:
    try:
        return max(20_000, int(os.getenv("HARNESS_ASK_CODEBASE_CONTEXT_BYTES", "250000")))
    except (TypeError, ValueError):
        return 250_000


def _ask_codebase_use_spares() -> bool:
    return os.getenv("HARNESS_ASK_CODEBASE_USE_SPARES", "1").strip().lower() not in {"0", "false", "no", "off"}


def _ask_codebase_timeout_retries() -> int:
    try:
        return max(0, int(os.getenv("HARNESS_ASK_CODEBASE_TIMEOUT_RETRIES", "0")))
    except (TypeError, ValueError):
        return 0


_ASK_STOPWORDS = {
    "the", "and", "for", "with", "what", "where", "how", "why", "file", "code",
    "this", "that", "from", "into", "are", "you", "can", "could", "would",
    "cho", "cua", "của", "trong", "ngoai", "ngoài", "nay", "này", "kia",
    "mot", "một", "cac", "các", "nhung", "những", "chua", "chưa", "tren",
    "trên", "duoi", "dưới", "lam", "làm", "viet", "viết", "chay", "chạy",
    "xem", "check", "thu", "thử", "sao", "nhu", "như", "nao", "nào",
    "dang", "đang", "duoc", "được", "khong", "không", "co", "có",
}


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
    stripped = line.strip()
    if re.search(r"\b(class|def|async def|function|const|let|var|export|interface|type)\b", stripped):
        score += 3
    if re.search(r"\b(route|router|endpoint|handler|controller|service|repository|schema|model)\b", haystack):
        score += 2
    if re.search(r"\b(todo|fixme|error|raise|except|catch|warning|fallback|timeout)\b", haystack):
        score += 1
    if stripped.startswith(("#", "//", "/*", "*")):
        score -= 1
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
    selected = ranked[:10]
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
    if len(text) < 40:
        return False
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
    return bool(re.search(r"`?[\w./\\-]+:\d+`?", text))


async def ask_codebase(
    question: str,
    files: Optional[list[str]] = None,
    index_md: Optional[str] = None,
) -> dict:
    """Hỏi đáp trên lượng code lớn (model 1M context).

    Khi `files` không được cung cấp, tự động dùng CodebaseIndex để tìm các file liên quan nhất.
    """
    warnings = []
    if not files and not index_md:
        try:
            from .codebase_index import get_index
            idx = get_index()
            hits = idx.search(question, top_k=20)
            seen: dict[str, float] = {}
            for h in hits:
                p = h.get("path", "")
                if p and p not in seen:
                    seen[p] = h.get("score", 0.0)
            files = list(seen.keys())[:10]
            if files:
                warnings.append(f"Auto-selected {len(files)} file(s) via CodebaseIndex for: {question[:80]}")
        except Exception as e:
            warnings.append(f"CodebaseIndex lookup failed: {e}")
    if not files and not index_md:
        return {"error": "Cần cung cấp danh sách file qua `files` hoặc nội dung điều hướng qua `index_md`", "warnings": warnings}
        
    ctx_blocks = []
    loaded_count = 0

    wiki_ctx = _load_relevant_wiki_context("\n".join([question, "\n".join(files or []), index_md or ""]))
    if wiki_ctx:
        ctx_blocks.append(f"=== PROJECT WIKI CONTEXT (SELECTIVE) ===\n{wiki_ctx}")
    
    if files:
        file_ctx, file_warns, file_loaded = read_workspace_files(
            files,
            total_cap=min(MAX_TOTAL_BYTES_BIG, _ask_codebase_context_cap()),
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

    timeout_s = _ask_codebase_timeout()
    task = (
        f"{question}\n\n"
        "Trả lời trực tiếp bằng Markdown tiếng Việt. Bắt buộc trích dẫn `file:line` cho claim về code. "
        "Không trả JSON wrapper trừ khi user hỏi rõ JSON."
    )
    result = await Agent(AgentRole.MANAGER, get_azure_client()).run_async(
        task, ctx, max_output_tokens=4096, timeout=timeout_s,
        timeout_retries=_ask_codebase_timeout_retries(),
        use_spares=_ask_codebase_use_spares(),
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
        }

    return {
        "answer": answer_text,
        "files_loaded": loaded_count,
        "agent": _result_meta(result), "warnings": warnings,
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
    if not ctx_files:
        matches = re.findall(r"file\s+\"([^\"]+\.py)\",\s+line\s+(\d+)", error_log.lower())
        for fpath, line in matches:
            rel_p = os.path.relpath(fpath, WORKSPACE_ROOT)
            if not rel_p.startswith("..") and os.path.exists(os.path.join(WORKSPACE_ROOT, rel_p)):
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
            full_tf = os.path.realpath(os.path.join(WORKSPACE_ROOT, tf_str))
            try:
                outside = os.path.commonpath([full_tf, os.path.realpath(WORKSPACE_ROOT)]) != os.path.realpath(WORKSPACE_ROOT)
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
        m_code = re.search(r"```python\s*(.*?)\s*```", reproducer_code, re.DOTALL)
        if m_code:
            reproducer_code = m_code.group(1).strip()
            
    sandbox_res = _run_reproducer_in_sandbox(reproducer_code)
    reproducer_failed = sandbox_res["status"] == "success" and "failed" in (sandbox_res["stdout"] + sandbox_res["stderr"]).lower()
    
    if reproducer_failed:
        swarm_logs.append({"role": "tester", "message": "Xác nhận: File test reproducer đã kích hoạt lỗi thành công (FAIL as expected).", "timestamp": time.time()})
    else:
        swarm_logs.append({"role": "tester", "message": "Cảnh báo: File test reproducer không fail trên code hiện tại. Vẫn tiếp tục quy trình vá lỗi.", "timestamp": time.time()})
        
    return {
        "status": "success",
        "reproducer_code": reproducer_code,
        "reproducer_failed": reproducer_failed,
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
    
    success, msg, backup_path = _extract_and_apply_patch(target_files, patch)
    backup_paths = [backup_path] if backup_path else []
    
    patch_applied_successfully = success
    test_passed_after_patch = False
    sandbox_res2 = {}
    
    if success:
        swarm_logs.append({"role": "coder", "message": "Bản vá đã được áp dụng. Đang chạy lại reproducer test trong sandbox...", "timestamp": time.time()})
        sandbox_res2 = _run_reproducer_in_sandbox(reproducer_code or "def test_placeholder():\n    assert True\n")
        test_passed_after_patch = (sandbox_res2["status"] == "success" and "failed" not in (sandbox_res2["stdout"] + sandbox_res2["stderr"]).lower() and "passed" in (sandbox_res2["stdout"] + sandbox_res2["stderr"]).lower())
        
        if test_passed_after_patch:
            swarm_logs.append({"role": "coder", "message": "Chúc mừng! File test reproducer đã PASS thành công sau khi áp dụng bản vá.", "timestamp": time.time()})
        else:
            swarm_logs.append({"role": "coder", "message": f"Thất bại: Test reproducer vẫn không pass. Chi tiết:\n{sandbox_res2.get('stdout','')}\n{sandbox_res2.get('stderr','')}", "timestamp": time.time()})
            _restore_session_backups(backup_paths)
            swarm_logs.append({"role": "coder", "message": "Đã rollback bản vá lỗi thử nghiệm.", "timestamp": time.time()})
    else:
        swarm_logs.append({"role": "coder", "message": f"Thất bại: Không thể apply bản vá. Chi tiết: {msg}", "timestamp": time.time()})
        
    return {
        "status": "success" if (patch_applied_successfully and test_passed_after_patch) else "failed",
        "patch_applied_successfully": patch_applied_successfully,
        "test_passed_after_patch": test_passed_after_patch,
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
        reviewer_verdict = rev_data.get("verdict", "reject")
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
