"""
tools/testing.py — Automated testing, benchmarking, visual UI reviews, and test coverage analysis.
Ported from support_tools.py.
"""
import asyncio
import os
import re
import json
import sys
import shutil
import uuid
import statistics
import subprocess
import base64
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit
from agents import Agent, AgentRole, chat_completion
from config import get_llm_client, WORKSPACE_ROOT, MODELS
from .core import (
    _assemble_context,
    read_workspace_files,
    _is_git_repo,
    _run_tests,
    _parse_json_object,
    _result_meta
)
from .ui_criteria import EXECUTIVE_COMMAND_UI_CRITERIA


async def auto_tester(files: list[str], findings: list[dict]) -> dict:
    """Tự động viết test case (pytest) dựa trên files và findings."""
    warnings = []
    if not files:
        return {"error": "Cần cung cấp danh sách file để sinh test", "warnings": warnings}
        
    ctx, assemble_warnings = _assemble_context(files=files)
    warnings.extend(assemble_warnings)
    
    findings_str = json.dumps(findings, ensure_ascii=False, indent=2)
    prompt = (
        "Bạn là Test Generator Agent. Hãy viết một file test pytest hoàn chỉnh cho các file trong context.\n"
        f"Danh sách các lỗi/gaps được phát hiện cần test:\n{findings_str}\n\n"
        "Yêu cầu:\n"
        "- Trả về duy nhất MỘT block code python pytest hoàn chỉnh (bao gồm imports, test functions, và mock data nếu cần).\n"
        "- Viết code test sạch, dễ đọc, bao phủ các trường hợp lỗi được nêu.\n"
        "- Không ghi text giải thích bên ngoài block code.\n"
        "- Hãy đặt tên file test dạng `test_auto_generated.py`."
    )
    
    client = get_llm_client()
    agent = Agent(AgentRole.CODE_A, client)
    res = await agent.run_async(prompt, ctx)
    if res.status != "success" or not res.result:
        return {"error": f"Agent test generator thất bại: {res.error}", "warnings": warnings}
        
    test_code = res.result.strip()
    m = re.search(r"```python\s*(.*?)\s*```", test_code, re.DOTALL)
    if m:
        test_code = m.group(1).strip()
    else:
        if "def test_" not in test_code:
            return {"error": "Không parse được code block python từ kết quả của agent", "warnings": warnings}
            
    if not _is_git_repo():
        test_file = os.path.join(WORKSPACE_ROOT, "test_auto_generated.py")
        bak_file = test_file + ".bak"
        is_new = not os.path.exists(test_file)
        try:
            if not is_new:
                shutil.copy2(test_file, bak_file)
            with open(test_file, "w", encoding="utf-8") as f:
                f.write(test_code)
        except Exception as e:
            return {"error": f"Không thể ghi file test: {e}", "warnings": warnings}
            
        success, test_log = _run_tests()
        if not success:
            try:
                if is_new:
                    if os.path.exists(test_file):
                        os.remove(test_file)
                else:
                    shutil.copy2(bak_file, test_file)
                    os.remove(bak_file)
            except Exception:
                pass
            return {
                "success": False,
                "message": "Sinh file test thành công nhưng chạy test suite không pass",
                "test_log": test_log,
                "test_code": test_code,
                "warnings": warnings
            }
        else:
            if os.path.exists(bak_file):
                os.remove(bak_file)
            return {
                "success": True,
                "message": "Sinh test thành công và vượt qua kiểm thử",
                "test_file": "test_auto_generated.py",
                "test_code": test_code,
                "test_log": test_log,
                "warnings": warnings
            }
            
    repo_path = Path(WORKSPACE_ROOT).resolve()
    uid = uuid.uuid4().hex[:8]
    wt_path = repo_path / f".harness_worktree_{uid}"
    
    try:
        r_wt = subprocess.run(["git", "worktree", "add", "--detach", str(wt_path)], cwd=str(repo_path), capture_output=True, text=True)
        if r_wt.returncode != 0:
            return {"error": f"Không thể tạo worktree cô lập: {r_wt.stderr.strip()}", "warnings": warnings}
        
        wt_test_file = wt_path / "test_auto_generated.py"
        with open(wt_test_file, "w", encoding="utf-8") as f:
            f.write(test_code)
            
        try:
            r_run = subprocess.run(
                [sys.executable or "python", "-m", "pytest", "test_auto_generated.py"],
                cwd=str(wt_path), capture_output=True, text=True, timeout=30
            )
            test_ok = (r_run.returncode == 0)
            test_log = r_run.stdout + "\n" + r_run.stderr
        except Exception as e:
            test_ok = False
            test_log = f"Lỗi chạy test: {e}"
            
        if not test_ok:
            return {
                "success": False,
                "message": "Bản vá test tự động fail pytest trong worktree cô lập",
                "test_log": test_log,
                "test_code": test_code,
                "warnings": warnings
            }
            
        dest_test_file = repo_path / "test_auto_generated.py"
        shutil.copy2(wt_test_file, dest_test_file)
        
        return {
            "success": True,
            "message": "Sinh test thành công và vượt qua kiểm thử trong worktree cô lập",
            "test_file": "test_auto_generated.py",
            "test_code": test_code,
            "test_log": test_log,
            "warnings": warnings
        }
        
    finally:
        try:
            if wt_path.exists():
                subprocess.run(["git", "worktree", "remove", "--force", str(wt_path)], cwd=str(repo_path), capture_output=True)
        except Exception:
            pass


