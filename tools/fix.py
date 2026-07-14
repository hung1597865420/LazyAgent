"""
tools/fix.py — Code fixing and auto-remediation tools.
Ported from support_tools.py.
"""
import asyncio
import logging
from typing import Optional
from agents import Agent, AgentRole
from config import get_azure_client
from .core import (
    _assemble_context,
    append_lesson,
    _result_meta,
    _extract_and_apply_patch,
    _extract_and_save_lesson,
    _run_tests,
    _restore_session_backups,
    _cleanup_session_backups,
)
from .review import panel_review

_log = logging.getLogger("harness.fix")


def _safe_status(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("ascii", "replace").decode("ascii"))


async def suggest_fix(
    error: str,
    files: Optional[list[str]] = None,
    code: Optional[str] = None,
    context: Optional[str] = None,
) -> dict:
    """Debugger tự động chữa lành và sửa lỗi."""
    warnings = []
    # Auto-ingest new raw wiki files
    try:
        import llmwiki_tool
        await llmwiki_tool.wiki_ingest()
    except Exception:
        pass

    if not files and not code and not context:
        return {"error": "Cần cung cấp thông tin lỗi qua `files`, `code` hoặc `context`", "warnings": warnings}

    ctx, assemble_warnings = _assemble_context(files=files, code=code, context=context)
    warnings.extend(assemble_warnings)

    task = f"Lỗi/bug cần fix:\n{error}"
    client = get_azure_client()
    agent = Agent(AgentRole.DEBUGGER, client)
    
    attempts = 0
    max_attempts = 3
    last_error_log = ""
    patch_applied = False
    patch_msg = ""
    result = None
    session_backups = []
    
    while attempts < max_attempts:
        attempts += 1
        current_task = task
        if attempts > 1:
            current_task += f"\n\n[Hệ thống tự động chạy test và phát hiện lỗi của bản vá trước]\nChi tiết lỗi test:\n{last_error_log}\n\nHãy phân tích lỗi này và đưa ra phương án vá lỗi (unified diff) mới chính xác và hoàn chỉnh hơn để bài test pass."
            
        _safe_status(f"[Harness] Debugger self-healing attempt {attempts}/{max_attempts}...")
        result = await agent.run_async(current_task, ctx)
        
        if result.status != "success":
            _restore_session_backups(session_backups)
            return {
                "fix": None,
                "agent": _result_meta(result),
                "warnings": warnings,
                "patch_applied": False,
                "patch_message": f"Agent debugger thất bại tại attempt {attempts}: {result.error}"
            }
            
        success, msg, bpath = _extract_and_apply_patch(files, result.result)
        if bpath:
            session_backups.append(bpath)
            
        if not success:
            if not files:
                patch_applied = False
                patch_msg = "Không áp dụng bản vá vì đang ở chế độ code-only"
                break
            last_error_log = f"Không thể áp dụng bản vá (diff): {msg}"
            _safe_status(f"[Harness] Attempt {attempts} failed: {last_error_log}")
            continue
            
        test_success, test_log = _run_tests()
        if test_success:
            _safe_status(f"[Harness] Self-healing succeeded at attempt {attempts}! Test suite passed.")
            patch_applied = True
            patch_msg = f"{msg} (Vá thành công sau {attempts} lần vá và bài test pass)"
            append_lesson({
                "source": "suggest_fix",
                "title": (error or "suggest_fix lesson").splitlines()[0][:160],
                "outcome": "fixed",
                "files": files or [],
                "error_signature": (error or "")[:500],
                "fix_summary": patch_msg,
                "tags": ["suggest_fix", "self_healing"],
            })
            asyncio.create_task(_extract_and_save_lesson(error, files, result.result or ""))
            _cleanup_session_backups(session_backups)
            break
        else:
            _safe_status(f"[Harness] Attempt {attempts} failed tests. Restoring backup and retrying...")
            _restore_session_backups(session_backups)
            last_error_log = test_log
            
    if not patch_applied:
        _restore_session_backups(session_backups)
        return {
            "fix": result.result if result else None,
            "agent": _result_meta(result) if result else {},
            "warnings": warnings,
            "patch_applied": False,
            "patch_message": f"Tất cả {max_attempts} lượt vá lỗi đều không vượt qua bài test. Lỗi cuối cùng:\n{last_error_log}"
        }

    return {
        "fix": result.result if result else None,
        "agent": _result_meta(result) if result else {},
        "warnings": warnings,
        "patch_applied": patch_applied,
        "patch_message": patch_msg
    }


async def security_autofix(files: Optional[list[str]] = None) -> dict:
    """Tự động phát hiện và vá các lỗi bảo mật nghiêm trọng."""
    if not files:
        return {"error": "Cần cung cấp danh sách file để quét bảo mật"}
        
    review_res = await panel_review(files=files)
    if "error" in review_res:
        return {"error": f"Lỗi quét bảo mật: {review_res['error']}"}
        
    findings = review_res.get("findings", [])
    sec_findings = [
        f for f in findings
        if f.get("severity", "").lower() in ("critical", "high")
        and (
            f.get("category", "").lower() in ("injection", "xss", "auth", "secrets", "validation")
            or "security" in (
                f.get("found_by") if isinstance(f.get("found_by"), list)
                else ([f.get("found_by")] if f.get("found_by") else [])
            )
        )
    ]
    
    if not sec_findings:
        return {
            "message": "Không phát hiện lỗi bảo mật nghiêm trọng nào (Critical/High). Code của bạn an toàn!",
            "findings_count": 0,
            "fixed": []
        }
        
    fixed_list = []
    errors = []
    
    for f in sec_findings:
        f_file = f.get("file")
        f_line = f.get("line")
        f_issue = f.get("issue", "")
        
        _safe_status(f"[Harness Security] Đang tự động vá lỗi bảo mật: {f_issue} tại {f_file}:{f_line}...")
        fix_res = await suggest_fix(
            error=f"Lỗi bảo mật phát hiện: {f_issue}\nTại file: {f_file} dòng {f_line}.\nHãy vá lỗi này đảm bảo các quy chuẩn bảo mật (SQL injection, XSS, secrets exposure...).",
            files=[f_file] if f_file else None
        )
        
        if fix_res.get("patch_applied"):
            fixed_list.append({
                "file": f_file,
                "line": f_line,
                "issue": f_issue,
                "message": fix_res.get("patch_message")
            })
        else:
            errors.append({
                "file": f_file,
                "line": f_line,
                "issue": f_issue,
                "error": fix_res.get("patch_message") or "Vá lỗi thất bại"
            })
            
    return {
        "message": f"Quét bảo mật hoàn tất. Đã sửa thành công {len(fixed_list)}/{len(sec_findings)} lỗi bảo mật.",
        "findings_count": len(sec_findings),
        "fixed": fixed_list,
        "failed": errors
    }
