@echo off
setlocal EnableExtensions
set "HARNESS_TOGGLE_BAT=%~f0"
set "HARNESS_TOGGLE_ROOT=%~dp0"
set "HARNESS_TOGGLE_MARKER=###HARNESS_TOGGLE_PS_"
set "HARNESS_TOGGLE_MARKER=%HARNESS_TOGGLE_MARKER%PAYLOAD###"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:HARNESS_TOGGLE_BAT); $i=$s.IndexOf($env:HARNESS_TOGGLE_MARKER); if($i -lt 0){Write-Error 'PowerShell payload missing'; exit 2}; & ([scriptblock]::Create($s.Substring($i))) @args" %*
exit /b %ERRORLEVEL%

###HARNESS_TOGGLE_PS_PAYLOAD###
$Argv = @($args | ForEach-Object { [string]$_ })

$Root = (Resolve-Path $env:HARNESS_TOGGLE_ROOT).Path
$UserHome = [Environment]::GetFolderPath('UserProfile')
if (-not $UserHome) { $UserHome = $env:USERPROFILE }
if (-not $UserHome) { throw 'Cannot resolve user profile directory for global Agent Harness config.' }
$FeatureDir = Join-Path $UserHome '.agent-harness'
$FeatureFile = Join-Path $FeatureDir 'harness.features.json'
$ErrorActionPreference = 'Stop'
$script:InteractiveProfileWrite = $false

function New-Obj { [pscustomobject]@{} }

function Ensure-Prop($Obj, [string]$Name, $Value) {
    if (-not $Obj.PSObject.Properties[$Name]) {
        Add-Member -InputObject $Obj -NotePropertyName $Name -NotePropertyValue $Value
    }
    return $Obj.PSObject.Properties[$Name].Value
}

function Require-ProfileWriteConsent([string]$Action) {
    if ($script:InteractiveProfileWrite) { return }
    if ($env:HARNESS_ALLOW_PROFILE_WRITE -match '^(1|true|yes|on)$') { return }
    throw "Blocked profile write '$Action'. Agents/non-interactive shells cannot change global harness.features.json unless HARNESS_ALLOW_PROFILE_WRITE=1 is set. Open harness-toggle.bat with no args for the user menu."
}

function Load-Features([bool]$Strict = $false) {
    if (Test-Path $FeatureFile) {
        try {
            $raw = [IO.File]::ReadAllText($FeatureFile)
            if ($raw.Trim()) {
                $obj = ConvertFrom-Json -InputObject $raw
                if ($obj) { return $obj }
            }
        } catch {
            if ($Strict) { throw "Cannot parse $FeatureFile; fix the JSON or delete/repair the file before writing profile changes. $($_.Exception.Message)" }
            Write-Warning "Cannot parse $FeatureFile; rebuilding it."
        }
    }
    return New-Obj
}

