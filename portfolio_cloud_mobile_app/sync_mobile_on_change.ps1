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

$state = [hashtable]::Synchronized(@{
    LastChange = Get-Date
    Pending = $false
    Deploying = $false
})

$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $AppDir
$watcher.IncludeSubdirectories = $true
$watcher.NotifyFilter = [System.IO.NotifyFilters]'FileName, DirectoryName, LastWrite, Size'
$watcher.EnableRaisingEvents = $true

$action = {
    $state = $Event.MessageData
    if (Test-IgnoredPath -Path $Event.SourceEventArgs.FullPath) {
        return
    }
    $state.LastChange = Get-Date
    $state.Pending = $true
    Write-SyncLog "Detected change: $($Event.SourceEventArgs.ChangeType) $($Event.SourceEventArgs.FullPath)"
}

$registrations = @()
$registrations += Register-ObjectEvent -InputObject $watcher -EventName Changed -MessageData $state -Action $action
$registrations += Register-ObjectEvent -InputObject $watcher -EventName Created -MessageData $state -Action $action
$registrations += Register-ObjectEvent -InputObject $watcher -EventName Deleted -MessageData $state -Action $action
$registrations += Register-ObjectEvent -InputObject $watcher -EventName Renamed -MessageData $state -Action $action

Write-SyncLog "Mobile auto-sync watcher started for $AppDir"

try {
    while ($true) {
        Start-Sleep -Seconds 2
        if (-not $state.Pending -or $state.Deploying) {
            continue
        }
        $elapsed = (New-TimeSpan -Start $state.LastChange -End (Get-Date)).TotalSeconds
        if ($elapsed -lt $DebounceSeconds) {
            continue
        }
        $state.Pending = $false
        $state.Deploying = $true
        try {
            $message = "$MessagePrefix $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
            Write-SyncLog "Deploy started: $message"
            $stdoutPath = Join-Path $env:TEMP "portfolio_mobile_sync_stdout.log"
            $stderrPath = Join-Path $env:TEMP "portfolio_mobile_sync_stderr.log"
            Remove-Item -Path $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
            $process = Start-Process `
                -FilePath powershell.exe `
                -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$DeployScript`"", "-Message", "`"$message`"") `
                -WorkingDirectory $AppDir `
                -RedirectStandardOutput $stdoutPath `
                -RedirectStandardError $stderrPath `
                -NoNewWindow `
                -PassThru `
                -Wait
            if (Test-Path $stdoutPath) {
                Get-Content $stdoutPath -ErrorAction SilentlyContinue | Add-Content -Path $LogPath -Encoding UTF8
            }
            if (Test-Path $stderrPath) {
                Get-Content $stderrPath -ErrorAction SilentlyContinue | Add-Content -Path $LogPath -Encoding UTF8
            }
            if ($process.ExitCode -ne 0) {
                throw "Deploy process exited with code $($process.ExitCode)"
            }
            Write-SyncLog "Deploy finished"
        }
        catch {
            Write-SyncLog "Deploy failed: $($_.Exception.Message)"
        }
        finally {
            $state.Deploying = $false
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