def _clean_review_url(value: str, label: str) -> tuple[str, str]:
    clean = (value or "").strip()
    if not clean:
        return "", f"{label} không được để trống"
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in clean):
        return "", f"{label} chứa control character không hợp lệ"
    parsed = urlsplit(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "", f"{label} không hợp lệ. Chỉ chấp nhận URL http:// hoặc https://"
    return clean, ""


def _normalize_optional_url(value: Optional[str]) -> str:
    clean = value or ""
    for marker in ("\ufeff", "\u200b", "\u200c", "\u200d"):
        clean = clean.replace(marker, "")
    return clean.strip()


def _skip_scan_dir(path: str) -> bool:
    parts = set(Path(path).parts)
    return (
        bool(parts & {".git", "node_modules", ".gemini", ".claude", ".harness_cache"})
        or any(part.startswith(".harness_worktree_") for part in parts)
    )


async def visual_reviewer(url: str, baseline_url: Optional[str] = None) -> dict:
    """Chụp ảnh màn hình URL và audit giao diện bằng Vision LLM."""
    warnings = []
    neutral_drift = {
        "mode": "static_single_page",
        "visual_drift_applicable": False,
        "baseline_captured": False,
        "drift_detected": False,
        "visual_drift_summary": "not_applicable_without_valid_baseline",
    }
    if not url or not url.strip():
        return {"error": "Cần cung cấp URL để phân tích giao diện", "warnings": warnings, **neutral_drift}
        
    clean_url, url_error = _clean_review_url(url, "URL")
    if url_error:
        return {"error": url_error, "warnings": warnings, **neutral_drift}
    clean_base = None
    baseline_raw = _normalize_optional_url(baseline_url)
    if baseline_raw:
        clean_base, base_error = _clean_review_url(baseline_raw, "Baseline URL")
        if base_error:
            return {"error": base_error, "warnings": warnings, **neutral_drift}

    screenshot_b64 = None
    baseline_b64 = None
    capture_mode = "static_single_page"
    visual_drift_applicable = False
    
    try:
        from playwright.async_api import async_playwright  # type: ignore
        has_playwright = True
    except ImportError:
        has_playwright = False
        warnings.append("Thư viện `playwright` chưa được cài đặt. Chạy `python -m pip install -r requirements.txt` rồi `python -m playwright install chromium`.")
        
    if has_playwright:
        try:
            from playwright.async_api import async_playwright  # type: ignore
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.set_viewport_size({"width": 1280, "height": 800})
                
                await page.goto(clean_url, wait_until="networkidle", timeout=20000)
                img_bytes = await page.screenshot(full_page=False)
                if not img_bytes:
                    raise RuntimeError("current screenshot is empty")
                screenshot_b64 = base64.b64encode(img_bytes).decode("utf-8")
                capture_mode = "playwright_single_page"
                
                if clean_base:
                    try:
                        await page.goto(clean_base, wait_until="networkidle", timeout=20000)
                        base_bytes = await page.screenshot(full_page=False)
                        if not base_bytes:
                            raise RuntimeError("baseline screenshot is empty")
                        baseline_b64 = base64.b64encode(base_bytes).decode("utf-8")
                        capture_mode = "playwright_compare"
                        visual_drift_applicable = True
                    except Exception as base_error:
                        warnings.append(
                            f"Không thể capture baseline screenshot: {base_error}. "
                            "Tiếp tục audit ảnh hiện tại; visual drift không được đánh giá."
                        )
                    
                await browser.close()
        except Exception as e:
            hint = " Chạy `python -m playwright install chromium` nếu thiếu browser binary."
            warnings.append(f"Không thể capture screenshot qua playwright: {e}.{hint} Fallback sang phân tích mã nguồn.")
            has_playwright = False
            
    client = get_llm_client()
    model = MODELS.code_b
    
    system_prompt = (
        "Bạn là Visual UI Auditor Agent chuyên nghiệp.\n"
        "Nhiệm vụ của bạn là đánh giá chất lượng thiết kế giao diện (UI/UX, Responsive, Contrast, Aesthetics) từ ảnh chụp màn hình.\n"
        "Hãy dùng Executive Command design system làm tiêu chí mặc định cho UI enterprise/corporate precision. "
        "Đánh giá cả tính thẩm mỹ lẫn khả năng vận hành: hierarchy, density, palette, typography, component states, "
        "responsive, accessibility, motion, form/login behavior và visual drift.\n\n"
        f"{EXECUTIVE_COMMAND_UI_CRITERIA}\n\n"
        "Nếu được cung cấp 2 ảnh (ảnh hiện tại và ảnh gốc/baseline), hãy so sánh xem có bất kỳ sự lệch pha (visual drift), vỡ layout, lệch pixel hay không.\n"
        "Hãy trả về kết quả dưới định dạng JSON với cấu trúc:\n"
        "{\n"
        "  \"drift_detected\": true|false,\n"
        "  \"score\": 85,\n"
        "  \"design_system_score\": 85,\n"
        "  \"issues\": [\n"
        "    {\"element\": \"...\", \"criterion\": \"palette|typography|layout|responsive|motion|state_design|accessibility|visual_drift\", \"problem\": \"...\", \"severity\": \"critical|high|medium|low\", \"suggested_fix\": \"...\"}\n"
        "  ],\n"
        "  \"aesthetics_verdict\": \"Một câu tóm tắt về mặt mỹ thuật và thẩm mỹ UI\"\n"
        "}\n"
        "Chú ý: Trả về duy nhất JSON block thuần, không markdown fence."
    )
    
    messages = [
        {"role": "system", "content": system_prompt}
    ]
    
    if screenshot_b64:
        user_content = [
            {
                "type": "text",
                "text": (
                    f"URL được kiểm thử: {clean_url}\n"
                    f"Capture mode: {capture_mode}\n"
                    f"Visual drift applicable: {visual_drift_applicable}\n"
                    + (f"URL baseline: {clean_base}\n" if clean_base else "")
                    + ("Nếu visual_drift_applicable=false, không được kết luận drift so sánh baseline; chỉ audit ảnh hiện tại." if not visual_drift_applicable else "")
                ),
            },
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}}
        ]
        if baseline_b64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{baseline_b64}"}})
            
        messages.append({"role": "user", "content": user_content})
        
        try:
            res_text, model_used, _, _ = chat_completion(
                client=client,
                model=model,
                messages=messages,
                json_mode=True
            )
            audit_report = _parse_json_object(res_text)
            if not isinstance(audit_report, dict):
                audit_report = {
                    "drift_detected": False,
                    "score": 100,
                    "issues": [],
                    "aesthetics_verdict": "Không thể parse JSON từ Vision LLM.",
                    "warnings": warnings + ["Lỗi phân tích cú pháp kết quả từ LLM."]
                }
            audit_report["model_used"] = model_used
            audit_report["captured_screenshot"] = True
            audit_report["mode"] = capture_mode
            audit_report["visual_drift_applicable"] = visual_drift_applicable
            audit_report["baseline_captured"] = baseline_b64 is not None
            if not visual_drift_applicable:
                audit_report["drift_detected"] = False
                audit_report["visual_drift_summary"] = "not_applicable_without_valid_baseline"
            audit_report["warnings"] = warnings
            return audit_report
        except Exception as e:
            return {"error": f"Lỗi gọi Vision API: {e}", "warnings": warnings}
    else:
        html_files = []
        for r_dir, _, files_in_dir in os.walk(WORKSPACE_ROOT):
            if _skip_scan_dir(r_dir):
                continue
            for f in files_in_dir:
                if f.endswith(".html") or f.endswith(".css"):
                    html_files.append(os.path.relpath(os.path.join(r_dir, f), WORKSPACE_ROOT))
                    if len(html_files) >= 3:
                        break
            if len(html_files) >= 3:
                break
                
        ctx_text = ""
        if html_files:
            ctx_text, file_warns, _ = read_workspace_files(html_files[:3])
            warnings.extend(file_warns)
            
        prompt = (
            "Hãy phân tích tĩnh mã nguồn HTML/CSS sau theo Executive Command design system, "
            "để phát hiện lỗi responsive, tương phản màu sắc, typography, component state, motion, form/login behavior "
            "hoặc anti-patterns layout:\n\n"
            f"{EXECUTIVE_COMMAND_UI_CRITERIA}\n\n"
            f"URL cần phân tích: {clean_url}\n\n"
            f"Mã nguồn tham khảo:\n{ctx_text}"
        )
        
        agent = Agent(AgentRole.CODE_B, client)
        res = await agent.run_async(prompt)
        
        if res.status != "success":
            return {"error": f"Fallback audit thất bại: {res.error}", "warnings": warnings}
            
        audit_report = {
            "drift_detected": False,
            "score": 80,
            "issues": [
                {"element": "HTML/CSS Code", "problem": "Playwright chưa chụp được ảnh thực tế. Phân tích tĩnh code thấy: " + res.result[:500], "severity": "medium", "suggested_fix": "Cài playwright để có kết quả chính xác hơn"}
            ],
            "aesthetics_verdict": "Phân tích tĩnh code hoàn tất (thiếu screenshot thực tế)",
            "captured_screenshot": False,
            "mode": capture_mode,
            "visual_drift_applicable": False,
            "baseline_captured": False,
            "visual_drift_summary": "not_applicable_without_screenshot",
            "warnings": warnings,
            "agent": _result_meta(res)
        }
        return audit_report