function Ensure-Defaults($J) {
    Ensure-Prop $J 'profile' 'custom' | Out-Null
    Ensure-Prop $J 'description' 'Written by harness-toggle.bat.' | Out-Null
    $llm = Ensure-Prop $J 'llm' (New-Obj)
    Ensure-Prop $llm 'enabled' $true | Out-Null
    Ensure-Prop $llm 'static' $false | Out-Null
    $finops = Ensure-Prop $J 'finops' (New-Obj)
    Ensure-Prop $finops 'enabled' $true | Out-Null
    $hooks = Ensure-Prop $J 'hooks' (New-Obj)
    Ensure-Prop $hooks 'enabled' $true | Out-Null
    $lessons = Ensure-Prop $J 'lessons' (New-Obj)
    Ensure-Prop $lessons 'enabled' $true | Out-Null
    $auto = Ensure-Prop $J 'auto_pilot' (New-Obj)
    Ensure-Prop $auto 'enabled' $true | Out-Null
    Ensure-Prop $auto 'mode' 'safe' | Out-Null
    Ensure-Prop $auto 'llm' $false | Out-Null
    $watch = Ensure-Prop $J 'auto_watch' (New-Obj)
    Ensure-Prop $watch 'enabled' $false | Out-Null
    Ensure-Prop $watch 'mode' 'safe' | Out-Null
    Ensure-Prop $watch 'llm' $false | Out-Null
    Ensure-Prop $watch 'interval' 3 | Out-Null
    Ensure-Prop $watch 'debounce' 2 | Out-Null
    Ensure-Prop $J 'static_llm' $false | Out-Null
    $manual = Ensure-Prop $J 'manual_features' (New-Obj)
    foreach ($manualName in @('hooks','lessons','llmwiki','code_index','finops','dashboard')) {
        $item = Ensure-Prop $manual $manualName (New-Obj)
        Ensure-Prop $item 'enabled' ($manualName -ne 'dashboard') | Out-Null
        Ensure-Prop $item 'status' 'manual' | Out-Null
        Ensure-Prop $item 'note' '' | Out-Null
    }
    $manual.hooks.status = 'soft-toggle'
    $manual.hooks.note = 'Global hook config remains installed; hooks.enabled=false still allows read-only profile snapshot injection, but disables lesson/edit hook work.'
    $manual.lessons.status = 'soft-toggle'
    $manual.lessons.note = 'Disables lesson write/inject paths without deleting existing lesson DB files.'
    $manual.llmwiki.status = 'on_demand'
    $manual.llmwiki.note = 'Preference only; wiki tools run when explicitly called.'
    $manual.code_index.status = 'on_demand'
    $manual.code_index.note = 'Preference only; code index tools run when explicitly called.'
    $manual.finops.status = 'soft-toggle'
    $manual.finops.note = 'Disables new FinOps DB writes when finops.enabled=false.'
    $manual.dashboard.status = 'manual'
    $manual.dashboard.note = 'Only runs when dashboard start is requested.'
    return $J
}

