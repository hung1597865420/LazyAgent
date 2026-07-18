@echo off
setlocal EnableExtensions
set "HARNESS_FULL_SETUP_BAT=%~f0"
set "HARNESS_FULL_SETUP_ROOT=%~dp0"
set "HARNESS_FULL_SETUP_MARKER=###HARNESS_FULL_SETUP_PS_PAYLOAD###"
set "HARNESS_FULL_SETUP_PS1=%TEMP%\harness-full-setup-%RANDOM%-%RANDOM%.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:HARNESS_FULL_SETUP_BAT); $i=$s.LastIndexOf($env:HARNESS_FULL_SETUP_MARKER); if($i -lt 0){Write-Error 'PowerShell payload missing'; exit 2}; [IO.File]::WriteAllText($env:HARNESS_FULL_SETUP_PS1, $s.Substring($i), (New-Object System.Text.UTF8Encoding($false)))"
if errorlevel 1 exit /b %ERRORLEVEL%
powershell -NoProfile -ExecutionPolicy Bypass -File "%HARNESS_FULL_SETUP_PS1%" %*
set "HARNESS_FULL_SETUP_EXIT=%ERRORLEVEL%"
del "%HARNESS_FULL_SETUP_PS1%" >nul 2>nul
exit /b %HARNESS_FULL_SETUP_EXIT%

###HARNESS_FULL_SETUP_PS_PAYLOAD###
$Argv = @($args | ForEach-Object { [string]$_ })
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path $env:HARNESS_FULL_SETUP_ROOT).Path
$ToggleBat = Join-Path $Root 'harness-toggle.bat'
$FeatureFile = Join-Path $Root 'harness.features.json'
$Profile = 'off'
$RunSmoke = $true
$InstallPlaywright = $true
$InstallGitHook = $true
$InstallStartupTask = $true
$StartWatch = $null
$StartDashboard = $false
$CopyWikiGlobal = $true
$AllowMissingEnv = $true

function Show-Help {
@'
Agent Harness Full Setup

Purpose:
  Install dependencies, sync MCP/rules/hooks for Claude + Gemini/Antigravity
  + Codex, install memory/background integration, and write a runtime profile.
  Also verifies the current MCP-only bridges are present: Hallmark/Spec Kit,
  OfficeCLI bridge, scope-creep guard, and 9Router quota reminder.
  Default profile is off. Use --profile max to enable every runtime feature
  and start background helpers.

Usage:
  harness-full-setup.bat
  harness-full-setup.bat --profile max
  harness-full-setup.bat --profile heavy
  harness-full-setup.bat --no-watch --no-smoke
  harness-full-setup.bat --start-dashboard

Options:
  --profile <off|max|heavy|review|balanced|standard|light>
      Runtime profile to write. Default: off.
      Default off still installs configs/hooks/rules, but prevents background
      tools, LLM calls, watcher, lessons, and FinOps writes until user enables
      a higher profile explicitly.
  --no-smoke
      Skip smoke_test.py.
      Full smoke is skipped automatically when profile is off.
  --no-playwright
      Skip Playwright Chromium install.
  --no-git-hook
      Skip repository pre-commit hook install.
  --no-startup-task
      Skip Windows Scheduled Task that starts auto_watch.py at user logon.
      The task is safe with default profile off: auto_watch.py starts, sees
      auto-watch disabled, and exits.
  --no-watch
      Do not start watcher now. Auto-watch state still follows the selected
      profile in harness.features.json.
  --start-dashboard
      Also start server.py in the background.
  --no-global-wiki
      Do not copy repo llmwiki/ into ~/.claude/llmwiki.
  --require-env
      Fail when .env is missing instead of creating it from .env.example.
  --help
      Show this help.

Maintenance:
  When adding/removing runtime features, update both harness-toggle.bat and
  this file so full setup stays identical to the supported toggle surface.
  MCP-only/read-only tools still belong here because setup should fail fast if
  their files are missing, even when they do not need a profile toggle.
'@
}

for ($i = 0; $i -lt $Argv.Count; $i++) {
    $a = $Argv[$i].ToLowerInvariant()
    switch ($a) {
        '--help' { Show-Help; exit 0 }
        '-h' { Show-Help; exit 0 }
        '/?' { Show-Help; exit 0 }
        '--profile' {
            if ($i + 1 -ge $Argv.Count) { throw '--profile requires a value.' }
            $i++
            $Profile = $Argv[$i].ToLowerInvariant()
        }
        '--no-smoke' { $RunSmoke = $false }
        '--no-playwright' { $InstallPlaywright = $false }
        '--no-git-hook' { $InstallGitHook = $false }
        '--no-startup-task' { $InstallStartupTask = $false }
        '--no-watch' { $StartWatch = $false }
        '--start-dashboard' { $StartDashboard = $true }
        '--no-global-wiki' { $CopyWikiGlobal = $false }
        '--require-env' { $AllowMissingEnv = $false }
        default { throw "Unknown option '$($Argv[$i])'. Run harness-full-setup.bat --help" }
    }
}

