"""
tools/intel.py — System intelligence, PR generation, license audits, and static analysis tools.
"""
import os
import re
import json
import uuid
from typing import Optional
from config import WORKSPACE_ROOT
from agents import AgentRole
from .core import _run_cmd_safe, _llm_analyze, _git_diff, read_workspace_files
from .ui_criteria import EXECUTIVE_COMMAND_UI_CRITERIA


async def pr_generator(diff: Optional[str] = None, branch: Optional[str] = None) -> dict:
    """Tự động sinh tiêu đề, mô tả và danh sách thay đổi của Pull Request dựa trên git diff."""
    warnings = []
    if not diff:
        diff_text, err = _git_diff(staged=False, since_commit=branch or "")
        if err:
            warnings.append(f"Git diff error: {err}")
            diff_text = ""
        diff = diff_text

    if not diff or not diff.strip():
        return {
            "title": "Update codebase",
            "description": "Cập nhật mã nguồn hệ thống (Không tìm thấy git diff thay đổi).",
            "changes": [],
            "warnings": warnings + ["Không có thay đổi nào để tạo PR description chi tiết."]
        }

    prompt = (
        "Bạn là PR Generator Agent chuyên nghiệp.\n"
        "Hãy phân tích git diff sau và sinh tiêu đề PR (ngắn gọn), mô tả PR chi tiết theo chuẩn Markdown "
        "(bao gồm: Mục đích, Các thay đổi chính, và Ảnh hưởng nếu có).\n"
        "Hãy trả về kết quả dưới định dạng JSON block thuần túy:\n"
        "{\n"
        "  \"title\": \"[Prefix] Tiêu đề ngắn gọn\",\n"
        "  \"description\": \"Mô tả Markdown chi tiết\",\n"
        "  \"changes\": [\"Thay đổi 1\", \"Thay đổi 2\"]\n"
        "}\n"
        "Không ghi thêm text giải thích ngoài JSON block."
    )

    try:
        res_raw = await _llm_analyze(prompt, diff, role=AgentRole.WORKER)
        from .core import _parse_json_object
        res = _parse_json_object(res_raw)
    except Exception as _e:
        res = None

    if not res or not isinstance(res, dict) or "title" not in res:
        return {
            "title": "Cập nhật mã nguồn hệ thống",
            "description": f"### Thay đổi bổ sung:\n\n```diff\n{diff[:500]}...\n```",
            "changes": ["Cập nhật các files trong codebase"],
            "warnings": warnings + ["Lỗi parse JSON kết quả từ LLM, fallback dùng nội dung mặc định."]
        }

    if not isinstance(res.get("title"), str):
        res["title"] = "Cập nhật mã nguồn hệ thống"
    if not isinstance(res.get("description"), str):
        res["description"] = ""
    if not isinstance(res.get("changes"), list):
        res["changes"] = []
    res["changes"] = [c for c in res["changes"] if isinstance(c, str)]
    res["warnings"] = warnings
    return res