function Save-Features($J) {
    $J = Ensure-Defaults $J
    $json = ConvertTo-Json -InputObject $J -Depth 20
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    New-Item -ItemType Directory -Force $FeatureDir | Out-Null
    $mutex = New-Object System.Threading.Mutex($false, 'Global\AgentHarnessFeatures')
    $locked = $false
    $tmp = Join-Path $FeatureDir ("harness.features.{0}.tmp" -f ([guid]::NewGuid().ToString('N')))
    $backup = Join-Path $FeatureDir ("harness.features.{0}.bak" -f ([guid]::NewGuid().ToString('N')))
    try {
        $locked = $mutex.WaitOne(30000)
        if (-not $locked) { throw 'Timed out waiting for global feature profile lock.' }
        [IO.File]::WriteAllText($tmp, $json + [Environment]::NewLine, $utf8)
        if (Test-Path $FeatureFile) {
            [IO.File]::Replace($tmp, $FeatureFile, $backup, $true)
        } else {
            [IO.File]::Move($tmp, $FeatureFile)
        }
    } finally {
        if (Test-Path $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
        if (Test-Path $backup) { Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue }
        if ($locked) { $mutex.ReleaseMutex() | Out-Null }
        $mutex.Dispose()
    }
}

function To-Bool([string]$Raw) {
    if ($null -eq $Raw) { $Raw = '' }
    switch -Regex ($Raw.Trim().ToLowerInvariant()) {
        '^(1|true|yes|on|enable|enabled)$' { return $true }
        '^(0|false|no|off|disable|disabled)$' { return $false }
        default { throw "Expected on/off, got '$Raw'." }
    }
}

function Set-Manual($J, [string]$Name, [bool]$Value) {
    $manual = Ensure-Prop $J 'manual_features' (New-Obj)
    $item = Ensure-Prop $manual $Name (New-Obj)
    $item.enabled = $Value
    $item.status = if ($Value) { 'enabled' } else { 'disabled' }
}

function Get-Feature($J, [string]$Name) {
    $J = Ensure-Defaults $J
    switch ($Name) {
        'llm' { return [bool]$J.llm.enabled }
        'finops' { return [bool]$J.finops.enabled }
        'hooks' { return [bool]$J.hooks.enabled }
        'lessons' { return [bool]$J.lessons.enabled }
        'auto-pilot' { return [bool]$J.auto_pilot.enabled }
        'auto-pilot-llm' { return [bool]$J.auto_pilot.llm }
        'auto-watch' { return [bool]$J.auto_watch.enabled }
        'auto-watch-llm' { return [bool]$J.auto_watch.llm }
        'static-llm' { return [bool]$J.static_llm }
        'wiki' { return [bool]$J.manual_features.llmwiki.enabled }
        'code-index' { return [bool]$J.manual_features.code_index.enabled }
        'dashboard' { return [bool]$J.manual_features.dashboard.enabled }
        default { throw "Unknown feature '$Name'. Run: harness-toggle.bat list" }
    }
}

function Feature-Note([string]$Name) {
    switch ($Name) {
        'llm' { return 'Hard kill-switch: off = no 9Router/model calls at all.' }
        'finops' { return 'Token/cost SQLite logging. Off reduces DB writes; does not affect model calls.' }
        'hooks' { return 'Client hook bridge. Off = only read-only profile snapshot injection remains; lesson/edit hook work stops.' }
        'lessons' { return 'Lesson memory write/inject/background learning. Off keeps old data but stops new capture.' }
        'auto-pilot' { return 'Contextual auto_trigger checks after edits/final gates.' }
        'auto-pilot-llm' { return 'Allows Auto-Pilot selected checks to call LLM review tools.' }
        'auto-watch' { return 'Global background file watcher. One supervisor reads ~/.agent-harness/watch.repos.json; keep off on slow machines.' }
        'auto-watch-llm' { return 'Allows watcher-triggered checks to call LLM tools.' }
        'static-llm' { return 'Optional LLM enrichment for static-first analyzers/gap tools.' }
        'wiki' { return 'On-demand llmwiki preference marker; no daemon by itself.' }
        'code-index' { return 'On-demand semantic/code index preference marker; builds when requested.' }
        'dashboard' { return 'Manual web dashboard marker; action dashboard start launches server.py.' }
        'mcp-bridges' { return 'Read-only/static MCP tools: install manifest, graph review, adapter parity, MCP inventory, context budget, workflow/UI routers, bug repro guard, Hallmark/Spec Kit, Office bridge, scope guard. No profile toggle needed.' }
        'auto-pilot-mode' { return 'safe = conservative checks, max = aggressive fan-out.' }
        'auto-watch-mode' { return 'safe/max mode used by watcher-triggered Auto-Pilot.' }
        'auto-watch-time' { return 'Polling interval and debounce seconds for watcher.' }
        default { return '' }
    }
}

function Watch-Procs {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*auto_watch.py*' -and $_.CommandLine -like ('*' + $Root + '*') }
}

function Stop-Watch {
    $items = @(Watch-Procs)
    foreach ($p in $items) {
        Stop-Process -Id $p.ProcessId -Force
        Write-Host "stopped auto_watch pid=$($p.ProcessId)"
    }
    if (-not $items) { Write-Host 'no auto_watch process found' }
}

function Set-Feature([string]$Name, [bool]$Value) {
    Require-ProfileWriteConsent "set $Name"
    $j = Ensure-Defaults (Load-Features $true)
    $j.profile = 'custom'
    switch ($Name) {
        'llm' { $j.llm.enabled = $Value }
        'finops' { $j.finops.enabled = $Value; Set-Manual $j 'finops' $Value }
        'hooks' { $j.hooks.enabled = $Value; Set-Manual $j 'hooks' $Value }
        'lessons' { $j.lessons.enabled = $Value; Set-Manual $j 'lessons' $Value }
        'auto-pilot' { $j.auto_pilot.enabled = $Value }
        'auto-pilot-llm' { $j.auto_pilot.llm = $Value }
        'auto-watch' { $j.auto_watch.enabled = $Value; if (-not $Value) { Stop-Watch } }
        'auto-watch-llm' { $j.auto_watch.llm = $Value }
        'static-llm' { $j.static_llm = $Value; $j.llm.static = $Value }
        'wiki' { Set-Manual $j 'llmwiki' $Value }
        'code-index' { Set-Manual $j 'code_index' $Value }
        'dashboard' { Set-Manual $j 'dashboard' $Value }
        default { throw "Unknown feature '$Name'. Run: harness-toggle.bat list" }
    }
    Save-Features $j
    Write-Host "$Name = $Value"
}

function Set-Mode([string]$Name, [string]$Mode) {
    Require-ProfileWriteConsent "mode $Name"
    $mode = $Mode.ToLowerInvariant()
    if ($mode -notin @('safe','max')) { throw "Mode must be safe or max." }
    $j = Ensure-Defaults (Load-Features $true)
    $j.profile = 'custom'
    switch ($Name) {
        'auto-pilot' { $j.auto_pilot.mode = $mode }
        'auto-watch' { $j.auto_watch.mode = $mode }
        default { throw "Mode is supported for auto-pilot or auto-watch only." }
    }
    Save-Features $j
    Write-Host "$Name mode = $mode"
}

function Set-Timing([double]$Interval, [double]$Debounce) {
    Require-ProfileWriteConsent 'timing'
    if ($Interval -lt 0.5 -or $Interval -gt 300) { throw 'Interval must be between 0.5 and 300 seconds.' }
    if ($Debounce -lt 0.5 -or $Debounce -gt 300) { throw 'Debounce must be between 0.5 and 300 seconds.' }
    $j = Ensure-Defaults (Load-Features $true)
    $j.profile = 'custom'
    $j.auto_watch.interval = $Interval
    $j.auto_watch.debounce = $Debounce
    Save-Features $j
    Write-Host "auto-watch timing interval=$Interval debounce=$Debounce"
}

function Set-Profile([string]$Name) {
    Require-ProfileWriteConsent "profile $Name"
    $requested = $Name.ToLowerInvariant()
    $profile = switch ($requested) {
        '4' { 'balanced' }
        '5' { 'review' }
        '7' { 'heavy' }
        default { $requested }
    }
    $j = Ensure-Defaults (New-Obj)
    $j.profile = $profile
    $j.description = "Profile '$profile' written by harness-toggle.bat."
    switch ($profile) {
        'off' {
            $j.auto_pilot.enabled = $false
            $j.auto_pilot.llm = $false
            $j.auto_watch.enabled = $false
            $j.auto_watch.llm = $false
            $j.static_llm = $false
            $j.llm.enabled = $false
            $j.llm.static = $false
            $j.finops.enabled = $false
            $j.hooks.enabled = $false
            $j.lessons.enabled = $false
            Set-Manual $j 'finops' $false
            Set-Manual $j 'hooks' $false
            Set-Manual $j 'lessons' $false
            Set-Manual $j 'dashboard' $false
            Stop-Watch
        }
        'light' {
            $j.auto_pilot.enabled = $true
            $j.auto_pilot.mode = 'safe'
            $j.auto_pilot.llm = $false
            $j.auto_watch.enabled = $false
            $j.auto_watch.mode = 'safe'
            $j.auto_watch.llm = $false
            $j.auto_watch.interval = 3
            $j.auto_watch.debounce = 2
            $j.static_llm = $false
            $j.llm.enabled = $true
            $j.llm.static = $false
            $j.finops.enabled = $true
            $j.hooks.enabled = $true
            $j.lessons.enabled = $true
            Set-Manual $j 'finops' $true
            Set-Manual $j 'hooks' $true
            Set-Manual $j 'lessons' $true
            Set-Manual $j 'llmwiki' $true
            Set-Manual $j 'code_index' $true
            Set-Manual $j 'dashboard' $false
            Stop-Watch
        }
        'standard' {
            $j.auto_pilot.enabled = $true
            $j.auto_pilot.mode = 'safe'
            $j.auto_pilot.llm = $false
            $j.auto_watch.enabled = $true
            $j.auto_watch.mode = 'safe'
            $j.auto_watch.llm = $false
            $j.auto_watch.interval = 3
            $j.auto_watch.debounce = 2
            $j.static_llm = $false
            $j.llm.enabled = $true
            $j.llm.static = $false
            $j.finops.enabled = $true
            $j.hooks.enabled = $true
            $j.lessons.enabled = $true
            Set-Manual $j 'finops' $true
            Set-Manual $j 'hooks' $true
            Set-Manual $j 'lessons' $true
            Set-Manual $j 'llmwiki' $true
            Set-Manual $j 'code_index' $true
        }
        'balanced' {
            $j.auto_pilot.enabled = $true
            $j.auto_pilot.mode = 'safe'
            $j.auto_pilot.llm = $true
            $j.auto_watch.enabled = $false
            $j.auto_watch.mode = 'safe'
            $j.auto_watch.llm = $false
            $j.auto_watch.interval = 3
            $j.auto_watch.debounce = 2
            $j.static_llm = $false
            $j.llm.enabled = $true
            $j.llm.static = $false
            $j.finops.enabled = $true
            $j.hooks.enabled = $true
            $j.lessons.enabled = $true
            Set-Manual $j 'finops' $true
            Set-Manual $j 'hooks' $true
            Set-Manual $j 'lessons' $true
            Set-Manual $j 'llmwiki' $true
            Set-Manual $j 'code_index' $true
            Stop-Watch
        }
        'review' {
            $j.auto_pilot.enabled = $true
            $j.auto_pilot.mode = 'safe'
            $j.auto_pilot.llm = $true
            $j.auto_watch.enabled = $true
            $j.auto_watch.mode = 'safe'
            $j.auto_watch.llm = $false
            $j.auto_watch.interval = 3
            $j.auto_watch.debounce = 2
            $j.static_llm = $true
            $j.llm.enabled = $true
            $j.llm.static = $true
            $j.finops.enabled = $true
            $j.hooks.enabled = $true
            $j.lessons.enabled = $true
            Set-Manual $j 'finops' $true
            Set-Manual $j 'hooks' $true
            Set-Manual $j 'lessons' $true
            Set-Manual $j 'llmwiki' $true
            Set-Manual $j 'code_index' $true
        }
        'heavy' {
            $j.auto_pilot.enabled = $true
            $j.auto_pilot.mode = 'max'
            $j.auto_pilot.llm = $true
            $j.auto_watch.enabled = $false
            $j.auto_watch.mode = 'safe'
            $j.auto_watch.llm = $false
            $j.auto_watch.interval = 3
            $j.auto_watch.debounce = 2
            $j.static_llm = $true
            $j.llm.enabled = $true
            $j.llm.static = $true
            $j.finops.enabled = $true
            $j.hooks.enabled = $true
            $j.lessons.enabled = $true
            Set-Manual $j 'finops' $true
            Set-Manual $j 'hooks' $true
            Set-Manual $j 'lessons' $true
            Set-Manual $j 'llmwiki' $true
            Set-Manual $j 'code_index' $true
            Stop-Watch
        }
        'max' {
            $j.auto_pilot.enabled = $true
            $j.auto_pilot.mode = 'max'
            $j.auto_pilot.llm = $true
            $j.auto_watch.enabled = $true
            $j.auto_watch.mode = 'max'
            $j.auto_watch.llm = $true
            $j.auto_watch.interval = 2
            $j.auto_watch.debounce = 1
            $j.static_llm = $true
            $j.llm.enabled = $true
            $j.llm.static = $true
            $j.finops.enabled = $true
            $j.hooks.enabled = $true
            $j.lessons.enabled = $true
            Set-Manual $j 'finops' $true
            Set-Manual $j 'hooks' $true
            Set-Manual $j 'lessons' $true
        }
        default { throw "Unknown profile '$Name'. Use off, light, standard, balanced/4, review/5, heavy/7, or max." }
    }
    Save-Features $j
    Write-Host "profile = $profile"
}

function Start-Watch {
    Set-Feature 'auto-watch' $true
    $script = Join-Path $Root 'auto_watch.py'
    $cmd = Get-Command pythonw -ErrorAction SilentlyContinue
    if (-not $cmd) { $cmd = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $cmd) { throw 'python/pythonw not found on PATH.' }
    Start-Process -FilePath $cmd.Source -ArgumentList @($script) -WorkingDirectory $Root -WindowStyle Hidden
    Write-Host 'auto_watch global start requested'
}

function Start-Dashboard {
    Set-Feature 'dashboard' $true
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw 'python not found on PATH.' }
    Start-Process -FilePath $cmd.Source -ArgumentList @('server.py') -WorkingDirectory $Root -WindowStyle Hidden
    Write-Host 'dashboard start requested'
}

