# Agent Harness — installer cho may moi
# Cach dung: copy nguyen folder nay sang may dich, mo PowerShell trong folder, chay:
#   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot

Write-Host "=== Agent Harness Installer ===" -ForegroundColor Cyan

# ── 0. Prerequisites ─────────────────────────────────────────────────────────
# Detect Python: uu tien 'python', fallback 'py -3' (py.exe launcher cai tu python.org)
$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = "py"
    Write-Host "[info] Dung 'py' launcher (py.exe) thay cho 'python'"
} else {
    Write-Host "[error] Khong tim thay Python tren PATH." -ForegroundColor Red
    Write-Host "        Cai Python 3.10+ tu https://python.org roi chay lai."
    exit 1
}

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host "[error] Khong tim thay 'claude' tren PATH." -ForegroundColor Red
    Write-Host "        Cai Claude Code truoc (https://claude.com/claude-code) roi chay lai."
    exit 1
}

if (-not (Test-Path "$dir\.env")) {
    Write-Host "[error] Thieu file .env (chua Azure credentials)." -ForegroundColor Red
    Write-Host "        Copy file .env tu may goc vao $dir roi chay lai."
    exit 1
}

# ── 1. Python dependencies ───────────────────────────────────────────────────
Write-Host "[1/4] Cai Python dependencies..."
& $pythonCmd -m pip install -r "$dir\requirements.txt" --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Write-Host "[error] pip install that bai" -ForegroundColor Red; exit 1 }
& $pythonCmd -m playwright install chromium
if ($LASTEXITCODE -ne 0) { Write-Host "[warn] Khong cai duoc Playwright Chromium; visual_reviewer se fallback static analysis." -ForegroundColor Yellow }

# ── 2. Dang ky MCP server (scope user = moi project deu co) ──────────────────
Write-Host "[2/4] Dang ky MCP server voi Claude Code..."
$ErrorActionPreference = "Continue"
claude mcp remove --scope user agent-harness 2>$null | Out-Null   # idempotent: xoa ban cu neu co
$ErrorActionPreference = "Stop"
claude mcp add --scope user agent-harness -- $pythonCmd "$dir\mcp_server.py"
if ($LASTEXITCODE -ne 0) { Write-Host "[error] claude mcp add that bai" -ForegroundColor Red; exit 1 }

# ── 3. CLAUDE.md (quy trinh tu dong) ────────────────────────────────────────
Write-Host "[3/4] Cau hinh ~/.claude/CLAUDE.md va hook..."
& $pythonCmd "$dir\merge_settings.py"
if ($LASTEXITCODE -ne 0) { exit 1 }
$ErrorActionPreference = "Continue"
Unregister-ScheduledTask -TaskName "AgentHarnessAutoWatch" -Confirm:$false 2>$null | Out-Null
$ErrorActionPreference = "Stop"
$legacyTasks = Get-ScheduledTask -TaskName "AgentHarness*" -ErrorAction SilentlyContinue
if ($legacyTasks) {
    Write-Host "[warn] Con scheduled task AgentHarness* cu; Auto-Watch bay gio spawn theo project tu MCP." -ForegroundColor Yellow
}

# ── 4. Smoke test ────────────────────────────────────────────────────────────
Write-Host "[4/4] Chay smoke test..."
& $pythonCmd "$dir\smoke_test.py"
if ($LASTEXITCODE -ne 0) { Write-Host "[error] Smoke test fail — xem loi o tren" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "=== CAI DAT XONG ===" -ForegroundColor Green
Write-Host "Mo (hoac restart) Claude Code o bat ky project nao, go /mcp"
Write-Host "de kiem tra: agent-harness - connected. Tu gio cu giao task code binh thuong,"
Write-Host "harness se tu chay (consult truoc phan kho, panel_review truoc khi bao xong)."
Write-Host "Auto-Watch se tu spawn theo project khi MCP tool dau tien duoc goi."
