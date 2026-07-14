"""
tools/review.py — Reviewer tools.
Ported from support_tools.py.
"""
import asyncio
import json
import os
from typing import Optional
from agents import Agent, AgentRole, AgentResult
from config import get_azure_client
from .core import (
    _git_diff,
    _calculate_review_hash,
    _export_review_report,
    _assemble_context,
    _parse_json_findings,
    _parse_json_object,
    _result_meta,
    get_runtime_path,
    MAX_TOTAL_BYTES
)

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_FAST_CTX_BYTES = 80_000   # context cap cho fast mode


def _panel_integrity_timeout(default_timeout: float) -> float:
    try:
        configured = float(os.getenv("HARNESS_PANEL_INTEGRITY_TIMEOUT", "75"))
    except (TypeError, ValueError):
        configured = 75.0
    if configured <= 0:
        configured = 75.0
    return min(default_timeout, max(0.05, configured))


def _dedup_findings_local(findings: list[dict]) -> list[dict]:
    """Dedupe nhanh bằng Python khi không cần Synthesizer.
    Giữ finding có severity cao nhất cho mỗi (file, line) key.
    triage: nếu conflict auto_fix + ask_user → ask_user (conservative).
    """
    seen: dict[tuple, dict] = {}
    for f in findings:
        key = (str(f.get("file", "")), str(f.get("line", "")), str(f.get("issue", ""))[:60])
        existing = seen.get(key)
        if existing is None:
            seen[key] = dict(f)
        else:
            existing_by = existing.get("found_by", [])
            new_by = f.get("found_by", [])
            if isinstance(existing_by, str):
                existing_by = [existing_by]
            if isinstance(new_by, str):
                new_by = [new_by]
            existing["found_by"] = list(dict.fromkeys(existing_by + new_by))
            if _SEVERITY_ORDER.get(str(f.get("severity","low")).lower(), 4) < \
               _SEVERITY_ORDER.get(str(existing.get("severity","low")).lower(), 4):
                existing["severity"] = f["severity"]
            # triage conflict: auto_fix + ask_user → ask_user (conservative)
            if f.get("triage") == "ask_user" or existing.get("triage") == "ask_user":
                existing["triage"] = "ask_user"
            elif f.get("triage") == "auto_fix":
                existing.setdefault("triage", "auto_fix")
    result = list(seen.values())
    result.sort(key=lambda f: _SEVERITY_ORDER.get(str(f.get("severity", "low")).lower(), 4))
    return result


def _found_by_set(v) -> set:
    """Chuẩn hoá found_by thành tập reviewer nguyên tử."""
    if isinstance(v, list):
        return {str(x) for x in v if x}
    return {str(v)} if v else set()


def _check_anti_consensus(results: list, raw_findings: list[dict]) -> list[str]:
    """Cảnh báo khi panel đồng thuận quá mức — có thể bỏ sót issue thật."""
    warnings: list[str] = []
    success_count = sum(1 for r in results if r.status == "success")
    if success_count < 2:
        return warnings
    # Tất cả thành công nhưng không ai tìm thấy gì
    if success_count == len(results) and not raw_findings:
        warnings.append(
            "Anti-consensus: cả 3 reviewer đều báo clean — hãy double-check thủ công "
            "nếu diff lớn hoặc logic phức tạp."
        )
        return warnings
    # Union tất cả reviewer thực sự đóng góp findings
    contributors: set[str] = set()
    for f in raw_findings:
        contributors |= _found_by_set(f.get("found_by"))
    contributors.discard("")
    if len(contributors) == 1 and success_count >= 2:
        only = next(iter(contributors))
        warnings.append(
            f"Anti-consensus: chỉ có '{only}' báo findings, "
            f"{success_count - 1} reviewer kia không tìm thấy gì — "
            "xem xét findings này cẩn thận hơn."
        )
    return warnings