function Install-Hooks {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw 'python not found on PATH.' }
    & $cmd.Source (Join-Path $Root 'merge_settings.py')
}

function Install-GitHook {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { throw 'python not found on PATH.' }
    & $cmd.Source (Join-Path $Root 'install_hooks.py')
}

function Show-Status {
    $j = Ensure-Defaults (Load-Features)
    Write-Host "Global runtime file: $FeatureFile"
    Write-Host "Profile: $($j.profile)"
    Write-Host ''
    Write-Host ("{0,-16} {1,-7} {2}" -f 'feature', 'value', 'note')
    Write-Host ("{0,-16} {1,-7} {2}" -f '-------', '-----', '----')
    foreach ($featureName in @('llm','finops','hooks','lessons','auto-pilot','auto-pilot-llm','auto-watch','auto-watch-llm','static-llm','wiki','code-index','dashboard')) {
        Write-Host ("{0,-16} {1,-7} {2}" -f $featureName, (Get-Feature $j $featureName), (Feature-Note $featureName))
    }
    Write-Host ("{0,-16} {1,-7} {2}" -f 'auto-pilot-mode', $j.auto_pilot.mode, (Feature-Note 'auto-pilot-mode'))
    Write-Host ("{0,-16} {1,-7} {2}" -f 'auto-watch-mode', $j.auto_watch.mode, (Feature-Note 'auto-watch-mode'))
    Write-Host ("{0,-16} {1,-7} {2}" -f 'auto-watch-time', "i=$($j.auto_watch.interval)", "debounce=$($j.auto_watch.debounce). $(Feature-Note 'auto-watch-time')")
    Write-Host ("{0,-16} {1,-7} {2}" -f 'mcp-bridges', 'read', (Feature-Note 'mcp-bridges'))
    Write-Host ''
    $items = @(Watch-Procs)
    if ($items) {
        Write-Host 'auto_watch processes:'
        foreach ($p in $items) { Write-Host "  pid=$($p.ProcessId) $($p.Name)" }
    } else {
        Write-Host 'auto_watch processes: none'
    }
    $watchRegistry = Join-Path $FeatureDir 'watch.repos.json'
    $watchPid = Join-Path $FeatureDir 'auto_watch.global.pid'
    Write-Host "auto_watch global registry: $watchRegistry"
    if (Test-Path $watchPid) {
        Write-Host "auto_watch global pid file: $watchPid"
    }
}

