"""
tools/devops.py — CI/CD, dependency management, and DevOps pipeline tools.
Ported from support_tools.py.
"""
import asyncio
import logging
import os
import re
import json
import subprocess
import sys
import uuid
from pathlib import Path

from agents import AgentRole
from .core import (
    _is_git_repo,
    _scoped_dirty_status,
    _run_tests,
    _run_tests_in_dir,
    _get_active_workspace,
)

_log = logging.getLogger("harness.devops")
_dep_upgrade_lock = asyncio.Lock()


def _run_text(args, **kwargs):
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    return subprocess.run(args, **kwargs)


def _stream_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _rel_to_repo(repo_path: Path, path: str) -> str:
    try:
        return Path(path).resolve().relative_to(repo_path.resolve()).as_posix()
    except ValueError:
        return Path(path).name


def _optional_llm_enabled() -> bool:
    return os.getenv("HARNESS_STATIC_LLM", "").strip().lower() in {"1", "true", "yes", "on"}


async def dependency_upgrader(dry_run: bool = True) -> dict:
    """Quét và đề xuất nâng cấp các package lỗi thời trong requirements.txt."""
    warnings = []
    workspace = _get_active_workspace()
    req_file = os.path.join(workspace, "requirements.txt")
    if not os.path.isfile(req_file):
        return {"error": "Không tìm thấy requirements.txt ở thư mục gốc workspace", "warnings": warnings}
        
    try:
        r = await asyncio.to_thread(
            _run_text,
            [sys.executable or "python", "-m", "pip", "list", "--outdated", "--format=json"],
            timeout=30
        )
        if r.returncode != 0:
            outdated_packages = []
            warnings.append(f"Không thể kiểm tra package lỗi thời qua pip: {r.stderr.strip()}")
        else:
            outdated_packages = json.loads(r.stdout.strip())
    except Exception as e:
        outdated_packages = []
        warnings.append(f"Lỗi khi chạy pip list: {e}")
        
    try:
        with open(req_file, "r", encoding="utf-8") as f:
            req_content = f.read()
    except Exception as e:
        return {"error": f"Không thể đọc requirements.txt: {e}", "warnings": warnings}
        
    parsed_reqs = {}
    for line in req_content.splitlines():
        raw_line = line
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([a-zA-Z0-9_.-]+)(?:\[[^\]]+\])?\s*([<>=!~]+)\s*([^;#\s]+)", line)
        if m:
            pkg = m.group(1).lower()
            op = m.group(2)
            ver = m.group(3)
            parsed_reqs[pkg] = (op, ver)
        else:
            m_plain = re.match(r"^\s*([a-zA-Z0-9_.-]+)(?:\[[^\]]+\])?(?:\s*(?:[;#].*)?)$", raw_line)
            if m_plain:
                parsed_reqs[m_plain.group(1).lower()] = ("", "")
            
    upgrades = []
    for pkg_info in outdated_packages:
        name = pkg_info.get("name", "").lower()
        if name in parsed_reqs:
            curr_op, curr_ver = parsed_reqs[name]
            latest = pkg_info.get("latest_version", "")
            if latest:
                upgrades.append({
                    "package": pkg_info.get("name", ""),
                    "current": f"{curr_op}{curr_ver}" if curr_ver else "unpinned",
                    "latest": latest
                })
                
    if not upgrades:
        return {
            "message": "Tất cả thư viện trong requirements.txt đều ở phiên bản mới nhất!",
            "upgrades_count": 0,
            "upgrades": [],
            "warnings": warnings
        }

    if dry_run:
        # LLM đánh giá breaking change risk cho từng package cần upgrade
        preview_limit = 50
        preview_upgrades = upgrades[:preview_limit]
        omitted = max(0, len(upgrades) - len(preview_upgrades))
        upgrade_ctx = "\n".join(
            f"- {u['package']}: {u['current']} → {u['latest']}"
            for u in preview_upgrades
        )
        llm_risk = {
            "summary": "Static dry-run only. Set HARNESS_STATIC_LLM=1 to add LLM risk assessment.",
            "packages": upgrade_ctx.splitlines(),
            "omitted_packages": omitted,
        }
        if _optional_llm_enabled():
            from .core import _llm_analyze, _parse_json_object
            risk_prompt = (
                "Bạn là dependency management expert. Đánh giá rủi ro breaking change khi nâng cấp các package sau.\n"
                "Dựa trên kiến thức về semantic versioning và changelog lịch sử của các thư viện phổ biến.\n\n"
                f"Packages cần upgrade:\n{upgrade_ctx}\n\n"
                "Trả về JSON gồm risk_assessment, upgrade_order, summary."
            )
            try:
                raw = await asyncio.wait_for(_llm_analyze(risk_prompt, role=AgentRole.ANALYZER), timeout=30)
                _parsed = _parse_json_object(raw)
                llm_risk = _parsed if isinstance(_parsed, dict) else llm_risk
            except Exception as _e:
                warnings.append(f"LLM risk assessment bỏ qua: {_e}")

        return {
            "message": f"Tìm thấy {len(upgrades)} đề xuất nâng cấp (Chế độ xem thử/Dry Run)",
            "upgrades_count": len(upgrades),
            "upgrades": upgrades,
            "llm_risk_assessment": llm_risk,
            "warnings": warnings
        }
        
    new_lines = []
    for line in req_content.splitlines():
        line_strip = line.strip()
        if not line_strip or line_strip.startswith("#"):
            new_lines.append(line)
            continue
        m = re.match(r"^(\s*([a-zA-Z0-9_.-]+)(?:\[[^\]]+\])?)\s*([<>=!~]+)\s*([^;#\s]+)(.*)$", line)
        if m:
            pkg = m.group(2)
            pkg_lower = pkg.lower()
            matching_upgrade = next((u for u in upgrades if u["package"].lower() == pkg_lower), None)
            if matching_upgrade:
                new_lines.append(f"{m.group(1)}=={matching_upgrade['latest']}{m.group(5)}")
            else:
                new_lines.append(line)
        else:
            m_plain = re.match(r"^(\s*([a-zA-Z0-9_.-]+)(?:\[[^\]]+\])?)(\s*(?:[;#].*)?)$", line)
            pkg_lower = m_plain.group(2).lower() if m_plain else line_strip.lower()
            matching_upgrade = next((u for u in upgrades if u["package"].lower() == pkg_lower), None)
            if matching_upgrade and m_plain:
                new_lines.append(f"{m_plain.group(1)}=={matching_upgrade['latest']}{m_plain.group(3)}")
            else:
                new_lines.append(line)
                 
    new_req_content = "\n".join(new_lines)
    
    if not _is_git_repo():
        async with _dep_upgrade_lock:
            try:
                with open(req_file, "w", encoding="utf-8") as f:
                    f.write(new_req_content)
                r_inst = await asyncio.to_thread(_run_text, [sys.executable, "-m", "pip", "install", "-r", str(req_file)], timeout=300)
                if r_inst.returncode != 0:
                    with open(req_file, "w", encoding="utf-8") as f:
                        f.write(req_content)
                    return {"success": False, "message": f"Cài dependency thất bại: {_stream_text(r_inst.stderr)[:400]}", "warnings": warnings}
                test_ok, test_log = await asyncio.to_thread(_run_tests)
                if not test_ok:
                    with open(req_file, "w", encoding="utf-8") as f:
                        f.write(req_content)
                    r_rb = await asyncio.to_thread(_run_text, [sys.executable, "-m", "pip", "install", "-r", str(req_file)], timeout=300)
                    msg = "Nâng cấp thư viện thất bại do không pass test suite (đã rollback)"
                    if r_rb.returncode != 0:
                        msg += " — cảnh báo: rollback môi trường cũng thất bại, cần kiểm tra thủ công"
                        _log.warning("[Dep-Upgrade] Rollback pip install thất bại: %s", _stream_text(r_rb.stderr)[:200])
                    return {
                        "success": False,
                        "message": msg,
                        "test_log": test_log,
                        "warnings": warnings
                    }
                return {
                    "success": True,
                    "message": "Nâng cấp thư viện thành công (không có git repo)",
                    "upgrades": upgrades,
                    "warnings": warnings
                }
            except subprocess.TimeoutExpired as e:
                return {"error": f"Timeout khi cài đặt package (pip install): {e}", "error_code": "PIP_INSTALL_TIMEOUT", "warnings": warnings}
            except Exception as e:
                return {"error": f"Lỗi ghi hoặc cài đặt package: {e}", "warnings": warnings}
            
    repo_path = Path(workspace).resolve()

    async with _dep_upgrade_lock:
        return await asyncio.to_thread(_dependency_upgrader_apply, repo_path, req_file, req_content, new_req_content, upgrades, warnings)


def _dependency_upgrader_apply(repo_path, req_file, req_content, new_req_content, upgrades, warnings):
    req_rel = _rel_to_repo(repo_path, req_file)
    dirty = _scoped_dirty_status(repo_path, [req_rel])
    if dirty["error"]:
        return {"success": False, "message": f"Không thể kiểm tra trạng thái git: {dirty['error']}", "warnings": warnings}
    if dirty["scoped_conflicts"]:
        return {"success": False, "message": "requirements.txt đang có thay đổi chưa commit — không apply từ worktree", "warnings": warnings}
    warnings.extend(dirty["warnings"])

    uid = uuid.uuid4().hex[:8]
    branch = f"orca-dep-{uid}"
    wt_path = repo_path / f".harness_worktree_{uid}"
    created_branch = False

    try:
        # Atomic: tạo branch và worktree trong một lệnh, tránh branch rác khi fail
        r_wt = _run_text(
            ["git", "worktree", "add", "-b", branch, str(wt_path), "HEAD"],
            cwd=str(repo_path), timeout=30,
        )
        if r_wt.returncode != 0:
            return {"success": False, "message": f"Không thể tạo git worktree: {r_wt.stderr.strip()}", "error_code": "GIT_WORKTREE_FAIL", "warnings": warnings}
        created_branch = True

        wt_req_file = wt_path / "requirements.txt"
        with open(wt_req_file, "w", encoding="utf-8") as f:
            f.write(new_req_content)

        venv_dir = wt_path / ".venv_depcheck"
        r_venv = _run_text(
            [sys.executable, "-m", "venv", str(venv_dir)],
            timeout=60,
        )
        if r_venv.returncode != 0:
            return {"success": False, "message": f"Không thể tạo venv cô lập: {_stream_text(r_venv.stderr)[:400]}", "error_code": "VENV_CREATE_FAIL", "warnings": warnings}
        venv_py = str(venv_dir / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python"))

        r_pip = _run_text(
            [venv_py, "-m", "pip", "install", "-r", str(wt_req_file)],
            timeout=300,
        )
        if r_pip.returncode != 0:
            return {"success": False, "message": f"Cài dependency trong venv worktree thất bại: {_stream_text(r_pip.stderr)[:500]}", "error_code": "PIP_INSTALL_FAIL", "warnings": warnings}
        test_ok, test_log = _run_tests_in_dir(str(wt_path), python_bin=venv_py)
        
        if not test_ok:
            _log.warning("[Dep-Upgrade] Test fail sau nâng cấp trong worktree — worktree sẽ bị dọn dẹp, workspace chính không thay đổi.")
            return {
                "success": False,
                "message": "Nâng cấp thất bại — workspace chính không bị ảnh hưởng (worktree cô lập)",
                "test_log": test_log,
                "warnings": warnings,
            }
            
        dirty2 = _scoped_dirty_status(repo_path, [req_rel])
        if dirty2["error"]:
            return {"success": False, "message": f"Không thể kiểm tra trạng thái git trước apply: {dirty2['error']}", "warnings": warnings}
        if dirty2["scoped_conflicts"]:
            return {"success": False, "message": "requirements.txt có thay đổi mới trong lúc kiểm tra — không apply để tránh conflict", "warnings": warnings}
        warnings.extend(w for w in dirty2["warnings"] if w not in warnings)

        try:
            current_req = Path(req_file).read_text(encoding="utf-8")
        except Exception:
            current_req = None
        if current_req is not None and current_req != req_content:
            return {"success": False, "message": "requirements.txt đã bị thay đổi bên ngoài trong lúc kiểm tra — abort để tránh overwrite", "warnings": warnings}

        with open(req_file, "w", encoding="utf-8") as f:
            f.write(new_req_content)
        warnings.append("requirements.txt đã cập nhật. Chạy `pip install -r requirements.txt` thủ công để đồng bộ môi trường.")

        return {
            "success": True,
            "message": "Nâng cấp thư viện thành công và vượt qua tất cả kiểm thử!",
            "upgrades": upgrades,
            "warnings": warnings
        }

    except subprocess.TimeoutExpired as _te:
        return {"success": False, "message": f"Timeout trong quá trình nâng cấp: {_te}", "error_code": "UPGRADE_TIMEOUT", "warnings": warnings}
    except Exception as _e:
        return {"error": f"Lỗi không mong đợi khi nâng cấp: {_e}", "warnings": warnings}
    finally:
        try:
            if wt_path.exists():
                subprocess.run(["git", "worktree", "remove", "--force", str(wt_path)], cwd=str(repo_path), capture_output=True, timeout=15)
        except Exception:
            pass
        if created_branch:
            try:
                subprocess.run(["git", "branch", "-D", branch], cwd=str(repo_path), capture_output=True, timeout=15)
            except Exception:
                pass


async def devops_pipeline() -> dict:
    """CI/CD Quality Gate & Type/Style Auditor."""
    import ast
    findings = []
    tools_used = []
    warnings = []
    
    _SKIP_DEVOPS = {
        ".agents", ".claude", ".gemini", ".git", ".harness_cache", ".harness_sandbox",
        ".harness_smoke", ".harness_worktree", ".pytest_cache", ".ruff_cache",
        "__pycache__", "llmwiki", "node_modules",
    }
    py_files = []
    workspace = _get_active_workspace()
    for r_dir, dir_names, files_in_dir in os.walk(workspace):
        dir_names[:] = [d for d in dir_names if d not in _SKIP_DEVOPS and not d.startswith(".harness_worktree")]
        rel_dir = os.path.relpath(r_dir, workspace)
        dir_parts = set(Path(rel_dir).parts)
        if dir_parts & _SKIP_DEVOPS:
            continue
        for f in files_in_dir:
            if f.endswith(".py"):
                py_files.append(os.path.relpath(os.path.join(r_dir, f), workspace))
                
    if not py_files:
        return {
            "score": 100,
            "findings": [],
            "tools_used": [],
            "message": "Không tìm thấy file Python nào trong dự án.",
            "warnings": warnings
        }
        
    has_linter = False
    try:
        r = _run_text(["ruff", "check", "--output-format", "json"] + py_files, cwd=workspace, timeout=60)
        if r.returncode in (0, 1):
            has_linter = True
            tools_used.append("ruff")
            if r.stdout.strip():
                try:
                    data = json.loads(r.stdout)
                    if isinstance(data, dict):
                        data = data.get("diagnostics") or data.get("messages") or data.get("results") or []
                    if not isinstance(data, list):
                        warnings.append("Ruff output không phải list JSON, bỏ qua.")
                    else:
                        for item in data:
                            if not isinstance(item, dict):
                                continue
                            loc = item.get("location") or {}
                            f_path = (item.get("filename") or loc.get("path") or item.get("path") or "N/A")
                            f_line = loc.get("row") or loc.get("line") or item.get("row") or item.get("line") or 1
                            if not isinstance(f_line, int):
                                try:
                                    f_line = int(f_line)
                                except (TypeError, ValueError):
                                    f_line = 1
                            findings.append({
                                "type": "lint",
                                "file": f_path,
                                "line": f_line,
                                "code": item.get("code", "E999"),
                                "severity": "medium",
                                "message": f"Ruff: {item.get('message')}"
                            })
                except json.JSONDecodeError:
                    warnings.append("Ruff output không parse được JSON.")
        elif r.returncode in (2, 100):
            warnings.append(f"Ruff gặp lỗi cấu hình/runtime (exit {r.returncode}), fallback sang flake8.")
    except subprocess.TimeoutExpired:
        warnings.append("Ruff timeout sau 60s, fallback sang flake8.")
    except Exception as e:
        warnings.append(f"Không chạy được ruff: {e}. Fallback sang flake8.")

    if not has_linter:
        try:
            r = _run_text(["ruff", "check", "--format", "json"] + py_files, cwd=workspace, timeout=60)
            if r.returncode in (0, 1):
                has_linter = True
                tools_used.append("ruff")
                if r.stdout.strip():
                    try:
                        data = json.loads(r.stdout)
                        if isinstance(data, dict):
                            data = data.get("diagnostics") or data.get("messages") or data.get("results") or []
                        if not isinstance(data, list):
                            warnings.append("Ruff (--output-format) output không phải list JSON, bỏ qua.")
                        else:
                            for item in data:
                                if not isinstance(item, dict):
                                    continue
                                loc = item.get("location") or {}
                                f_path = (item.get("filename") or loc.get("path") or item.get("path") or "N/A")
                                f_line = loc.get("row") or loc.get("line") or item.get("row") or item.get("line") or 1
                                if not isinstance(f_line, int):
                                    try:
                                        f_line = int(f_line)
                                    except (TypeError, ValueError):
                                        f_line = 1
                                findings.append({
                                    "type": "lint",
                                    "file": f_path,
                                    "line": f_line,
                                    "code": item.get("code", "E999"),
                                    "severity": "medium",
                                    "message": f"Ruff: {item.get('message')}"
                                })
                    except json.JSONDecodeError:
                        warnings.append("Ruff (--output-format) output không parse được JSON.")
            elif r.returncode in (2, 100):
                warnings.append(f"Ruff (--format) gặp lỗi (exit {r.returncode}), fallback sang flake8.")
        except subprocess.TimeoutExpired:
            warnings.append("Ruff (--format) timeout sau 60s, fallback sang flake8.")
        except Exception as e:
            warnings.append(f"Không chạy được ruff (--format): {e}")

    if not has_linter:
        try:
            r = _run_text(["flake8", "--format=default"] + py_files, cwd=workspace, timeout=60)
            if r.returncode in (0, 1):
                has_linter = True
                tools_used.append("flake8")
                for line in r.stdout.splitlines():
                    m = re.match(r"^([^:]+):(\d+):(\d+):\s+(\w\d+)\s+(.+)$", line)
                    if m:
                        findings.append({
                            "type": "lint",
                            "file": m.group(1),
                            "line": int(m.group(2)),
                            "code": m.group(4),
                            "severity": "medium",
                            "message": f"Flake8: {m.group(5)}"
                        })
        except subprocess.TimeoutExpired:
            warnings.append("Flake8 timeout sau 60s, bỏ qua linter.")
        except Exception as e:
            warnings.append(f"Không chạy được flake8: {e}")

    has_formatter = False
    try:
        r = _run_text([sys.executable or "python", "-m", "black", "--check"] + py_files, cwd=workspace, timeout=60)
        if r.returncode in (0, 1):
            has_formatter = True
            tools_used.append("black")
            if r.returncode != 0:
                for line in (r.stderr + "\n" + r.stdout).splitlines():
                    if "would reformat" in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            fpath = parts[-1]
                            findings.append({
                                "type": "format",
                                "file": os.path.relpath(fpath, workspace) if os.path.isabs(fpath) else fpath,
                                "line": 1,
                                "code": "FMT",
                                "severity": "low",
                                "message": "File chưa được format chuẩn bằng black"
                            })
    except subprocess.TimeoutExpired:
        warnings.append("Black timeout sau 60s, bỏ qua formatter.")
    except Exception as e:
        warnings.append(f"Không chạy được black: {e}")

    has_typechecker = False
    try:
        r = _run_text([sys.executable or "python", "-m", "mypy", "."], cwd=workspace, timeout=120)
        if r.returncode in (0, 1, 2):
            has_typechecker = True
            tools_used.append("mypy")
            for line in r.stdout.splitlines():
                if ":" in line and "error:" in line:
                    parts = line.split(":", 3)
                    if len(parts) >= 4:
                        findings.append({
                            "type": "type_check",
                            "file": parts[0].strip(),
                            "line": int(parts[1].strip()) if parts[1].strip().isdigit() else 1,
                            "code": "TYPE",
                            "severity": "medium",
                            "message": parts[3].strip()
                        })
    except subprocess.TimeoutExpired:
        warnings.append("Mypy timeout sau 120s, bỏ qua type checker.")
    except Exception as e:
        warnings.append(f"mypy lỗi: {e}")

    if not (has_linter or has_formatter or has_typechecker):
        warnings.append("Không tìm thấy ruff/flake8/black/mypy cài sẵn trên hệ thống. Sử dụng bộ phân tích Python AST fallback.")
        tools_used.append("fallback_parser")
        
        for rel_path in py_files:
            abs_path = os.path.join(workspace, rel_path)
            try:
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    lines = content.splitlines()
            except Exception:
                continue
                
            for idx, line in enumerate(lines):
                line_no = idx + 1
                if len(line) > 120:
                    findings.append({
                        "type": "format",
                        "file": rel_path,
                        "line": line_no,
                        "code": "LINE_TOO_LONG",
                        "severity": "low",
                        "message": f"Dòng quá dài ({len(line)} > 120 ký tự)"
                    })
                stripped = line.lstrip()
                if stripped and not line.startswith("\t"):
                    indent_size = len(line) - len(stripped)
                    if indent_size % 4 != 0:
                        findings.append({
                            "type": "format",
                            "file": rel_path,
                            "line": line_no,
                            "code": "BAD_INDENT",
                            "severity": "low",
                            "message": f"Thụt lề không chuẩn (indent={indent_size} spaces, nên là bội số của 4)"
                        })
                        
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ExceptHandler):
                        if node.type is None:
                            findings.append({
                                "type": "lint",
                                "file": rel_path,
                                "line": node.lineno,
                                "code": "BARE_EXCEPT",
                                "severity": "medium",
                                "message": "Sử dụng 'except:' trống (bare except), nên chỉ định rõ Class ngoại lệ"
                            })
                        elif isinstance(node.type, ast.Name) and node.type.id == "Exception" and len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                            findings.append({
                                "type": "lint",
                                "file": rel_path,
                                "line": node.lineno,
                                "code": "SILENT_EXCEPT",
                                "severity": "medium",
                                "message": "Bắt ngoại lệ Exception và chỉ bỏ qua bằng 'pass' (silent catch)"
                            })
                            
                    if isinstance(node, ast.FunctionDef):
                        if node.name.startswith("__") and node.name.endswith("__"):
                            continue
                        if node.returns is None:
                            findings.append({
                                "type": "type_check",
                                "file": rel_path,
                                "line": node.lineno,
                                "code": "MISSING_RETURN_TYPE",
                                "severity": "low",
                                "message": f"Hàm '{node.name}' thiếu định nghĩa kiểu dữ liệu trả về (return type hint)"
                            })
                        for arg in node.args.args:
                            if arg.arg in ("self", "cls"):
                                continue
                            if arg.annotation is None:
                                findings.append({
                                    "type": "type_check",
                                    "file": rel_path,
                                    "line": arg.lineno,
                                    "code": "MISSING_ARG_TYPE",
                                    "severity": "low",
                                    "message": f"Tham số '{arg.arg}' của hàm '{node.name}' thiếu type hint"
                                })
            except Exception as e:
                warnings.append(f"Không thể parse AST cho file {rel_path}: {e}")
                
    score = 100
    for f in findings:
        sev = f.get("severity", "low").lower()
        if sev == "critical":
            score -= 10
        elif sev == "high":
            score -= 5
        elif sev == "medium":
            score -= 2
        else:
            score -= 1
            
    score = max(0, score)

    # LLM synthesize findings và prioritize cái nào fix trước
    llm_synthesis: dict = {}
    if findings:
        from .core import _llm_analyze, _parse_json_object
        findings_ctx = "\n".join(
            f"[{f['severity'].upper()}] {f['file']}:{f['line']} ({f['code']}) — {f['message']}"
            for f in findings[:40]
        )
        findings_ctx = findings_ctx.encode("utf-8", errors="replace").decode("utf-8")
        synthesis_prompt = (
            "Bạn là senior engineer đang review CI/CD quality gate output.\n"
            "Phân tích các findings từ linter/type-checker/formatter và:\n"
            "1. Nhóm theo pattern (cùng loại lỗi ở nhiều chỗ)\n"
            "2. Xác định root cause (thiếu config? coding convention chưa thống nhất?)\n"
            "3. Đề xuất thứ tự fix: critical trước, sau đó theo ROI cao nhất\n"
            "4. Suggest fix nhanh nếu có (ví dụ: 'chạy black . để fix tất cả format issues')\n\n"
            f"Score: {score}/100\nTools: {tools_used}\nFindings:\n{findings_ctx}\n\n"
            "Trả về JSON:\n"
            "{\n"
            '  "priority_groups": [{"label": "...", "count": 0, "quick_fix": "...", "findings_indices": [1,2]}],\n'
            '  "root_causes": ["..."],\n'
            '  "fix_commands": ["black .", "ruff check --fix ."],\n'
            '  "summary": "..."\n'
            "}"
        )
        if _optional_llm_enabled():
            try:
                raw = await asyncio.wait_for(_llm_analyze(synthesis_prompt, role=AgentRole.SYNTHESIZER), timeout=30)
                _parsed = _parse_json_object(raw)
                llm_synthesis = _parsed if isinstance(_parsed, dict) else {}
            except Exception as e:
                warnings.append(f"LLM synthesis bỏ qua: {e}")
        else:
            llm_synthesis = {
                "summary": "Static quality gate only. Set HARNESS_STATIC_LLM=1 to add LLM synthesis.",
                "fix_commands": ["ruff check --fix .", "python -m black ."],
            }

    return {
        "score": score,
        "findings": findings[:50],
        "tools_used": tools_used,
        "llm_synthesis": llm_synthesis,
        "warnings": warnings
    }


async def incident_responder(log_content: str) -> dict:
    """Tự động phân loại incident, chẩn đoán nguyên nhân, đề xuất giải pháp ứng cứu khẩn cấp (mitigation) và fix lâu dài."""
    warnings = []
    if not log_content or not log_content.strip():
        return {"error": "Cần cung cấp log_content của incident để phân tích", "warnings": warnings}
        
    from .core import _llm_analyze, _parse_json_object
    prompt = (
        "Bạn là DevOps Incident Responder Expert.\n"
        "Hãy phân tích log lỗi/incident sau đây để đưa ra chẩn đoán.\n"
        "Trả về kết quả dưới dạng JSON block thuần túy:\n"
        "{\n"
        "  \"severity\": \"P0\"|\"P1\"|\"P2\"|\"P3\",\n"
        "  \"summary\": \"Tóm tắt sự cố\",\n"
        "  \"root_cause\": \"Nguyên nhân gốc rễ\",\n"
        "  \"mitigation_steps\": [\"Bước giảm thiểu 1\", \"Bước giảm thiểu 2\"],\n"
        "  \"permanent_fix\": \"Giải pháp sửa đổi mã nguồn lâu dài\"\n"
        "}\n"
        "Không ghi thêm text giải thích ngoài JSON block."
    )
    
    try:
        res_raw = await asyncio.wait_for(_llm_analyze(prompt, log_content, role=AgentRole.WORKER), timeout=45)
        res = _parse_json_object(res_raw)
    except asyncio.TimeoutError:
        res = None
        warnings.append("LLM incident analysis timeout sau 45s.")
    except Exception as _e:
        res = None
        warnings.append(f"LLM incident analysis lỗi: {_e}")

    if not res or "severity" not in res:
        return {
            "severity": "P2",
            "summary": "Sự cố chưa xác định rõ qua phân tích tự động",
            "root_cause": "Chưa có kết luận.",
            "mitigation_steps": ["Kiểm tra lại log hệ thống thủ công", "Khởi động lại server nếu cần"],
            "permanent_fix": "Cần can thiệp phân tích sâu hơn.",
            "warnings": warnings + ["Lỗi parse JSON kết quả từ LLM."]
        }

    res["warnings"] = warnings
    return res


async def api_contract_tester(endpoints: list[dict]) -> dict:
    """Tự động tạo mã kiểm thử (pytest) kiểm tra contract của API (JSON schema, status code, v.v.)."""
    warnings = []
    if not endpoints:
        return {"error": "Cần cung cấp danh sách endpoints để test contract", "warnings": warnings}
        
    endpoints_str = json.dumps(endpoints, ensure_ascii=False, indent=2)
    prompt = (
        "Bạn là API Quality Engineer.\n"
        "Hãy sinh một file test pytest hoàn chỉnh sử dụng thư viện `requests` để kiểm thử contract "
        f"của các API endpoints sau:\n{endpoints_str}\n\n"
        "Yêu cầu:\n"
        "- Trả về duy nhất MỘT block code python pytest (chứa imports, mock request hoặc call thực tế, và asserts).\n"
        "- Không giải thích gì thêm ngoài code block."
    )
    
    from .core import _llm_analyze
    try:
        res_raw = await asyncio.wait_for(_llm_analyze(prompt, role=AgentRole.CODE_A), timeout=45)
    except asyncio.TimeoutError:
        warnings.append("LLM api_contract_tester timeout sau 45s.")
        return {"test_code": "", "syntax_valid": None, "generation_status": "timeout", "sandbox_output": {}, "warnings": warnings}
    except Exception as _e:
        warnings.append(f"LLM api_contract_tester lỗi: {_e}")
        return {"test_code": "", "syntax_valid": None, "generation_status": "error", "sandbox_output": {}, "warnings": warnings}

    test_code = res_raw.strip()
    m = re.search(r"```python\s*(.*?)\s*```", test_code, re.DOTALL)
    if m:
        test_code = m.group(1).strip()

    if not test_code:
        return {"test_code": "", "syntax_valid": None, "generation_status": "empty", "sandbox_output": {}, "warnings": warnings}

    import ast as _ast
    syntax_valid = False
    try:
        _ast.parse(test_code)
        syntax_valid = True
    except SyntaxError:
        pass

    if not syntax_valid:
        return {"test_code": test_code, "syntax_valid": False, "generation_status": "invalid_syntax", "execution_status": "skipped_invalid_syntax", "sandbox_output": {}, "warnings": warnings}

    from .core import run_in_sandbox
    try:
        sandbox_res = run_in_sandbox(test_code + "\nprint('Syntax OK')")
    except Exception as _e:
        warnings.append(f"Sandbox lỗi khi kiểm tra syntax: {_e}")
        return {"test_code": test_code, "syntax_valid": True, "generation_status": "ok", "execution_status": "sandbox_error", "sandbox_output": {}, "warnings": warnings}

    sandbox_status = sandbox_res.get("status", "unknown")
    if sandbox_status not in {"success", "ok"}:
        import re as _re_exec
        _combined = (sandbox_res.get("stderr", "") or "") + "\n" + (sandbox_res.get("stdout", "") or "")
        if _re_exec.search(r"ModuleNotFoundError|No module named|ImportError", _combined, _re_exec.IGNORECASE):
            execution_status = "missing_dependency"
        else:
            execution_status = "runtime_error"
    else:
        execution_status = "ok"

    return {
        "test_code": test_code,
        "syntax_valid": True,
        "generation_status": "ok",
        "execution_status": execution_status,
        "sandbox_output": sandbox_res,
        "warnings": warnings
    }


def chaos_tester(app_run_command: str, duration: int = 5) -> dict:
    """Thực hiện fault injection mô phỏng (ví dụ: làm đầy tài nguyên CPU) trong khi giám sát ứng dụng."""
    import shlex
    import time
    warnings = []

    if duration < 1:
        return {"error": "duration phải >= 1 giây", "warnings": warnings}

    import re as _re
    _ALLOWED_BINS = {"python", "python.exe", "python3", "python3.exe", "uvicorn", "pytest", "gunicorn", "node", "node.exe", "npm", "npm.cmd"}
    argv = shlex.split(app_run_command)
    if not argv:
        return {"error": "Lệnh trống", "warnings": warnings}
    from pathlib import PureWindowsPath
    exe_name = os.path.basename(argv[0]).lower()
    exe_name = PureWindowsPath(argv[0]).name.lower() or exe_name
    if exe_name not in _ALLOWED_BINS and not _re.match(r"^python(\d+(\.\d+)*)?$", exe_name):
        return {"error": f"Executable '{exe_name}' không được phép. Cho phép: {', '.join(sorted(_ALLOWED_BINS))} (và python3.x)", "warnings": warnings}

    kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True, "encoding": "utf-8", "errors": "replace"}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    else:
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    proc_app = None
    try:
        proc_app = subprocess.Popen(argv, **kwargs)
    except Exception as e:
        return {"error": f"Không thể khởi chạy ứng dụng: {e}", "warnings": warnings}

    time.sleep(1)
    if proc_app.poll() is not None:
        out, err = proc_app.communicate()
        return {"error": "Ứng dụng dừng trước khi stress bắt đầu", "app_stdout": out, "app_stderr": err, "warnings": warnings}

    stress_code = f"import time\nt0 = time.time()\nwhile time.time() - t0 < {duration}:\n    pass\nprint('Stress done')"
    from .core import run_in_sandbox

    t0 = time.perf_counter()
    stress_res = run_in_sandbox(stress_code, timeout=float(duration) + 1.0)
    duration_ms = int((time.perf_counter() - t0) * 1000)

    app_running_after_stress = proc_app.poll() is None

    app_stdout = ""
    app_stderr = ""
    try:
        if app_running_after_stress:
            proc_app.terminate()
            try:
                out, err = proc_app.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                warnings.append("Terminate timeout, buộc kill tiến trình app.")
                proc_app.kill()
                try:
                    out, err = proc_app.communicate(timeout=2.0)
                except subprocess.TimeoutExpired:
                    warnings.append("Kill timeout, tiến trình app có thể còn tồn tại.")
                    out, err = "", ""
            app_stdout = out
            app_stderr = err
        else:
            out, err = proc_app.communicate()
            app_stdout = out
            app_stderr = err
    except Exception as e:
        warnings.append(f"Lỗi dọn dẹp tiến trình app: {e}")
        try:
            proc_app.kill()
            proc_app.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            warnings.append("Kill cleanup cũng timeout, tiến trình app có thể còn tồn tại.")
        except Exception:
            pass

    return {
        "app_survived": app_running_after_stress,
        "stress_test_status": stress_res.get("status"),
        "chaos_duration_ms": duration_ms,
        "app_stdout": app_stdout[:500],
        "app_stderr": app_stderr[:500],
        "warnings": warnings
    }
