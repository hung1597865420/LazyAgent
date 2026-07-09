"""
tools/security.py — Secrets scanning, CORS auditing, and environment configuration drifts.
Ported from support_tools.py.
"""
import os
import re
from config import WORKSPACE_ROOT


async def config_security_audit() -> dict:
    """Security Auditor: Quét exposed secrets, config drift, và cấu hình CORS nhạy cảm."""
    findings = []
    secrets_found = []
    warnings = []
    
    secret_patterns = [
        (r"(?i)(api[_-]?key|secret|password|access[_-]?token|azure[_-]?api[_-]?key|openai[_-]?api[_-]?key)\s*[:=]\s*['\"]([a-zA-Z0-9_\-\.]{20,80})['\"]", "API Key / Credentials"),
        (r"-----BEGIN [A-Z ]+ PRIVATE KEY-----", "Private Key"),
        (r"(?i)\b(?:db_password|database_url)\b\s*[:=]\s*['\"]([^'\"]+)['\"]", "Database Password/URL")
    ]
    
    scan_extensions = (".py", ".env", ".env.example", ".json", ".yml", ".yaml", ".ini", ".conf")
    
    skip_dirs = {
        ".agents", ".claude", ".gemini", ".git", ".harness_cache", ".harness_sandbox",
        ".harness_smoke", ".harness_worktree", ".pytest_cache", ".ruff_cache",
        "__pycache__", "llmwiki", "node_modules",
    }
    for r_dir, dir_names, files_in_dir in os.walk(WORKSPACE_ROOT):
        dir_names[:] = [d for d in dir_names if d not in skip_dirs and not d.startswith(".harness_worktree")]
        rel_dir = os.path.relpath(r_dir, WORKSPACE_ROOT)
        if set(os.path.normpath(rel_dir).split(os.sep)) & skip_dirs:
            continue
        for f in files_in_dir:
            if not f.endswith(scan_extensions):
                continue
            rel_path = os.path.relpath(os.path.join(r_dir, f), WORKSPACE_ROOT)
            abs_path = os.path.join(WORKSPACE_ROOT, rel_path)
            
            try:
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as file_obj:
                    content = file_obj.read()
            except Exception:
                continue
                
            if not rel_path.endswith(".env.example"):
                for pattern, label in secret_patterns:
                    matches = re.finditer(pattern, content)
                    for m in matches:
                        line_no = content[:m.start()].count("\n") + 1
                        matched_str = m.group(0)
                        val = m.group(2) if len(m.groups()) >= 2 else matched_str
                        masked_val = val[:4] + "..." + val[-4:] if len(val) > 8 else "********"
                        masked_str = matched_str.replace(val, masked_val)
                        
                        dummy_indicators = ["your_", "mock_", "dummy_", "placeholder", "azure_openai_api_key"]
                        is_dummy = any(indicator in val.lower() for indicator in dummy_indicators) and "1yozh" not in val.lower()
                        if is_dummy:
                            continue
                            
                        findings.append({
                            "file": rel_path,
                            "line": line_no,
                            "severity": "critical" if "key" in label.lower() or "private" in label.lower() else "high",
                            "category": "secrets",
                            "issue": f"Phát hiện rò rỉ {label}: `{masked_str}`",
                            "suggested_fix": "Không commit thông tin nhạy cảm. Di chuyển vào file .env và đưa file .env vào .gitignore."
                        })
                        secrets_found.append({
                            "file": rel_path,
                            "line": line_no,
                            "label": label,
                            "masked": masked_str
                        })
                        
            if rel_path == "server.py" or f == "server.py":
                if re.search(r"allow_origins\s*=\s*\[\s*['\"]\*(['\"])", content) or "allow_origins=['*']" in content.replace(" ", "") or 'allow_origins=["*"]' in content.replace(" ", ""):
                    findings.append({
                        "file": rel_path,
                        "line": content.find("allow_origins") and content[:content.find("allow_origins")].count("\n") + 1 or 1,
                        "severity": "high",
                        "category": "cors",
                        "issue": "FastAPI CORS cho phép tất cả các nguồn (`allow_origins=['*']`)",
                        "suggested_fix": "Thay thế bằng danh sách các domain tin cậy cụ thể (ví dụ: ['http://localhost:3000']) để tránh lỗ hổng CORS Origin Bypass."
                    })
                    
    env_keys = set()
    example_keys = set()
    env_file = os.path.join(WORKSPACE_ROOT, ".env")
    example_file = os.path.join(WORKSPACE_ROOT, ".env.example")
    
    def parse_env_file(path):
        keys = set()
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k = line.split("=", 1)[0].strip()
                            if k:
                                keys.add(k)
            except Exception:
                pass
        return keys
        
    if os.path.isfile(env_file):
        env_keys = parse_env_file(env_file)
    if os.path.isfile(example_file):
        example_keys = parse_env_file(example_file)
        
    drift_added = list(env_keys - example_keys)
    drift_missing = list(example_keys - env_keys)
    
    if drift_missing:
        findings.append({
            "file": ".env",
            "line": 1,
            "severity": "high",
            "category": "drift",
            "issue": f"Tệp cấu hình .env thiếu các biến được yêu cầu trong .env.example: {drift_missing}",
            "suggested_fix": "Cập nhật tệp .env bằng cách điền giá trị cho các biến môi trường bị thiếu này."
        })
        
    if drift_added:
        findings.append({
            "file": ".env.example",
            "line": 1,
            "severity": "medium",
            "category": "drift",
            "issue": f"Tệp mẫu .env.example thiếu các biến đã có trong .env: {drift_added}",
            "suggested_fix": "Cập nhật tệp .env.example để lập trình viên khác biết cần cấu hình các biến mới này."
        })
        
    used_env_vars = set()
    py_files = []
    for r_dir, _, files_in_dir in os.walk(WORKSPACE_ROOT):
        if any(p in r_dir for p in [".git", "node_modules", ".harness_worktree", ".gemini", ".claude"]):
            continue
        for f in files_in_dir:
            if f.endswith(".py"):
                py_files.append(os.path.join(r_dir, f))
                
    for fpath in py_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                code_content = f.read()
            matches1 = re.findall(r"os\.environ(?:\[['\"]([A-Z_0-9]+)['\"]\]|\.get\(['\"]([A-Z_0-9]+)['\"]\))", code_content)
            matches2 = re.findall(r"os\.getenv\(['\"]([A-Z_0-9]+)['\"]\)", code_content)
            for m in matches1:
                k = m[0] or m[1]
                if k:
                    used_env_vars.add(k)
            for k in matches2:
                if k:
                    used_env_vars.add(k)
        except Exception:
            pass
            
    unregistered_env = list(used_env_vars - env_keys - example_keys)
    system_vars = {
        "ANTIGRAVITY_SOURCE_METADATA", "APPDATA", "CLAUDE_PROJECT_DIR", "HOME",
        "LOCALAPPDATA", "PATH", "PATHEXT", "SMOKE_TEST_SUBRUN", "SYSTEMROOT",
        "TEMP", "TMP", "USER", "USERPROFILE", "WINDIR", "WORKSPACE_ROOT",
        "PYTHONIOENCODING", "PYTHONPATH", "PYTHONUTF8",
    }
    unregistered_env = [v for v in unregistered_env if v not in system_vars]
    
    if unregistered_env:
        findings.append({
            "file": "codebase",
            "line": 1,
            "severity": "medium",
            "category": "drift",
            "issue": f"Phát hiện biến môi trường được gọi trong code nhưng chưa được khai báo trong cả .env và .env.example: {unregistered_env}",
            "suggested_fix": "Khai báo các biến này vào .env và .env.example để tránh các lỗi `NoneType` hoặc thiếu cấu hình khi chạy."
        })
        
    return {
        "findings": findings,
        "secrets_found": secrets_found,
        "drift": {
            "missing_in_env": drift_missing,
            "missing_in_example": drift_added,
            "unregistered_in_code": unregistered_env
        },
        "warnings": warnings
    }