function Show-Json {
    $j = Ensure-Defaults (Load-Features)
    ConvertTo-Json -InputObject $j -Depth 20
}

function Show-List {
@'
Features you can toggle:
  llm              Hard kill-switch: off = no 9Router/model calls at all.
  finops           Token/cost SQLite logging. Off reduces DB writes.
  hooks            Client hook bridge. Off = only profile snapshot injection remains.
  lessons          Lesson memory write/inject/background learning.
  auto-pilot       Contextual auto_trigger checks after edits/final gates.
  auto-pilot-llm   Allows Auto-Pilot selected checks to call LLM review tools.
  auto-watch       Global background file watcher; one supervisor watches registered repos.
  auto-watch-llm   Allows watcher-triggered checks to call LLM tools.
  static-llm       Optional LLM enrichment for static-first analyzers/gap tools.
  wiki             On-demand llmwiki preference marker; no daemon by itself.
  code-index       On-demand semantic/code index preference marker.
  dashboard        Manual web dashboard marker + dashboard start action.

MCP-only/read-only tools, installed by full setup and not toggled here:
  install_manifest     Dry-run setup manifest profiles/targets/check plan.
  adapter_parity_doctor Check Claude/Codex/Gemini/Antigravity rule + MCP drift.
  mcp_inventory        Inventory MCP configs and duplicated/drifted servers.
  context_budget       Estimate rules/skills/MCP token overhead + status.
  graph_minimal_context Ultra-compact local graph context before expensive tools.
  review_context_graph Static CRG-lite review pre-pass: changed symbols, blast radius, risk, test gaps, token savings.
  graph_health         Static graph health: hubs, bridge nodes, dead-code candidates, untested hotspots.
  integration_router   Static router for Hallmark UI + UI Skills + Spec Kit spec flows.
  workflow_router      Static router for BA, market research, UI/UX advisor, debug/spec/domain/review/TDD/architecture.
  bug_repro_guard      Static guard requiring red-capable repro before debug fixing.
  ui_skill_router      Static UI router; selects max 3 advisor/baseline/a11y/motion/metadata checks.
  hallmark_bridge      UI preflight/audit plan; write action still profile-gated.
  speckit_bridge       Spec status/snapshot; init/scaffold still profile-gated.
  office_bridge        Optional OfficeCLI adapter; mutations require allow_mutation.
  scope_creep_detector Static diff guard for unrelated dependency/config/API drift.

Profiles:
  off              0/10: hard-off; Auto-Pilot/hooks/lessons/FinOps/LLM off, watcher killed.
  light            1/10: recommended daily; Auto-Pilot safe, watcher off, auto LLM off.
  standard         2/10: watcher safe on; manual LLM allowed, auto LLM enrichment off.
  balanced, 4      4/10: Auto-Pilot may use LLM; watcher off, static LLM off.
  review, 5        5/10: Auto-Pilot LLM + static LLM; watcher safe, watcher LLM off.
  heavy, 7         7/10: Auto-Pilot max + static LLM; watcher off unless enabled separately.
  max              8-9/10: aggressive checks + fast global watcher + LLM enrichment.

Commands:
  harness-toggle.bat status
  harness-toggle.bat json
  harness-toggle.bat list
  harness-toggle.bat profile off|light|standard|balanced|review|heavy|max
  harness-toggle.bat set <feature> on|off
  harness-toggle.bat toggle <feature>
  harness-toggle.bat mode auto-pilot|auto-watch safe|max
  harness-toggle.bat timing <interval_seconds> <debounce_seconds>
  harness-toggle.bat action watch start|kill
  harness-toggle.bat action hooks install
  harness-toggle.bat action git-hook install
  harness-toggle.bat action dashboard start

Write guard:
  Profile/feature writes from CLI require HARNESS_ALLOW_PROFILE_WRITE=1.
  The interactive menu opened by double-click/no args is treated as user-approved.

Shortcuts:
  harness-toggle.bat off
  harness-toggle.bat light
  harness-toggle.bat standard
  harness-toggle.bat 4
  harness-toggle.bat 5
  harness-toggle.bat 7
  harness-toggle.bat balanced
  harness-toggle.bat review
  harness-toggle.bat heavy
  harness-toggle.bat max
  harness-toggle.bat watch-on
  harness-toggle.bat watch-off
  harness-toggle.bat kill-watch
'@
}