if ($Profile -notin @('off','max','heavy','review','balanced','standard','light','7','5','4')) {
    throw "Unsupported profile '$Profile'. Use off, max, heavy, review, balanced, standard, light, 7, 5, or 4."
}
if ($null -eq $StartWatch) {
    $StartWatch = $Profile -notin @('off','light','balanced','4')
}
if ($Profile -eq 'off' -and $RunSmoke) {
    $RunSmoke = $false
}

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "== $Text ==" -ForegroundColor Cyan
}

function Find-Python {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return [pscustomobject]@{ Command = 'python'; Prefix = @() }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return [pscustomobject]@{ Command = 'py'; Prefix = @('-3') }
    }
    throw 'Python 3.10+ not found on PATH.'
}

$script:Python = Find-Python

function Invoke-Python([string[]]$Arguments) {
    & $script:Python.Command @($script:Python.Prefix + $Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

function Invoke-OptionalPython([string[]]$Arguments, [string]$Warning) {
    & $script:Python.Command @($script:Python.Prefix + $Arguments)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[warn] $Warning" -ForegroundColor Yellow
    }
}

function Invoke-Toggle([string[]]$Arguments) {
    $old = $env:HARNESS_ALLOW_PROFILE_WRITE
    $env:HARNESS_ALLOW_PROFILE_WRITE = '1'
    try {
        & $ToggleBat @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "harness-toggle.bat failed: $($Arguments -join ' ')"
        }
    } finally {
        if ($null -eq $old) {
            Remove-Item Env:\HARNESS_ALLOW_PROFILE_WRITE -ErrorAction SilentlyContinue
        } else {
            $env:HARNESS_ALLOW_PROFILE_WRITE = $old
        }
    }
}

function Install-WatchStartupTask {
    if ($IsWindows -eq $false -or $env:OS -ne 'Windows_NT') {
        Write-Host '[skip] Scheduled Task is Windows-only.' -ForegroundColor Yellow
        return
    }
    $pythonw = Get-Command pythonw -ErrorAction SilentlyContinue
    if (-not $pythonw) { $pythonw = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $pythonw) { throw 'python/pythonw not found on PATH for startup task.' }

    $taskName = 'AgentHarnessAutoWatch'
    $scriptPath = Join-Path $Root 'auto_watch.py'
    $action = New-ScheduledTaskAction `
        -Execute $pythonw.Source `
        -Argument ('"{0}"' -f $scriptPath) `
        -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 12) `
        -MultipleInstances IgnoreNew
    try {
        Register-ScheduledTask `
            -TaskName $taskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Description 'Starts Agent Harness Auto-Watch at user logon. Runtime profile off makes it exit immediately.' `
            -Force | Out-Null
        Write-Host "[ok] Windows startup task installed: $taskName"
    } catch {
        Write-Host "[warn] Could not install startup task: $($_.Exception.Message)" -ForegroundColor Yellow
        Write-Host "[warn] Run this batch from a normal user PowerShell with Scheduled Tasks permission, or use --no-startup-task." -ForegroundColor Yellow
    }
}

function Copy-DirMerge([string]$Source, [string]$Dest) {
    if (-not (Test-Path $Source)) { return }
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    Copy-Item -Path (Join-Path $Source '*') -Destination $Dest -Recurse -Force -ErrorAction Stop
}

Write-Host '=== Agent Harness Full Setup ===' -ForegroundColor Green
Write-Host "Root: $Root"
Write-Host "Profile to write: $Profile"

foreach ($required in @(
    'mcp_server.py',
    'merge_settings.py',
    'requirements.txt',
    'harness-toggle.bat',
    'tools\integrations.py',
    'tools\office_bridge.py',
    'tools\scope_guard.py',
    'tools\quota.py'
)) {
    if (-not (Test-Path (Join-Path $Root $required))) {
        throw "Missing required file: $required. Run this bat from the harness repo folder."
    }
}

Write-Step '0/9 Check env file'
$envPath = Join-Path $Root '.env'
$envExample = Join-Path $Root '.env.example'
if (-not (Test-Path $envPath)) {
    if ($AllowMissingEnv -and (Test-Path $envExample)) {
        Copy-Item -LiteralPath $envExample -Destination $envPath -Force
        $RunSmoke = $false
        Write-Host '[warn] .env was missing; created it from .env.example.' -ForegroundColor Yellow
        Write-Host '[warn] Fill ROUTER_BASE_URL/ROUTER_API_KEY before using LLM tools. Smoke skipped this run.' -ForegroundColor Yellow
    } else {
        throw 'Missing .env. Copy .env.example to .env and fill 9Router credentials.'
    }
} else {
    Write-Host '[ok] .env found'
}

Write-Step '1/9 Install Python dependencies'
Invoke-Python @('-m','pip','install','-r', (Join-Path $Root 'requirements.txt'), '--disable-pip-version-check')

if ($InstallPlaywright) {
    Write-Step '2/9 Install Playwright Chromium'
    Invoke-OptionalPython @('-m','playwright','install','chromium') 'Playwright Chromium install failed; visual_reviewer may fall back to static analysis.'
} else {
    Write-Step '2/9 Skip Playwright Chromium'
}