async def benchmarker(code_a: str, code_b: str, iterations: int = 5) -> dict:
    """So sánh hiệu năng giữa hai đoạn code Python."""
    warnings = []
    if not isinstance(iterations, int) or iterations < 1:
        return {"error": "Số lần chạy kiểm thử (iterations) phải là số nguyên lớn hơn hoặc bằng 1", "warnings": warnings}
    
    def create_runner_script(user_code: str) -> str:
        return f"""
import time
import tracemalloc
import json
import sys

tracemalloc.start()
t0 = time.perf_counter()

# --- USER CODE START ---
exec({repr(user_code)}, {{}})
# --- USER CODE END ---

t1 = time.perf_counter()
peak = tracemalloc.get_traced_memory()[1]
tracemalloc.stop()

print(json.dumps({{"duration_sec": t1 - t0, "peak_mem_bytes": peak}}))
"""

    async def run_one(script_content: str) -> dict:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
            f.write(script_content)
            temp_path = f.name
            
        try:
            r = await asyncio.to_thread(
                subprocess.run,
                [sys.executable or "python", temp_path],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10
            )
            if r.returncode != 0:
                return {"error": f"Exit code {r.returncode}: {r.stderr.strip()}"}
            return json.loads(r.stdout.strip())
        except subprocess.TimeoutExpired:
            return {"error": "Timeout (>10s)"}
        except Exception as e:
            return {"error": str(e)}
        finally:
            try:
                os.remove(temp_path)
            except Exception:
                pass

    script_a = create_runner_script(code_a)
    durations_a = []
    memories_a = []
    errors_a = []
    
    for _ in range(iterations):
        res = await run_one(script_a)
        if "error" in res:
            errors_a.append(res["error"])
        else:
            durations_a.append(res["duration_sec"])
            memories_a.append(res["peak_mem_bytes"])
            
    script_b = create_runner_script(code_b)
    durations_b = []
    memories_b = []
    errors_b = []
    
    for _ in range(iterations):
        res = await run_one(script_b)
        if "error" in res:
            errors_b.append(res["error"])
        else:
            durations_b.append(res["duration_sec"])
            memories_b.append(res["peak_mem_bytes"])
            
    if errors_a or errors_b:
        err_msg = "; ".join(errors_a + errors_b)
        return {"error": f"Lỗi đo đạc hiệu năng: {err_msg}", "warnings": warnings}
        
    if not durations_a or not durations_b:
        return {"error": "Không có kết quả đo đạc nào thành công", "warnings": warnings}
        
    def calc_stats(durations, memories):
        return {
            "mean_ms": round(statistics.mean(durations) * 1000, 3),
            "min_ms": round(min(durations) * 1000, 3),
            "max_ms": round(max(durations) * 1000, 3),
            "stddev_ms": round(statistics.stdev(durations) * 1000, 3) if len(durations) > 1 else 0.0,
            "peak_mem_kb": round(statistics.mean(memories) / 1024, 2)
        }
        
    stats_a = calc_stats(durations_a, memories_a)
    stats_b = calc_stats(durations_b, memories_b)
    
    comparison = ""
    mean_a = statistics.mean(durations_a)
    mean_b = statistics.mean(durations_b)
    diff_pct = ((mean_b - mean_a) / mean_a) * 100 if mean_a > 1e-9 else 0
    if diff_pct < 0:
        comparison = f"Code B chạy nhanh hơn Code A khoảng {abs(diff_pct):.1f}%"
    else:
        comparison = f"Code A chạy nhanh hơn Code B khoảng {diff_pct:.1f}%"
            
    return {
        "iterations": iterations,
        "code_a_stats": stats_a,
        "code_b_stats": stats_b,
        "comparison": comparison,
        "warnings": warnings
    }