function Show-Menu {
    while ($true) {
        Clear-Host
        Write-Host 'Agent Harness Toggle Panel'
        Write-Host '=========================='
        Write-Host ''
        Show-Status
        Write-Host ''
        Write-Host '1  Profile: off         2  Profile: light      3  Profile: standard    4  Profile: balanced'
        Write-Host '   0/10 hard-off        1/10 daily            2/10 watcher safe       4/10 AP LLM'
        Write-Host '5  Profile: review      7  Profile: heavy      9  Profile: max'
        Write-Host '   5/10 static+AP LLM   7/10 AP max          8-9/10 heavy/LLM'
        Write-Host '20 Toggle Auto-Watch    21 Toggle Auto-Pilot   22 Toggle Lessons      23 Toggle Hooks'
        Write-Host '   daemon file watcher   auto checks           memory capture/inject    client hook bridge'
        Write-Host '24 Toggle FinOps        25 Toggle LLM          26 Toggle Static-LLM    27 Toggle Auto-Pilot-LLM'
        Write-Host '   DB cost logging       hard model kill       static tool enrich      auto checks can use LLM'
        Write-Host '28 Toggle Watch-LLM     29 Kill watcher        30 Show commands       0  Exit'
        Write-Host '   watcher can use LLM   stop current daemon   detailed help'
        Write-Host ''
        $choice = Read-Host 'Select'
        try {
            $script:InteractiveProfileWrite = $true
            switch ($choice.Trim().ToLowerInvariant()) {
                '0' { return }
                'q' { return }
                '1' { Set-Profile 'off' }
                '2' { Set-Profile 'light' }
                '3' { Set-Profile 'standard' }
                '4' { Set-Profile 'balanced' }
                '5' { Set-Profile 'review' }
                '7' { Set-Profile 'heavy' }
                '9' { Set-Profile 'max' }
                '20' { $j = Ensure-Defaults (Load-Features); Set-Feature 'auto-watch' (-not (Get-Feature $j 'auto-watch')) }
                '21' { $j = Ensure-Defaults (Load-Features); Set-Feature 'auto-pilot' (-not (Get-Feature $j 'auto-pilot')) }
                '22' { $j = Ensure-Defaults (Load-Features); Set-Feature 'lessons' (-not (Get-Feature $j 'lessons')) }
                '23' { $j = Ensure-Defaults (Load-Features); Set-Feature 'hooks' (-not (Get-Feature $j 'hooks')) }
                '24' { $j = Ensure-Defaults (Load-Features); Set-Feature 'finops' (-not (Get-Feature $j 'finops')) }
                '25' { $j = Ensure-Defaults (Load-Features); Set-Feature 'llm' (-not (Get-Feature $j 'llm')) }
                '26' { $j = Ensure-Defaults (Load-Features); Set-Feature 'static-llm' (-not (Get-Feature $j 'static-llm')) }
                '27' { $j = Ensure-Defaults (Load-Features); Set-Feature 'auto-pilot-llm' (-not (Get-Feature $j 'auto-pilot-llm')) }
                '28' { $j = Ensure-Defaults (Load-Features); Set-Feature 'auto-watch-llm' (-not (Get-Feature $j 'auto-watch-llm')) }
                '29' { Stop-Watch }
                '30' { Show-List }
                default { Write-Host "Unknown selection: $choice" }
            }
        } catch {
            Write-Host ("ERROR: " + $_.Exception.Message)
        } finally {
            $script:InteractiveProfileWrite = $false
        }
        Write-Host ''
        Read-Host 'Press Enter to continue' | Out-Null
    }
}