async def license_scanner() -> dict:
    """Quét toàn bộ codebase để phát hiện các giấy phép (license) sử dụng và cảnh báo tương thích."""
    warnings = []
    licenses_found = []
    copyleft_warnings = []
    
    license_files = []
    for r_dir, _, files_in_dir in os.walk(WORKSPACE_ROOT):
        if any(p in r_dir for p in [".git", "node_modules", ".harness_worktree", ".gemini", ".claude"]):
            continue
        for f in files_in_dir:
            if f.lower() in ("license", "licence", "copying", "license.md", "license.txt"):
                license_files.append(os.path.join(r_dir, f))

    # Đọc requirements.txt để scan thư viện bên thứ ba
    req_file = os.path.join(WORKSPACE_ROOT, "requirements.txt")
    third_party = []
    if os.path.isfile(req_file):
        try:
            with open(req_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # Trích xuất tên package
                        m = re.match(r"^([a-zA-Z0-9_.-]+)", line)
                        if m:
                            third_party.append(m.group(1))
        except Exception:
            pass

    # Phân tích license file chính
    for lf in license_files:
        rel = os.path.relpath(lf, WORKSPACE_ROOT)
        try:
            with open(lf, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(5000).lower()
            
            detected = "Unknown"
            if "mit license" in content or "mit-license" in content or "copyright (c) " in content and "permission is hereby granted" in content:
                detected = "MIT"
            elif "apache license" in content or "apache 2" in content or "version 2.0, january 2004" in content:
                detected = "Apache-2.0"
            elif "gnu general public license" in content or "gpl" in content:
                detected = "GPL"
                copyleft_warnings.append(f"Phát hiện giấy phép copyleft (GPL) tại {rel}. Hãy cẩn thận khi sử dụng trong commercial projects.")
            elif "bsd" in content:
                detected = "BSD"
                
            licenses_found.append({
                "file": rel,
                "license": detected
            })
        except Exception as e:
            warnings.append(f"Không thể đọc license file {rel}: {e}")

    # Sử dụng LLM để kiểm tra sự tương thích của giấy phép bên thứ ba nếu có
    if third_party:
        pkg_sample = third_party[:50]
        if len(third_party) > 50:
            warnings.append(f"License scanner: chỉ gửi 50/{len(third_party)} packages đầu vào LLM để tránh vượt context window.")
        prompt = (
            "Bạn là License Compliance Auditor.\n"
            f"Danh sách các package sử dụng: {pkg_sample}\n"
            f"Hãy liệt kê các giấy phép ước tính của các package này và kiểm tra xem có bất kỳ sự xung đột "
            "về mặt pháp lý hoặc giấy phép copyleft nghiêm ngặt nào không.\n"
            "Trả về JSON định dạng:\n"
            "{\n"
            "  \"packages\": [{\"name\": \"...\", \"license\": \"...\"}],\n"
            "  \"compliance_issues\": [\"Vấn đề 1\"]\n"
            "}"
        )
        try:
            res_raw = await _llm_analyze(prompt, role=AgentRole.ANALYZER)
            from .core import _parse_json_object
            compliance_data = _parse_json_object(res_raw)
        except Exception as _e:
            warnings.append(f"LLM license check lỗi: {_e}")
            compliance_data = None

        if compliance_data:
            for pkg in compliance_data.get("packages", []):
                if not isinstance(pkg, dict):
                    warnings.append("LLM packages item không hợp lệ, bỏ qua.")
                    continue
                licenses_found.append({
                    "package": pkg.get("name"),
                    "license": pkg.get("license")
                })
                if "gpl" in str(pkg.get("license")).lower() or "agpl" in str(pkg.get("license")).lower():
                    copyleft_warnings.append(f"Package {pkg.get('name')} sử dụng giấy phép copyleft ({pkg.get('license')}).")

            raw_issues = compliance_data.get("compliance_issues", [])
            if isinstance(raw_issues, list):
                seen_issues = set()
                for issue in raw_issues:
                    if isinstance(issue, str):
                        clean = issue.strip()
                        if clean and clean not in seen_issues:
                            seen_issues.add(clean)
                            copyleft_warnings.append(clean)
            else:
                warnings.append("LLM compliance_issues không phải list, bỏ qua.")

    return {
        "licenses": licenses_found,
        "copyleft_warnings": copyleft_warnings,
        "warnings": warnings,
        "compliant": len(copyleft_warnings) == 0
    }


async def sbom_generator() -> dict:
    """Sinh Software Bill of Materials (SBOM) dựa trên các dependencies của dự án theo chuẩn SPDX JSON."""
    dependencies = []
    warnings = []
    
    # 1. Quét Python requirements.txt
    req_file = os.path.join(WORKSPACE_ROOT, "requirements.txt")
    if os.path.isfile(req_file):
        try:
            with open(req_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    m = re.match(r"^([a-zA-Z0-9_.-]+)\s*([<>=!~]+)\s*([^;#\s]+)", line)
                    if m:
                        dependencies.append({
                            "name": m.group(1),
                            "version": m.group(3),
                            "type": "pip"
                        })
                    else:
                        dependencies.append({
                            "name": line,
                            "version": "latest",
                            "type": "pip"
                        })
        except Exception as e:
            warnings.append(f"Lỗi đọc requirements.txt: {e}")

    # 2. Quét Node package.json (nếu có)
    package_json = os.path.join(WORKSPACE_ROOT, "package.json")
    if os.path.isfile(package_json):
        try:
            with open(package_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.get("dependencies", {}).items():
                dependencies.append({
                    "name": k,
                    "version": v,
                    "type": "npm"
                })
            for k, v in data.get("devDependencies", {}).items():
                dependencies.append({
                    "name": k,
                    "version": v,
                    "type": "npm-dev"
                })
        except Exception as e:
            warnings.append(f"Lỗi đọc package.json: {e}")

    import datetime
    created_time = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "AgentHarness-SBOM",
        "documentNamespace": f"http://spdx.org/spdxdocs/harness-{uuid.uuid4().hex[:8]}",
        "creationInfo": {
            "creators": ["Tool: SBOM Generator (Agent Harness)"],
            "created": created_time
        },
        "packages": []
    }

    for idx, dep in enumerate(dependencies):
        pkg_id = f"SPDXRef-Package-{idx + 1}"
        sbom["packages"].append({
            "name": dep["name"],
            "SPDXID": pkg_id,
            "versionInfo": dep["version"],
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:{dep['type']}/{dep['name']}@{dep['version']}"
                }
            ]
        })

    # LLM flag CVE risk và highlight packages đáng lo ngại
    llm_risk: dict = {}
    if dependencies:
        from .core import _parse_json_object
        dep_ctx = "\n".join(
            f"- {d['name']}=={d['version']} ({d['type']})"
            for d in dependencies[:50]
        )
        risk_prompt = (
            "Bạn là security engineer chuyên về supply chain risk.\n"
            "Phân tích danh sách dependencies và flag:\n"
            "1. HIGH_CVE_RISK: Package có lịch sử CVE nghiêm trọng hoặc version cũ đã biết có lỗ hổng\n"
            "2. ABANDONED: Package không còn được maintain (dựa trên kiến thức về ecosystem)\n"
            "3. SUSPICIOUS: Package tên giống popular package nhưng khác (typosquatting risk)\n"
            "4. OK: Package ổn định, được maintain tốt\n\n"
            f"Dependencies:\n{dep_ctx}\n\n"
            "Trả về JSON:\n"
            "{\n"
            '  "risk_items": [{"name": "...", "version": "...", "risk": "HIGH_CVE_RISK|ABANDONED|SUSPICIOUS|OK", '
            '"notes": "...", "recommendation": "..."}],\n'
            '  "high_risk_count": 0,\n'
            '  "action_required": ["upgrade X to Y", "replace Z with W"],\n'
            '  "summary": "..."\n'
            "}"
        )
        try:
            raw = await _llm_analyze(risk_prompt, role=AgentRole.SECURITY)
            llm_risk = _parse_json_object(raw) or {}
        except Exception as _e:
            llm_risk = {"warning": f"LLM risk assessment lỗi: {_e}"}

    return {
        "sbom": sbom,
        "dependencies_count": len(dependencies),
        "llm_risk_assessment": llm_risk,
        "warnings": warnings
    }


async def a11y_auditor(files: Optional[list[str]] = None) -> dict:
    """Quét và kiểm tra lỗi accessibility (A11y - WCAG) trong các giao diện HTML/CSS/JSX."""
    warnings = []
    target_files = []
    
    if files:
        target_files = files
    else:
        for r_dir, _, files_in_dir in os.walk(WORKSPACE_ROOT):
            if any(p in r_dir for p in [".git", "node_modules", ".harness_worktree"]):
                continue
            for f in files_in_dir:
                if f.endswith((".html", ".jsx", ".tsx", ".vue")):
                    target_files.append(os.path.relpath(os.path.join(r_dir, f), WORKSPACE_ROOT))
                    if len(target_files) >= 5:
                        break
            if len(target_files) >= 5:
                break

    if not target_files:
        return {
            "score": 100,
            "issues": [],
            "message": "Không tìm thấy file giao diện (HTML/JSX/Vue) nào để audit.",
            "warnings": warnings
        }

    ctx_block, warns, _ = read_workspace_files(target_files)
    warnings.extend(warns)

    prompt = (
        "Bạn là Accessibility (A11y) Expert. Hãy kiểm tra các file giao diện trong context "
        "đối chiếu với chuẩn WCAG 2.1 AA (như thiếu alt ở img, thiếu label ở input, sai cấu trúc headings, "
        "tương phản kém, thiếu thuộc tính aria).\n"
        "Ngoài WCAG, hãy audit theo design system Executive Command dưới đây. Đừng chỉ bắt lỗi kỹ thuật; "
        "hãy flag cả lỗi khiến UI lệch chuẩn corporate precision, thiếu state, sai palette, sai typography, "
        "responsive yếu, form/login không đủ trạng thái, motion không tôn trọng reduced motion, hoặc layout "
        "làm giảm khả năng thao tác lặp lại.\n\n"
        f"{EXECUTIVE_COMMAND_UI_CRITERIA}\n\n"
        "Trả về kết quả dưới dạng JSON block thuần túy:\n"
        "{\n"
        "  \"score\": 80,\n"
        "  \"design_system_score\": 80,\n"
        "  \"issues\": [\n"
        "    {\n"
        "      \"file\": \"tên_file.html\",\n"
        "      \"line\": 15,\n"
        "      \"severity\": \"critical\"|\"high\"|\"medium\"|\"low\",\n"
        "      \"standard\": \"WCAG 1.1.1 Non-text Content hoặc Executive Command: Interaction states\",\n"
        "      \"criterion\": \"contrast|semantic_html|keyboard|forms|palette|typography|layout|responsive|motion|state_design\",\n"
        "      \"design_system_violation\": true,\n"
        "      \"issue\": \"Thẻ img thiếu thuộc tính alt\",\n"
        "      \"suggested_fix\": \"Thêm alt='Mô tả ảnh' cho thẻ img\"\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "Không ghi thêm text giải thích ngoài JSON block."
    )

    try:
        res_raw = await _llm_analyze(prompt, ctx_block, role=AgentRole.REVIEWER)
        from .core import _parse_json_object
        res = _parse_json_object(res_raw)
    except Exception as _e:
        res = None

    if not res or "score" not in res:
        return {
            "score": 100,
            "issues": [],
            "message": "Không phát hiện lỗi A11y nào qua phân tích tĩnh sơ bộ.",
            "warnings": warnings + ["Lỗi phân tích cú pháp kết quả từ LLM."]
        }

    res["warnings"] = warnings
    return res


async def i18n_auditor(files: Optional[list[str]] = None) -> dict:
    """Quét và tìm các chuỗi văn bản cứng (hardcoded strings) cần được quốc tế hóa (i18n)."""
    warnings = []
    target_files = []
    
    if files:
        target_files = files
    else:
        for r_dir, _, files_in_dir in os.walk(WORKSPACE_ROOT):
            if any(p in r_dir for p in [".git", "node_modules", ".harness_worktree", ".gemini", ".claude"]):
                continue
            for f in files_in_dir:
                if f.endswith((".py", ".js", ".jsx", ".ts", ".tsx", ".html")):
                    target_files.append(os.path.relpath(os.path.join(r_dir, f), WORKSPACE_ROOT))
                    if len(target_files) >= 5:
                        break
            if len(target_files) >= 5:
                break

    if not target_files:
        return {
            "issues_count": 0,
            "issues": [],
            "warnings": warnings
        }

    ctx_block, warns, _ = read_workspace_files(target_files)
    warnings.extend(warns)

    prompt = (
        "Bạn là Internationalization (i18n) Auditor Agent.\n"
        "Hãy quét codebase và tìm các chuỗi string cứng (hardcoded text) hiển thị ra ngoài UI "
        "mà chưa được dịch qua các hàm đa ngôn ngữ (ví dụ: chưa được bọc bởi `t()`, `_()`, `gettext()`).\n"
        "Hãy bỏ qua các chuỗi kỹ thuật (như key, logs, debug messages, regex, paths, environment variables).\n"
        "Trả về kết quả dưới dạng JSON block thuần túy:\n"
        "{\n"
        "  \"issues\": [\n"
        "    {\n"
        "      \"file\": \"tên_file.py\",\n"
        "      \"line\": 25,\n"
        "      \"hardcoded_text\": \"Chào mừng bạn!\",\n"
        "      \"suggestion\": \"t('welcome_message') hoặc _('Chào mừng bạn!')\"\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "Không ghi thêm text giải thích ngoài JSON block."
    )

    try:
        res_raw = await _llm_analyze(prompt, ctx_block, role=AgentRole.REVIEWER)
        from .core import _parse_json_object
        res = _parse_json_object(res_raw)
    except Exception as _e:
        res = None

    if not res or "issues" not in res:
        return {
            "issues_count": 0,
            "issues": [],
            "warnings": warnings + ["Lỗi phân tích cú pháp kết quả từ LLM."]
        }

    res["issues_count"] = len(res["issues"])
    res["warnings"] = warnings
    return res


async def polyglot_reviewer(files: list[str]) -> dict:
    """Thực hiện code review đa ngôn ngữ chuyên sâu cho từng ngôn ngữ lập trình đặc thù."""
    warnings = []
    if not files:
        return {"error": "Cần cung cấp danh sách file để review đa ngôn ngữ", "warnings": warnings}

    ctx_block, warns, _ = read_workspace_files(files)
    warnings.extend(warns)

    prompt = (
        "Bạn là Polyglot Senior Code Reviewer. Bạn am hiểu sâu sắc các best practices của Python, "
        "JavaScript/TypeScript, Go, HTML, CSS, v.v.\n"
        "Hãy review các file nguồn trong context theo đặc thù ngôn ngữ của chúng (ví dụ: memory leaks "
        "trong JS/Go, performance anti-patterns trong Python, layout bugs trong CSS).\n"
        "Trả về kết quả dưới dạng JSON block thuần túy:\n"
        "{\n"
        "  \"findings\": [\n"
        "    {\n"
        "      \"file\": \"tên_file.py\",\n"
        "      \"line\": 12,\n"
        "      \"severity\": \"critical\"|\"high\"|\"medium\"|\"low\",\n"
        "      \"category\": \"performance\"|\"security\"|\"logic\"|\"style\",\n"
        "      \"issue\": \"Mô tả lỗi\",\n"
        "      \"suggested_fix\": \"Hướng dẫn sửa\"\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "Không ghi thêm text giải thích ngoài JSON block."
    )

    try:
        res_raw = await _llm_analyze(prompt, ctx_block, role=AgentRole.REVIEWER)
        from .core import _parse_json_object
        res = _parse_json_object(res_raw)
    except Exception as _e:
        res = None

    if not res or "findings" not in res:
        return {
            "findings": [],
            "warnings": warnings + ["Lỗi phân tích cú pháp kết quả từ LLM."]
        }

    res["warnings"] = warnings
    return res


async def git_archaeologist(file_path: str, line_no: Optional[int] = None) -> dict:
    """Khảo cổ lịch sử Git: tìm commit cuối cùng thay đổi một dòng hoặc file nhất định."""
    warnings = []
    
    # Check if git repo
    from .core import _is_git_repo
    if not _is_git_repo():
        return {"error": "Thư mục không phải là git repository", "warnings": warnings}

    if line_no is not None and line_no < 1:
        return {"error": f"line_no phải >= 1, nhận được {line_no}", "warnings": warnings}

    from pathlib import Path as _Path
    _root = _Path(WORKSPACE_ROOT).resolve()
    _full = (_root / file_path).resolve()
    if _full != _root and _root not in _full.parents:
        return {"error": "Truy cập ngoài WORKSPACE_ROOT bị chặn", "warnings": warnings}
    if not os.path.exists(str(_full)):
        return {"error": f"File {file_path} không tồn tại", "warnings": warnings}

    if line_no is not None:
        # Chạy git blame
        cmd = ["git", "blame", "-L", f"{line_no},{line_no}", "--porcelain", file_path]
        code, out, err = _run_cmd_safe(cmd)
        if code != 0:
            return {"error": f"Lỗi chạy git blame: {err}", "warnings": warnings}
        
        # Parse porcelain output
        lines = out.splitlines()
        if not lines:
            return {"error": "Không có thông tin blame", "warnings": warnings}
            
        commit_sha = lines[0].split()[0]
        author = "Unknown"
        time_str = "Unknown"
        summary = "Unknown"
        
        for line in lines:
            if line.startswith("author "):
                author = line[7:]
            elif line.startswith("author-time "):
                import datetime
                try:
                    time_str = datetime.datetime.fromtimestamp(int(line[12:])).isoformat()
                except Exception:
                    pass
            elif line.startswith("summary "):
                summary = line[8:]
                
        return {
            "file": file_path,
            "line": line_no,
            "commit_sha": commit_sha,
            "author": author,
            "date": time_str,
            "summary": summary,
            "warnings": warnings
        }
    else:
        # Chạy git log cuối cùng của file
        cmd = ["git", "log", "-n", "1", "--pretty=format:%H%n%an%n%ad%n%s", "--", file_path]
        code, out, err = _run_cmd_safe(cmd)
        if code != 0:
            return {"error": f"Lỗi chạy git log: {err}", "warnings": warnings}
            
        lines = out.splitlines()
        if len(lines) < 4:
            return {"error": "Không tìm thấy lịch sử commit cho file này", "warnings": warnings}
            
        return {
            "file": file_path,
            "commit_sha": lines[0],
            "author": lines[1],
            "date": lines[2],
            "summary": lines[3],
            "warnings": warnings
        }


async def feature_flag_auditor() -> dict:
    """Quét codebase phát hiện cấu trúc feature flags, các flag không sử dụng hoặc quá hạn."""
    warnings = []
    flags_found = []
    
    # 1. Tìm các flags được gọi trong codebase
    py_files = []
    for r_dir, _, files_in_dir in os.walk(WORKSPACE_ROOT):
        if any(p in r_dir for p in [".git", "node_modules", ".harness_worktree", ".gemini", ".claude"]):
            continue
        for f in files_in_dir:
            if f.endswith((".py", ".js", ".jsx", ".ts", ".tsx")):
                py_files.append(os.path.join(r_dir, f))

    flag_patterns = [
        r"(?:is_enabled|get_flag|flag_gate)\s*\(\s*['\"]([a-zA-Z0-9_\-\.]+)['\"]",
        r"features\.([a-zA-Z0-9_\-\.]+)",
        r"feature_flag\s*=\s*['\"]([a-zA-Z0-9_\-\.]+)['\"]"
    ]

    for pf in py_files:
        rel = os.path.relpath(pf, WORKSPACE_ROOT)
        try:
            with open(pf, "r", encoding="utf-8", errors="ignore") as f:
                for idx, line in enumerate(f):
                    for pat in flag_patterns:
                        for match in re.finditer(pat, line):
                            flag_name = match.group(1)
                            flags_found.append({
                                "flag": flag_name,
                                "file": rel,
                                "line": idx + 1
                            })
        except Exception as e:
            warnings.append(f"Không thể đọc file {rel}: {e}")

    # Deduplicate và đếm tần số dùng flag
    flags_summary = {}
    for f in flags_found:
        fname = f["flag"]
        if fname not in flags_summary:
            flags_summary[fname] = {
                "flag": fname,
                "occurrences": [],
                "count": 0
            }
        flags_summary[fname]["occurrences"].append(f"{f['file']}:{f['line']}")
        flags_summary[fname]["count"] += 1

    # Dùng LLM để phân loại xem flag nào có thể là dead flag (ví dụ: flag đã bật 100% hoặc quá cũ)
    summary_list = list(flags_summary.values())
    dead_flags = []
    if summary_list:
        prompt = (
            "Bạn là Feature Flag Auditor Agent.\n"
            f"Danh sách các feature flags phát hiện được và vị trí sử dụng:\n{json.dumps(summary_list, ensure_ascii=False, indent=2)}\n\n"
            "Hãy đánh giá xem flag nào có thể đã quá cũ hoặc không còn hoạt động tích cực (dead flags) "
            "cần phải được dọn dẹp để tránh nợ kỹ thuật (technical debt).\n"
            "Trả về JSON định dạng:\n"
            "{\n"
            "  \"dead_flags\": [\"tên_flag\"]\n"
            "}"
        )
        try:
            res_raw = await _llm_analyze(prompt, role=AgentRole.ANALYZER)
            from .core import _parse_json_object
            dead_data = _parse_json_object(res_raw)
            if isinstance(dead_data, dict):
                raw_dead = dead_data.get("dead_flags", [])
                if isinstance(raw_dead, list):
                    dead_flags = list(dict.fromkeys(x.strip() for x in raw_dead if isinstance(x, str) and x.strip()))
                    if len(dead_flags) != len([x for x in raw_dead if isinstance(x, str) and x.strip()]):
                        warnings.append("LLM dead_flags chứa phần tử không hợp lệ hoặc trùng lặp, đã lọc và dedup.")
                else:
                    dead_flags = []
                    warnings.append("LLM dead_flags không phải list, bỏ qua.")
            else:
                dead_flags = []
                warnings.append("Lỗi phân tích kết quả dead flags từ LLM")
        except Exception as _e:
            dead_flags = []
            warnings.append(f"LLM feature flag lỗi: {_e}")

    return {
        "flags": summary_list,
        "dead_flags": dead_flags,
        "warnings": warnings
    }