async def coverage_analyzer() -> dict:
    """Chạy phân tích độ bao phủ kiểm thử (test coverage) bằng cách dùng pytest và coverage.py."""
    warnings = []
    
    try:
        from .core import _run_cmd_safe
        # 1. Chạy coverage
        code, out, err = _run_cmd_safe([sys.executable, "-m", "coverage", "run", "-m", "pytest"])
        if code != 0:
            if "failed" in (out + err).lower():
                warnings.append("Một số kiểm thử bị thất bại trong quá trình đo đạc coverage.")
            else:
                warnings.append(f"Lệnh đo đạc coverage trả về mã lỗi {code}.")
        if code == 0 or "failed" in (out + err).lower() or os.path.exists(".coverage"):
            # 2. Xuất báo cáo JSON
            code_json, out_json, err_json = _run_cmd_safe([sys.executable, "-m", "coverage", "json", "-o", ".harness_coverage.json"])
            if code_json == 0:
                cov_path = os.path.join(WORKSPACE_ROOT, ".harness_coverage.json")
                if os.path.isfile(cov_path):
                    with open(cov_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    try:
                        os.remove(cov_path)
                    except Exception:
                        pass
                        
                    totals = data.get("totals", {})
                    files_cov = {}
                    for fpath, fdetails in data.get("files", {}).items():
                        files_cov[fpath] = {
                            "percent_covered": round(fdetails.get("summary", {}).get("percent_covered", 0), 2),
                            "missing_lines": fdetails.get("missing_lines", [])
                        }
                        
                    return {
                        "coverage_percent": round(totals.get("percent_covered", 0), 2),
                        "total_lines": totals.get("num_statements", 0),
                        "covered_lines": totals.get("covered_lines", 0),
                        "missing_lines_count": totals.get("missing_lines", 0),
                        "files": files_cov,
                        "warnings": warnings
                    }
    except Exception as e:
        warnings.append(f"Lỗi khi chạy coverage tool: {e}")

    warnings.append("Không chạy được coverage.py, fallback sang phân tích heuristic.")
    
    src_files = []
    test_files = []
    
    for r_dir, _, files_in_dir in os.walk(WORKSPACE_ROOT):
        if any(p in r_dir for p in [".git", "node_modules", ".harness_worktree", ".gemini", ".claude", ".harness_cache"]):
            continue
        for f in files_in_dir:
            if f.endswith(".py"):
                fpath = os.path.relpath(os.path.join(r_dir, f), WORKSPACE_ROOT)
                if f.startswith("test_") or "_test" in f:
                    test_files.append(fpath)
                elif f != "smoke_test.py":
                    src_files.append(fpath)
                    
    covered_files = {}
    total_score = 0.0
    
    for sf in src_files:
        base = os.path.basename(sf)[:-3]
        has_test = False
        test_fn_count = 0
        for tf in test_files:
            if base in tf:
                has_test = True
                try:
                    with open(os.path.join(WORKSPACE_ROOT, tf), "r", encoding="utf-8") as f:
                        test_fn_count += len(re.findall(r"def test_", f.read()))
                except Exception:
                    pass
                    
        percent = min(100.0, test_fn_count * 20.0) if has_test else 0.0
        covered_files[sf] = {
            "percent_covered": percent,
            "has_test_file": has_test,
            "test_functions_found": test_fn_count
        }
        total_score += percent

    avg_cov = round(total_score / len(src_files), 2) if src_files else 100.0

    return {
        "coverage_percent": avg_cov,
        "total_files": len(src_files),
        "test_files_count": len(test_files),
        "files": covered_files,
        "warnings": warnings
    }