try {
    if (-not $Argv -or $Argv.Count -eq 0) { Show-Menu; exit 0 }
    $cmd = $Argv[0].ToLowerInvariant()
    switch ($cmd) {
        'status' { Show-Status }
        'json' { Show-Json }
        'list' { Show-List }
        'profile' { if ($Argv.Count -lt 2) { throw 'Missing profile.' }; Set-Profile $Argv[1] }
        'set' { if ($Argv.Count -lt 3) { throw 'Usage: set <feature> on|off' }; Set-Feature $Argv[1].ToLowerInvariant() (To-Bool $Argv[2]) }
        'toggle' { if ($Argv.Count -lt 2) { throw 'Usage: toggle <feature>' }; $j = Ensure-Defaults (Load-Features); Set-Feature $Argv[1].ToLowerInvariant() (-not (Get-Feature $j $Argv[1].ToLowerInvariant())) }
        'mode' { if ($Argv.Count -lt 3) { throw 'Usage: mode auto-pilot|auto-watch safe|max' }; Set-Mode $Argv[1].ToLowerInvariant() $Argv[2] }
        'timing' { if ($Argv.Count -lt 3) { throw 'Usage: timing <interval> <debounce>' }; Set-Timing ([double]$Argv[1]) ([double]$Argv[2]) }
        'action' {
            if ($Argv.Count -lt 3) { throw 'Usage: action watch start|kill OR action hooks install OR action dashboard start' }
            $target = $Argv[1].ToLowerInvariant()
            $verb = $Argv[2].ToLowerInvariant()
            if ($target -eq 'watch' -and $verb -eq 'start') { Start-Watch }
            elseif ($target -eq 'watch' -and $verb -eq 'kill') { Stop-Watch }
            elseif ($target -eq 'hooks' -and $verb -eq 'install') { Install-Hooks }
            elseif ($target -eq 'git-hook' -and $verb -eq 'install') { Install-GitHook }
            elseif ($target -eq 'dashboard' -and $verb -eq 'start') { Start-Dashboard }
            else { throw "Unknown action '$target $verb'." }
        }
        'off' { Set-Profile 'off' }
        'light' { Set-Profile 'light' }
        'standard' { Set-Profile 'standard' }
        'balanced' { Set-Profile 'balanced' }
        'review' { Set-Profile 'review' }
        'heavy' { Set-Profile 'heavy' }
        '4' { Set-Profile '4' }
        '5' { Set-Profile '5' }
        '7' { Set-Profile '7' }
        'max' { Set-Profile 'max' }
        'watch-on' { Set-Feature 'auto-watch' $true }
        'watch-off' { Set-Feature 'auto-watch' $false }
        'kill-watch' { Stop-Watch }
        default { Show-List; throw "Unknown command '$cmd'." }
    }
} catch {
    Write-Host ("ERROR: " + $_.Exception.Message)
    exit 1
}
