#!/usr/bin/env python3
"""
Agent Harness - Git Pre-commit Hook Installer and Runner
"""
import os
import sys
import asyncio
import re
import shlex
import subprocess

# Reconfigure stdout/stderr to utf-8 to avoid encoding errors on Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Make sure we can import support_tools from current directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _git_stdout(args: list[str]) -> str:
    return _git_bytes(args).decode("utf-8", errors="replace")


def _git_bytes(args: list[str]) -> bytes:
    return subprocess.check_output(
        ["git", *args],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stderr=subprocess.DEVNULL,
    )


def _decode_git_path(raw: bytes) -> str:
    return raw.decode("utf-8", errors="surrogateescape")


def _staged_paths_from_index() -> list[str]:
    raw = _git_bytes(["diff", "--cached", "--name-status", "-z"])
    tokens = [part for part in raw.split(b"\x00") if part]
    paths: list[str] = []
    i = 0
    while i < len(tokens):
        status = tokens[i].decode("ascii", errors="replace")
        i += 1
        if i >= len(tokens):
            break
        if status.startswith("D"):
            i += 1
            continue
        if status.startswith(("R", "C")):
            i += 1
            if i >= len(tokens):
                break
            paths.append(_decode_git_path(tokens[i]))
            i += 1
            continue
        paths.append(_decode_git_path(tokens[i]))
        i += 1
    return paths


def _staged_coordination_records() -> list[dict[str, str]]:
    raw = _git_bytes(["diff", "--cached", "--name-status", "-z"])
    tokens = [part for part in raw.split(b"\x00") if part]
    records: list[dict[str, str]] = []
    i = 0
    while i < len(tokens):
        status = tokens[i].decode("ascii", errors="replace")
        i += 1
        if i >= len(tokens):
            break
        if status.startswith(("R", "C")):
            old_path = _decode_git_path(tokens[i])
            i += 1
            if i >= len(tokens):
                break
            new_path = _decode_git_path(tokens[i])
            i += 1
            records.append({"status": status, "old_path": old_path, "new_path": new_path, "path": new_path})
            continue
        path = _decode_git_path(tokens[i])
        i += 1
        records.append({"status": status, "path": path})
    return records


def _precommit_coordination_gate(records: list[dict[str, str]]) -> dict:
    if not records:
        return {"status": "completed", "files": []}
    try:
        from tools.coordination import conflict_check

        return conflict_check(files=records, task="git pre-commit", stage="pre_commit", require_lease=False)
    except Exception as exc:
        return {"status": "degraded", "error": f"{type(exc).__name__}: {exc}", "files": records}


def _is_regular_staged_file(path: str) -> bool:
    try:
        meta = _git_stdout(["ls-files", "-s", "--", path]).strip()
    except Exception:
        return False
    mode = meta.split(None, 1)[0] if meta else ""
    return mode in {"100644", "100755"}


