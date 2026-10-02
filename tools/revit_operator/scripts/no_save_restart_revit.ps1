param(
    [Parameter(Mandatory = $true)]
    [string] $Sandbox,

    [string] $ModelPath = "C:\Users\zeviel.persellin\IdeaProjects\Tools\_Hermes_WorkingCopies\24522_St_John_XXIII_Youth_Pavilion\Drawings\Working Drawings\24522 St John XXIII Youth Pavilion-Structural_Current Working-R25-BIM.rvt",

    [string] $RevitExe = "C:\Program Files\Autodesk\Revit 2025\Revit.exe",

    [string] $ExpectedTitleContains = "24522 St John XXIII Youth Pavilion-Structural_Current Working-R25-BIM",

    [int] $WaitSeconds = 300,

    [switch] $AllowDirtyDiscard,

    [switch] $WhatIfOnly
)

$ErrorActionPreference = "Stop"

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string] $Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Write-JsonFile {
    param(
        [Parameter(Mandatory = $true)] [string] $Path,
        [Parameter(Mandatory = $true)] $Value
    )
    $json = $Value | ConvertTo-Json -Depth 20
    Set-Content -LiteralPath $Path -Value $json -Encoding UTF8
}

function Invoke-RevitOperator {
    param(
        [Parameter(Mandatory = $true)] [string] $TaskId,
        [Parameter(Mandatory = $true)] [string[]] $Arguments
    )
    Push-Location $RepoRoot
    try {
        $allArgs = @(
            "-m", "tools.revit_operator.cli",
            "--sandbox", $Sandbox,
            "--task-id", $TaskId
        ) + $Arguments
        $stdout = & python @allArgs 2>&1
        $exit = $LASTEXITCODE
        $text = ($stdout | Out-String).Trim()
        $parsed = $null
        if ($text) {
            try {
                $jsonStart = $text.IndexOf("{")
                $jsonEnd = $text.LastIndexOf("}")
                if ($jsonStart -ge 0 -and $jsonEnd -gt $jsonStart) {
                    $jsonText = $text.Substring($jsonStart, $jsonEnd - $jsonStart + 1)
                    $parsed = $jsonText | ConvertFrom-Json
                }
            } catch {
                $parsed = $null
            }
        }
        return [pscustomobject]@{
            exit_code = $exit
            stdout = $text
            json = $parsed
            task_id = $TaskId
            arguments = $Arguments
        }
    } finally {
        Pop-Location
    }
}

function Get-NestedValue {
    param(
        [Parameter(Mandatory = $true)] $Object,
        [Parameter(Mandatory = $true)] [string[]] $Path
    )
    $current = $Object
    foreach ($part in $Path) {
        if ($null -eq $current) {
            return $null
        }
        $property = $current.PSObject.Properties[$part]
        if ($null -eq $property) {
            return $null
        }
        $current = $property.Value
    }
    return $current
}

function Add-Step {
    param(
        [Parameter(Mandatory = $true)] [string] $Name,
        [Parameter(Mandatory = $true)] [string] $Status,
        $Data = $null
    )
    $script:Steps += [pscustomobject]@{
        name = $Name
        status = $Status
        data = $Data
        timestamp_utc = [DateTime]::UtcNow.ToString("o")
    }
    Write-JsonFile -Path $script:AuditPath -Value (New-AuditObject -Status "running")
}

function New-AuditObject {
    param([string] $Status = "running")
    return [pscustomobject]@{
        status = $Status
        generated_at_utc = [DateTime]::UtcNow.ToString("o")
        sandbox = $Sandbox
        run_dir = $script:RunDir
        model_path = $ModelPath
        revit_exe = $RevitExe
        expected_title_contains = $ExpectedTitleContains
        allow_dirty_discard = [bool] $AllowDirtyDiscard
        what_if_only = [bool] $WhatIfOnly
        safety_policy = [pscustomobject]@{
            no_save = $true
            no_sync = $true
            no_relinquish = $true
            no_reload_links = $true
            no_detach_or_upgrade = $true
            no_central_or_cloud_write = $true
            kill_process_instead_of_save_prompt = $true
        }
        steps = $script:Steps
    }
}

$RepoRoot = Resolve-FullPath (Join-Path $PSScriptRoot "..\..\..")
$Sandbox = Resolve-FullPath $Sandbox
$ModelPath = Resolve-FullPath $ModelPath
$RevitExe = Resolve-FullPath $RevitExe