Write-Step '3/9 Sync MCP configs, memory rules, and agent hooks'
Invoke-Python @((Join-Path $Root 'merge_settings.py'))

Write-Step '4/9 Register Claude Code MCP when claude CLI exists'
if (Get-Command claude -ErrorAction SilentlyContinue) {
    $ErrorActionPreference = 'Continue'
    claude mcp remove --scope user agent-harness 2>$null | Out-Null
    $ErrorActionPreference = 'Stop'
    $claudeArgs = @('mcp','add','--scope','user','agent-harness','--',$script:Python.Command) + $script:Python.Prefix + @((Join-Path $Root 'mcp_server.py'))
    & claude @claudeArgs
    if ($LASTEXITCODE -ne 0) { throw 'claude mcp add failed.' }
    Write-Host '[ok] Claude MCP registered'
} else {
    Write-Host '[warn] claude CLI not found; skipped Claude CLI registration. merge_settings.py still wrote MCP config files.' -ForegroundColor Yellow
}

Write-Step '5/9 Write runtime feature profile'
Invoke-Toggle @('profile', $Profile)
if ($Profile -eq 'max') {
    $featureCommands = @(
        @('set','llm','on'),
        @('set','finops','on'),
        @('set','hooks','on'),
        @('set','lessons','on'),
        @('set','auto-pilot','on'),
        @('set','auto-pilot-llm','on'),
        @('set','auto-watch','on'),
        @('set','auto-watch-llm','on'),
        @('set','static-llm','on'),
        @('set','wiki','on'),
        @('set','code-index','on'),
        @('set','dashboard','on'),
        @('mode','auto-pilot','max'),
        @('mode','auto-watch','max'),
        @('timing','2','1')
    )
    foreach ($cmd in $featureCommands) {
        Invoke-Toggle $cmd
    }
} elseif ($Profile -eq 'off') {
    Write-Host '[ok] Default-safe install: runtime profile is off, so no background/LLM/token features are enabled.'
} else {
    Write-Host "[ok] Runtime profile '$Profile' written using harness-toggle.bat defaults."
}
Write-Host "[ok] Runtime features written to $FeatureFile"

Write-Step '6/9 Install repository git pre-commit hook'
if ($InstallGitHook) {
    if (Test-Path (Join-Path $Root '.git')) {
        Invoke-Python @((Join-Path $Root 'install_hooks.py'))
    } else {
        Write-Host '[warn] This folder is not a git repo; skipped install_hooks.py.' -ForegroundColor Yellow
    }
} else {
    Write-Host '[skip] --no-git-hook'
}

Write-Step '7/9 Bootstrap global wiki memory'
if ($CopyWikiGlobal) {
    $sourceWiki = Join-Path $Root 'llmwiki'
    $destWiki = Join-Path $HOME '.claude\llmwiki'
    if (Test-Path $sourceWiki) {
        Copy-DirMerge $sourceWiki $destWiki
        Write-Host "[ok] Copied llmwiki into $destWiki"
    } else {
        Write-Host '[warn] No repo llmwiki/ found; skipped global wiki copy.' -ForegroundColor Yellow
    }
} else {
    Write-Host '[skip] --no-global-wiki'
}

Write-Step '8/9 Install/start background helpers'
if ($InstallStartupTask) {
    Install-WatchStartupTask
} else {
    Write-Host '[skip] --no-startup-task'
}
if ($StartWatch) {
    Invoke-Toggle @('action','watch','start')
    Write-Host '[ok] Auto-Watch start requested for this harness folder. For other projects, it will also spawn after first MCP call when auto-watch is enabled.'
} else {
    if ($Profile -eq 'off') {
        Write-Host '[skip] Default profile off; watcher is not started.'
    } else {
        Write-Host '[skip] --no-watch; auto-watch state follows the selected profile.'
    }
}
if ($StartDashboard) {
    Invoke-Toggle @('action','dashboard','start')
} else {
    Write-Host '[skip] Dashboard server not started. Use --start-dashboard or harness-toggle.bat action dashboard start.'
}

Write-Step '9/9 Verify install'
Invoke-Toggle @('status')
if ($RunSmoke) {
    Invoke-Python @((Join-Path $Root 'smoke_test.py'))
} else {
    Write-Host '[skip] smoke_test.py'
}

Write-Host ''
Write-Host '=== FULL SETUP DONE ===' -ForegroundColor Green
Write-Host 'Restart Claude/Gemini/Codex/IDE sessions so they reload MCP config and memory rules.'
Write-Host 'MCP-only tools installed: integration_router, hallmark_bridge, speckit_bridge, office_bridge, scope_creep_detector, router_quota_status.'
Write-Host 'Quota reminder config lives in .env: HARNESS_QUOTA_* and HARNESS_ROUTER_QUOTA_*.'
Write-Host 'Future maintenance: when a runtime feature changes, update harness-toggle.bat and harness-full-setup.bat together.'