_SECRET_KEY_RE = re.compile(
    r"(?i)\b(auth|api[_-]?key|auth[_-]?token|_authtoken|npm[_-]?token|access[_-]?key|access[_-]?token|aws[_-]?access[_-]?key[_-]?id|refresh[_-]?token|token|secret|password|passwd|pwd|authorization|private[_-]?key|client[_-]?secret|webhook)\b"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:auth|api[_-]?key|auth[_-]?token|_authtoken|npm[_-]?token|access[_-]?key|access[_-]?token|aws[_-]?access[_-]?key[_-]?id|refresh[_-]?token|token|secret|password|passwd|pwd|authorization|private[_-]?key|client[_-]?secret|webhook)\b\s*[:=]\s*)([\"']?)[^\s,\"'}\]]+"
)
_AUTH_VALUE_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_URL_CREDENTIAL_RE = re.compile(r"([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@\s/]+@", re.IGNORECASE)
_PEM_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PEM_BLOCK_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)
_SENSITIVE_EXTS = {".pem", ".key", ".p12", ".pfx"}
_SAFE_ENV_NAMES = {".env.example", ".env.sample", ".env.template"}
_SENSITIVE_FILE_NAMES = {
    ".npmrc",
    ".pypirc",
    ".netrc",
    "_netrc",
    "pip.conf",
    "pip.ini",
    "credentials",
    "credentials.toml",
    "kubeconfig",
    "application_default_credentials.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
_SENSITIVE_PATH_SUFFIXES = {
    ".aws/credentials",
    ".aws/config",
    ".kube/config",
    ".docker/config.json",
    ".gem/credentials",
    ".config/gcloud/application_default_credentials.json",
    "cargo/credentials.toml",
}
_STAGED_FILE_TOTAL_CAP = 180_000
_STAGED_FILE_PER_FILE_CAP = 40_000


def _is_sensitive_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    if name.startswith(".env") and name not in _SAFE_ENV_NAMES:
        return True
    if name in _SENSITIVE_FILE_NAMES:
        return True
    if any(normalized.endswith(suffix) for suffix in _SENSITIVE_PATH_SUFFIXES):
        return True
    return os.path.splitext(name)[1].lower() in _SENSITIVE_EXTS


def _resolve_hook_path(workspace_root: str) -> str:
    git_dir = os.path.join(workspace_root, ".git")
    if os.path.isdir(git_dir):
        return os.path.join(git_dir, "hooks", "pre-commit")
    try:
        rel = subprocess.check_output(
            ["git", "rev-parse", "--git-path", "hooks/pre-commit"],
            cwd=workspace_root,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        ).strip()
        if rel:
            return rel if os.path.isabs(rel) else os.path.join(workspace_root, rel)
    except Exception:
        pass
    raise RuntimeError(f"Cannot resolve git hooks path for {workspace_root}")


def _redact_secret_line(line: str) -> str:
    line = _URL_CREDENTIAL_RE.sub(r"\1[REDACTED]@", line)
    line = _AUTH_VALUE_RE.sub(lambda m: f"{m.group(1)} [REDACTED]", line)
    line = _SECRET_ASSIGNMENT_RE.sub(r"\1[REDACTED]", line)
    if _SECRET_KEY_RE.search(line) or _PEM_RE.search(line):
        prefix = ""
        if line[:1] in {"+", "-", " "}:
            prefix = line[:1]
        return f"{prefix}[REDACTED_SECRET_LINE]"
    return line


def _redact_text(text: str) -> str:
    text = _PEM_BLOCK_RE.sub("[REDACTED_PEM_BLOCK]", str(text or ""))
    return "\n".join(_redact_secret_line(line) for line in text.splitlines())


def _redact_diff(diff: str) -> str:
    redacted: list[str] = []
    skipping_sensitive_file = False
    diff = _PEM_BLOCK_RE.sub("[REDACTED_PEM_BLOCK]", str(diff or ""))
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            paths = [part[2:] for part in parts[2:] if part.startswith(("a/", "b/"))]
            skipping_sensitive_file = any(_is_sensitive_path(path) for path in paths)
            if skipping_sensitive_file:
                redacted.append(f"{line} [SENSITIVE FILE CONTENT REDACTED]")
            else:
                redacted.append(line)
            continue
        if skipping_sensitive_file:
            if line.startswith(("index ", "--- ", "+++ ")):
                redacted.append(line)
            elif line.startswith("@@"):
                redacted.append("@@ [SENSITIVE HUNK REDACTED]")
            continue
        redacted.append(_redact_secret_line(line))
    return "\n".join(redacted)


def _staged_file_context(files: list[str], *, total_cap: int = _STAGED_FILE_TOTAL_CAP, per_file_cap: int = _STAGED_FILE_PER_FILE_CAP) -> str:
    blocks: list[str] = []
    total = 0
    for path in files:
        if _is_sensitive_path(path):
            blocks.append(f"=== STAGED FILE: {path} ===\n[SENSITIVE FILE CONTENT REDACTED]")
            continue
        if not _is_regular_staged_file(path):
            blocks.append(f"=== STAGED FILE: {path} ===\n[NON-REGULAR STAGED FILE CONTENT OMITTED]")
            continue
        try:
            raw = _git_bytes(["show", f":{path}"])
        except Exception as exc:
            blocks.append(f"=== STAGED FILE: {path} ===\n[UNAVAILABLE FROM INDEX: {exc}]")
            continue
        if b"\x00" in raw[:8192]:
            blocks.append(f"=== STAGED FILE: {path} ===\n[BINARY FILE CONTENT OMITTED]")
            continue
        if len(raw) > per_file_cap:
            data = raw[:per_file_cap].decode("utf-8", errors="replace")
            data += f"\n[TRUNCATED: staged file exceeded {per_file_cap} bytes]"
        else:
            data = raw.decode("utf-8", errors="replace")
        data = _redact_text(data)
        block = f"=== STAGED FILE: {path} ===\n{data}"
        block_len = len(block.encode("utf-8", errors="replace"))
        if total + block_len > total_cap:
            blocks.append(f"=== STAGED FILE: {path} ===\n[SKIPPED: staged context cap reached]")
            continue
        total += block_len
        blocks.append(block)
    return "\n\n".join(blocks)


def _staged_review_inputs() -> tuple[list[str], str, str]:
    try:
        staged_files = _staged_paths_from_index()
    except Exception:
        staged_files = []
    context_exts = {".py", ".ps1", ".bat", ".json", ".toml", ".yaml", ".yml"}
    ignored_context = {"README.md", "REVIEW_REPORT.md", "CHANGELOG.md"}
    files = [
        path for path in staged_files
        if path.replace("\\", "/").rsplit("/", 1)[-1] not in ignored_context
        and os.path.splitext(path)[1].lower() in context_exts
    ]
    files.sort(key=lambda path: (0 if path.endswith(".py") else 1, path))
    code_context = _staged_file_context(files)
    try:
        diff = _git_stdout(["diff", "--cached", "--unified=80"])
    except Exception:
        diff = ""
    return files, _redact_diff(diff), code_context

def install_hook():
    workspace_root = os.path.dirname(os.path.abspath(__file__))
    try:
        hook_path = _resolve_hook_path(workspace_root)
    except Exception as exc:
        print(f"\033[91m[Harness Installer] Thất bại: không resolve được Git hook path: {exc}\033[0m")
        print("[Harness Installer] Hãy chắc chắn rằng bạn đang chạy script này từ thư mục gốc của Git repository.")
        sys.exit(1)

    hooks_dir = os.path.dirname(hook_path)
    os.makedirs(hooks_dir, exist_ok=True)
    
    python_exe = shlex.quote(sys.executable.replace("\\", "/"))
    script_path = shlex.quote(os.path.join(workspace_root, "install_hooks.py").replace("\\", "/"))
    
    hook_content = f"""#!/bin/sh
# Agent Harness Pre-commit Hook
# Auto-generated by install_hooks.py

PYTHON_EXE={python_exe}
SCRIPT_PATH={script_path}

echo ""
echo "=== [Agent Harness] Đang chạy Git Pre-commit Hook..."

if [ -f "$PYTHON_EXE" ]; then
    "$PYTHON_EXE" "$SCRIPT_PATH" --run-hook
    EXIT_CODE=$?
else
    if command -v python3 >/dev/null 2>&1; then
        python3 "$SCRIPT_PATH" --run-hook
        EXIT_CODE=$?
    else
        python "$SCRIPT_PATH" --run-hook
        EXIT_CODE=$?
    fi
fi

if [ $EXIT_CODE -ne 0 ]; then
    echo "=== [Agent Harness] ❌ Commit bị chặn do phát hiện lỗi nghiêm trọng ==="
    echo ""
    exit $EXIT_CODE
fi

exit 0
"""
    
    try:
        with open(hook_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(hook_content)
        
        # Make the hook executable (crucial for Linux/macOS and Git Bash on Windows)
        try:
            os.chmod(hook_path, 0o755)
        except Exception:
            pass
            
        print(f"\033[92m[Harness Installer] Đã cài đặt Git Pre-commit Hook thành công tại: {hook_path}\033[0m")
    except Exception as e:
        print(f"\033[91m[Harness Installer] Lỗi ghi file hook: {e}\033[0m")
        sys.exit(1)

def run_hook():
    # Helper to run async function
    try:
        from support_tools import panel_review
    except ImportError as e:
        print(f"\033[91m[Harness Hook] Lỗi import support_tools: {e}\033[0m")
        sys.exit(1)
        
    try:
        staged_files, staged_diff, staged_code = _staged_review_inputs()
        coord_records = _staged_coordination_records()
        coord_gate = _precommit_coordination_gate(coord_records)
        if coord_gate.get("status") == "blocked_conflict":
            print("\033[91m======================================================================\033[0m")
            print("\033[91m[Agent Harness] ❌ COMMIT BỊ CHẶN: Có coordination conflict đang active.\033[0m")
            print("\033[91m======================================================================\033[0m")
            for item in coord_gate.get("conflicts", [])[:10]:
                print(f" - {item.get('path')}: owner={item.get('owner')} severity={item.get('severity')} reason={item.get('reason')}")
            print("Hãy chờ owner xong, refresh diff, hoặc takeover stale claim nếu session đã chết.")
            sys.exit(1)
        if coord_gate.get("status") == "warning":
            print(f"[Agent Harness] Coordination warning: {coord_gate.get('warnings') or coord_gate.get('conflicts')}")
        elif coord_gate.get("status") == "degraded":
            print(f"\033[91m[Harness Hook] ❌ coordination gate degraded: {coord_gate.get('error')}\033[0m")
            print("Coordination gate is fail-closed; resolve the coordinator error before committing.")
            sys.exit(1)
        review_code = "\n\n".join(part for part in [
            "=== REDACTED STAGED DIFF ===\n" + staged_diff if staged_diff else "",
            "=== REDACTED STAGED FILE CONTEXT FROM GIT INDEX ===\n" + staged_code if staged_code else "",
        ] if part)
        result = asyncio.run(panel_review(
            code=review_code or None,
            staged=True,
            focus=(
                "Pre-commit review. The === CODE context is read from the Git index, not the working tree. "
                "The staged diff and staged file context have already been redacted for secrets before this call. "
                "Use it to verify existing imports/helpers before flagging missing-symbol findings from === DIFF only. "
                f"Staged context files: {', '.join(staged_files[:20]) or 'none'}."
            ),
        ))
    except Exception as e:
        print(f"\033[93m[Harness Hook] ⚠️ panel_review bị lỗi khi thực thi: {e}\033[0m")
        print("\033[91m[Harness Hook] Fail-closed: sửa lỗi pre-commit/panel infrastructure rồi commit lại.\033[0m")
        sys.exit(1)
        
    if "error" in result:
        err_msg = result["error"]
        if "Không có thay đổi nào để review" in err_msg or "Không có gì để review" in err_msg:
            print("\033[92m[Harness Hook] ✓ Không có thay đổi staged cần review. Tiếp tục commit.\033[0m")
            sys.exit(0)
        else:
            print(f"\033[91m[Harness Hook] ❌ panel_review error: {err_msg}\033[0m")
            print("\033[91m[Harness Hook] Fail-closed: review infrastructure/config must be healthy before commit.\033[0m")
            sys.exit(1)
            
    findings = result.get("findings", [])
    blockers = [
        f for f in findings 
        if str(f.get("severity", "")).lower() in ("critical", "high")
    ]
    
    if blockers:
        print("\033[91m======================================================================\033[0m")
        print("\033[91m[Agent Harness] ❌ COMMIT BỊ CHẶN: Phát hiện lỗi nghiêm trọng (Critical/High)!\033[0m")
        print("\033[91m======================================================================\033[0m")
        for idx, f in enumerate(blockers, 1):
            file_name = f.get("file", "N/A")
            line = f.get("line", "N/A")
            severity = str(f.get("severity", "")).upper()
            issue = f.get("issue", "N/A")
            fix = f.get("suggested_fix", "N/A")
            print(f"\033[1m[{idx}] {file_name}:{line} - \033[91m{severity}\033[0m")
            print(f"    \033[93mLỗi:\033[0m      {issue}")
            print(f"    \033[92mGợi ý sửa:\033[0m {fix}")
            print()
        print("\033[91mHãy sửa các lỗi trên hoặc bỏ qua hook bằng cách dùng: git commit --no-verify\033[0m")
        print("\033[91mXem báo cáo đầy đủ tại file: REVIEW_REPORT.md\033[0m")
        sys.exit(1)
        
    print("\033[92m[Agent Harness] ✓ Vượt qua bước review pre-commit thành công! (Không phát hiện lỗi Critical/High)\033[0m")
    if findings:
        print(f"[Agent Harness] Lưu ý: Phát hiện {len(findings)} lỗi Medium/Low. Bạn có thể xem chi tiết trong file REVIEW_REPORT.md.")
    sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--run-hook":
        run_hook()
    else:
        install_hook()