if (-not (Test-Path -LiteralPath $Sandbox -PathType Container)) {
    New-Item -ItemType Directory -Path $Sandbox | Out-Null
}
if ($Sandbox -notlike "*_AI_Hermes_Sandbox_DO_NOT_USE_FOR_PERMIT*") {
    throw "Refusing no-save restart because sandbox is not the approved Hermes AI sandbox: $Sandbox"
}
if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
    throw "Model path does not exist: $ModelPath"
}
if (-not (Test-Path -LiteralPath $RevitExe -PathType Leaf)) {
    throw "Revit executable does not exist: $RevitExe"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$RunDir = Join-Path $Sandbox "revit_no_save_restart_$timestamp"
New-Item -ItemType Directory -Path $RunDir | Out-Null
$AuditPath = Join-Path $RunDir "no_save_restart_audit.json"
$Steps = @()
Write-JsonFile -Path $AuditPath -Value (New-AuditObject -Status "running")

try {
    Add-Step -Name "preflight_status" -Status "running"
    $statusResult = Invoke-RevitOperator -TaskId "no-save-restart-preflight-$timestamp" -Arguments @("status")
    if ($statusResult.exit_code -ne 0 -or $null -eq $statusResult.json) {
        throw "Could not read Revit operator status before restart."
    }
    $status = $statusResult.json
    $mainWindow = $status.main_window
    $doc = Get-NestedValue -Object $status -Path @("active_document", "document", "document")
    $revitPid = $mainWindow.pid
    $title = [string] $mainWindow.title
    $processPath = Resolve-FullPath ([string] $mainWindow.process_path)
    $dirty = [bool] (Get-NestedValue -Object $doc -Path @("dirty"))
    $centralPath = [string] (Get-NestedValue -Object $doc -Path @("central_path"))

    if (-not $status.revit_running -or -not $revitPid) {
        throw "No running Revit process was found for restart."
    }
    if ($processPath -ne $RevitExe) {
        throw "Running Revit path does not match expected Revit 2025 executable. Observed: $processPath"
    }
    if ($title -notlike "*$ExpectedTitleContains*") {
        throw "Active Revit title does not match the copied local test model. Observed: $title"
    }
    if ($centralPath) {
        throw "Active document reports a non-empty central path; refusing no-save automation. Observed central path: $centralPath"
    }
    if ($dirty -and -not $AllowDirtyDiscard) {
        throw "Active copied-local model is dirty. Re-run with -AllowDirtyDiscard to explicitly discard local unsaved session changes without saving."
    }
    Add-Step -Name "preflight_status" -Status "passed" -Data @{
        pid = $revitPid
        title = $title
        process_path = $processPath
        document_dirty = $dirty
        central_path = $centralPath
        active_document_title = (Get-NestedValue -Object $doc -Path @("title"))
        active_view_name = (Get-NestedValue -Object $doc -Path @("active_view", "name"))
        active_view_type = (Get-NestedValue -Object $doc -Path @("active_view", "type"))
    }

    Add-Step -Name "archive_stale_bridge_files" -Status "running"
    $bridgeDir = Join-Path $Sandbox "bridge"
    $archiveDir = Join-Path $RunDir "pre_restart_bridge_archive"
    New-Item -ItemType Directory -Path $archiveDir | Out-Null
    $archived = @()
    if (Test-Path -LiteralPath $bridgeDir -PathType Container) {
        foreach ($name in @("addin_status.json", "addin_heartbeat.json", "active_document.json")) {
            $source = Join-Path $bridgeDir $name
            if (Test-Path -LiteralPath $source -PathType Leaf) {
                $target = Join-Path $archiveDir $name
                Copy-Item -LiteralPath $source -Destination $target -Force
                Remove-Item -LiteralPath $source -Force
                $archived += $target
            }
        }
    }
    Add-Step -Name "archive_stale_bridge_files" -Status "passed" -Data @{ archived = $archived }

    if ($WhatIfOnly) {
        Add-Step -Name "what_if_stop_before_process_kill" -Status "passed"
        Write-JsonFile -Path $AuditPath -Value (New-AuditObject -Status "what_if_complete")
        Write-Output (Get-Content -LiteralPath $AuditPath -Raw)
        exit 0
    }

    Add-Step -Name "force_stop_revit_without_save" -Status "running" -Data @{ pid = $revitPid }
    Stop-Process -Id $revitPid -Force
    $deadline = (Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Seconds 1
        $stillRunning = Get-Process -Id $revitPid -ErrorAction SilentlyContinue
    } while ($stillRunning -and (Get-Date) -lt $deadline)
    if ($stillRunning) {
        throw "Revit process $revitPid did not exit after force stop."
    }
    Add-Step -Name "force_stop_revit_without_save" -Status "passed" -Data @{ pid = $revitPid }

    Add-Step -Name "launch_revit_with_copied_local_model" -Status "running"
    $process = Start-Process -FilePath $RevitExe -ArgumentList ('"' + $ModelPath + '"') -PassThru
    Add-Step -Name "launch_revit_with_copied_local_model" -Status "passed" -Data @{
        pid = $process.Id
        model_path = $ModelPath
    }

    Add-Step -Name "wait_for_revit_observable" -Status "running"
    $observable = $null
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    do {
        Start-Sleep -Seconds 5
        $waitResult = Invoke-RevitOperator -TaskId "no-save-restart-observe-$timestamp" -Arguments @("status")
        if ($waitResult.exit_code -eq 0 -and $null -ne $waitResult.json -and $waitResult.json.revit_running) {
            $observable = $waitResult.json
            $hasWindow = $null -ne $observable.main_window
            $hasDialog = ($observable.active_dialogs | Measure-Object).Count -gt 0
            if ($hasWindow -or $hasDialog) {
                break
            }
        }
    } while ((Get-Date) -lt $deadline)
    if ($null -eq $observable) {
        throw "Revit was relaunched but did not become observable within $WaitSeconds seconds."
    }
    Add-Step -Name "wait_for_revit_observable" -Status "passed" -Data @{
        state = $observable.state
        dialog_count = ($observable.active_dialogs | Measure-Object).Count
        title = $observable.main_window.title
    }

    Write-JsonFile -Path $AuditPath -Value (New-AuditObject -Status "complete")
    Write-Output (Get-Content -LiteralPath $AuditPath -Raw)
} catch {
    Add-Step -Name "failure" -Status "failed" -Data @{
        message = $_.Exception.Message
        category = $_.CategoryInfo.Category
    }
    Write-JsonFile -Path $AuditPath -Value (New-AuditObject -Status "failed")
    Write-Output (Get-Content -LiteralPath $AuditPath -Raw)
    exit 1
}