async def panel_review(
    files: Optional[list[str]] = None,
    diff: Optional[str] = None,
    code: Optional[str] = None,
    focus: Optional[str] = None,
    staged: bool = False,
    since_commit: str = "",
    fast: bool = False,
    agent_timeout: float = 90.0,
) -> dict:
    """Reviewer + Tester + Security soi code parallel → Synthesizer dedupe/merge."""
    warnings: list[str] = []
    if agent_timeout <= 0:
        return {"error": "agent_timeout phải là số dương lớn hơn 0", "warnings": warnings}
    ctx_cap = _FAST_CTX_BYTES if fast else MAX_TOTAL_BYTES

    # Auto-ingest new raw wiki files
    try:
        import llmwiki_tool
        await llmwiki_tool.wiki_ingest()
    except Exception:
        pass

    # Auto-detect git diff nếu không có input thủ công
    if not files and not diff and not code and (staged or since_commit):
        git_diff, git_err = _git_diff(staged=staged, since_commit=since_commit)
        if git_err:
            warnings.append(f"git diff: {git_err}")
        if git_diff:
            diff = git_diff
        elif not git_err:
            return {"error": "Không có thay đổi nào để review", "warnings": warnings}

    if not files and not diff and not code:
        return {"error": "Không có gì để review — cần ít nhất một trong: files, diff, code, staged, since_commit", "warnings": warnings}

    # Caching check
    cache_dir = get_runtime_path(".harness_cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_hash = _calculate_review_hash(
        files=files, diff=diff, code=code, focus=focus,
        staged=staged, since_commit=since_commit,
        fast=fast, agent_timeout=agent_timeout, cache_schema=2,
    )
    cache_file = os.path.join(cache_dir, f"review_{cache_hash}.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
            cached_data["cached"] = True
            _export_review_report(cached_data)
            return cached_data
        except Exception:
            try:
                os.remove(cache_file)
            except Exception:
                pass

    ctx, file_warnings = _assemble_context(files=files, diff=diff, code=code, total_cap=ctx_cap)
    warnings.extend(file_warnings)
    if fast and ctx_cap < MAX_TOTAL_BYTES:
        warnings.append(f"fast=True: context bị cap ở {ctx_cap//1000}KB để tăng tốc")
    if not ctx:
        return {"error": "Không có gì để review — cần ít nhất một trong: files, diff, code, staged, since_commit", "warnings": warnings}

    client = get_azure_client()

    # Pre-pass summarizer: khi ctx > 200KB, SYNTHESIZER/pro tier tóm gọn xuống ~100KB
    # để MANAGER/pro-3 rảnh cho ask_codebase.
    # trước khi đưa vào 3 codex reviewer song song
    _PREPASS_THRESHOLD = 200_000
    ctx_bytes = len(ctx.encode("utf-8", errors="replace"))
    if not fast and ctx_bytes > _PREPASS_THRESHOLD:
        try:
            from config import ROLE_TIMEOUTS
            prepass_system_prompt = (
                "Bạn là Code Review Pre-processor. Tóm tắt diff/code lớn cho review panel.\n"
                "GIỮ LẠI:\n"
                "- Mọi thay đổi liên quan security (auth, input validation, SQL, crypto, secret, env)\n"
                "- Logic phân nhánh phức tạp (nested if/loop, error handling, state mutation)\n"
                "- API endpoint và schema thay đổi\n"
                "- Thay đổi dependency (import, require, package)\n"
                "- Tên file và line number chính xác cho mỗi đoạn giữ lại\n"
                "BỎ: pure style/whitespace/comment-only changes.\n"
            )
            prepass_prompt = (
                f"Target: ~100KB (hiện {ctx_bytes//1024}KB). Trả về text tóm tắt thuần.\n"
            )
            prepass_t = min(ROLE_TIMEOUTS.get(AgentRole.SYNTHESIZER.value, 180.0), agent_timeout)
            prepass_result = await asyncio.wait_for(
                Agent(AgentRole.SYNTHESIZER, client, system_prompt=prepass_system_prompt).run_async(
                    prepass_prompt, ctx, timeout=prepass_t, timeout_retries=0, use_spares=False
                ),
                timeout=prepass_t + 2,
            )
            if prepass_result.status == "success" and prepass_result.result:
                orig_kb = len(ctx) // 1024
                ctx = prepass_result.result[:MAX_TOTAL_BYTES]
                warnings.append(
                    f"Pre-pass summarizer: {orig_kb}KB → {len(ctx)//1024}KB ({prepass_result.model_used})"
                )
        except Exception as e:
            warnings.append(f"Pre-pass summarizer lỗi: {e} — dùng context gốc ({len(ctx)//1024}KB)")

    task = "Review code trong CONTEXT." + (f" Tập trung vào: {focus}" if focus else "")
    panel = [AgentRole.REVIEWER, AgentRole.SECURITY, AgentRole.TESTER]

    async def _run_with_timeout(role: AgentRole) -> AgentResult:
        # Per-role timeout từ config; agent_timeout là cap cứng nếu caller truyền vào (< default)
        from config import ROLE_TIMEOUTS
        _DEFAULT_TIMEOUT = 90.0
        role_t = ROLE_TIMEOUTS.get(role.value, agent_timeout)
        if agent_timeout != _DEFAULT_TIMEOUT:
            role_t = min(role_t, agent_timeout)
        try:
            return await asyncio.wait_for(
                Agent(role, client).run_async(
                    task, ctx, json_mode=True, timeout=role_t, timeout_retries=0, use_spares=False
                ),
                timeout=role_t + 2,
            )
        except asyncio.TimeoutError:
            warnings.append(f"{role.value}: timeout sau {role_t:.0f}s — bỏ qua")
            return AgentResult(
                agent_id=f"timeout-{role.value}",
                agent_role=role,
                model_used="timeout",
                task=task[:100],
                result="",
                duration_ms=int(role_t * 1000),
                status="error",
                error=f"Timeout sau {role_t:.0f}s",
            )

    results = await asyncio.gather(*[_run_with_timeout(role) for role in panel])

    raw_findings: list[dict] = []
    panel_meta: list[dict] = []
    for r in results:
        panel_meta.append(_result_meta(r))
        if r.status == "success":
            for f in _parse_json_findings(r.result):
                f["found_by"] = r.agent_role.value
                if f.get("triage") not in ("auto_fix", "ask_user"):
                    f["triage"] = "ask_user"
                raw_findings.append(f)

    warnings.extend(_check_anti_consensus(results, raw_findings))

    if all(r.status == "error" for r in results):
        return {"error": "Cả 3 reviewer đều lỗi", "panel": panel_meta, "warnings": warnings}

    if not raw_findings:
        res = {
            "verdict": "approve", "summary": "Panel không tìm thấy issue nào.",
            "findings": [], "panel": panel_meta, "warnings": warnings,
        }
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        _export_review_report(res)
        return res

    # INTEGRITY agent: chạy sau 3 reviewer, nhận findings + code làm input
    # Vừa tìm race condition/transaction gap mới, vừa synthesize toàn panel
    merged: dict = {}
    integrity_ok = False
    if fast:
        warnings.append("fast=True: integrity synthesis skipped — race/transaction gaps không được review")
    else:
        try:
            from config import ROLE_TIMEOUTS
            _DEFAULT_TIMEOUT = 90.0
            integrity_t = ROLE_TIMEOUTS.get(AgentRole.INTEGRITY.value, agent_timeout)
            if agent_timeout != _DEFAULT_TIMEOUT:
                integrity_t = min(integrity_t, agent_timeout)
            integrity_t = _panel_integrity_timeout(integrity_t)
            integrity_input = json.dumps(
                {"code_context": ctx[:8000], "panel_findings": raw_findings},
                ensure_ascii=False,
            )
            integrity_result = await asyncio.wait_for(
                Agent(AgentRole.INTEGRITY, client).run_async(
                    "Review data integrity và synthesize toàn bộ findings từ panel.",
                    integrity_input,
                    json_mode=True,
                    timeout=integrity_t,
                    timeout_retries=0,
                    use_spares=False,
                ),
                timeout=integrity_t + 2,
            )
            panel_meta.append(_result_meta(integrity_result))
            if integrity_result.status == "success":
                parsed = _parse_json_object(integrity_result.result) or {}
                if parsed:  # chỉ dùng khi parse ra object hợp lệ (kể cả findings=[])
                    merged = parsed
                    integrity_ok = True
                    for f in merged.get("findings", []):
                        if f.get("triage") not in ("auto_fix", "ask_user"):
                            f["triage"] = "ask_user"
        except Exception as e:
            warnings.append(f"Integrity agent error/timeout: {e} — falling back to local deduplication")

    if not integrity_ok:
        deduped = _dedup_findings_local(raw_findings)
        has_blocker = any(
            str(f.get("severity", "")).lower() in ("critical", "high") for f in deduped
        )
        merged = {
            "verdict": "fix_first" if has_blocker else "approve",
            "summary": f"{len(deduped)} findings (deduped locally — integrity synthesis unavailable).",
            "findings": deduped,
            "degraded": True,  # integrity agent không chạy được → race/transaction gaps chưa review
        }

    merged["panel"] = panel_meta
    merged["warnings"] = warnings

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    _export_review_report(merged)

    return merged


async def consult(
    question: str,
    files: Optional[list[str]] = None,
    context: Optional[str] = None,
) -> dict:
    """Analyzer (deep reasoning) tư vấn."""
    ctx, warnings = _assemble_context(files=files, context=context)
    result = await Agent(AgentRole.ANALYZER, get_azure_client()).run_async(question, ctx)
    return {
        "advice": result.result if result.status == "success" else None,
        "agent": _result_meta(result), "warnings": warnings,
    }


async def alt_implementation(
    spec: str,
    files: Optional[list[str]] = None,
    context: Optional[str] = None,
) -> dict:
    """Sinh 2 phương án implementation song song."""
    ctx, warnings = _assemble_context(files=files, context=context)
    client = get_azure_client()
    res_a, res_b = await asyncio.gather(
        Agent(AgentRole.CODE_A, client).run_async(spec, ctx),
        Agent(AgentRole.CODE_B, client).run_async(spec, ctx),
    )
    return {
        "approach_a": {"implementation": res_a.result or None, **_result_meta(res_a)},
        "approach_b": {"implementation": res_b.result or None, **_result_meta(res_b)},
        "warnings": warnings,
    }
