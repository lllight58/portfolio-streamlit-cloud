param(
    [int]$DebounceSeconds = 20,
    [string]$MessagePrefix = "Auto-sync Codex update"
)

$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DeployScript = Join-Path $AppDir "deploy_to_streamlit_cloud.ps1"
$LogPath = Join-Path $AppDir "mobile_sync.log"
$PidPath = Join-Path $AppDir "mobile_sync.pid"

Set-Content -Path $PidPath -Value $PID -Encoding ASCII

function Write-SyncLog {
    param([string]$Text)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogPath -Value "[$timestamp] $Text" -Encoding UTF8
}

function Test-IgnoredPath {
    param([string]$Path)
    $relative = $Path.Replace($AppDir, "").TrimStart("\", "/")
    if (-not $relative) {
        return $true
    }
    $ignoredPrefixes = @(
        ".git\",
        ".venv\",
        "__pycache__\",
        "data\",
        "backups\",
        "exports\"
    )
    foreach ($prefix in $ignoredPrefixes) {
        if ($relative.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    $ignoredNames = @(
        ".env",
        "mobile_sync.log",
        "mobile_sync.pid",
        "deploy_info.json"
    )
    return $ignoredNames -contains [System.IO.Path]::GetFileName($relative)
}

$script:lastChange = Get-Date
$script:pending = $false
$script:deploying = $false

$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $AppDir
$watcher.IncludeSubdirectories = $true
$watcher.NotifyFilter = [System.IO.NotifyFilters]'FileName, DirectoryName, LastWrite, Size'
$watcher.EnableRaisingEvents = $true

$action = {
    if (Test-IgnoredPath -Path $Event.SourceEventArgs.FullPath) {
        return
    }
    $script:lastChange = Get-Date
    $script:pending = $true
    Write-SyncLog "Detected change: $($Event.SourceEventArgs.ChangeType) $($Event.SourceEventArgs.FullPath)"
}

$registrations = @()
$registrations += Register-ObjectEvent -InputObject $watcher -EventName Changed -Action $action
$registrations += Register-ObjectEvent -InputObject $watcher -EventName Created -Action $action
$registrations += Register-ObjectEvent -InputObject $watcher -EventName Deleted -Action $action
$registrations += Register-ObjectEvent -InputObject $watcher -EventName Renamed -Action $action

Write-SyncLog "Mobile auto-sync watcher started for $AppDir"

try {
    while ($true) {
        Start-Sleep -Seconds 2
        if (-not $script:pending -or $script:deploying) {
            continue
        }
        $elapsed = (New-TimeSpan -Start $script:lastChange -End (Get-Date)).TotalSeconds
        if ($elapsed -lt $DebounceSeconds) {
            continue
        }
        $script:pending = $false
        $script:deploying = $true
        try {
            $message = "$MessagePrefix $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
            Write-SyncLog "Deploy started: $message"
            & powershell -NoProfile -ExecutionPolicy Bypass -File $DeployScript -Message $message *>> $LogPath
            Write-SyncLog "Deploy finished"
        }
        catch {
            Write-SyncLog "Deploy failed: $($_.Exception.Message)"
        }
        finally {
            $script:deploying = $false
        }
    }
}
finally {
    foreach ($registration in $registrations) {
        Unregister-Event -SubscriptionId $registration.Id -ErrorAction SilentlyContinue
    }
    $watcher.Dispose()
    Remove-Item -Path $PidPath -Force -ErrorAction SilentlyContinue
    Write-SyncLog "Mobile auto-sync watcher stopped"
}
