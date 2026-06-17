param(
    [string]$Message = "Update Streamlit Cloud app"
)

$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$WorkspaceDir = Split-Path -Parent $AppDir
$RepoDir = Join-Path $WorkspaceDir "portfolio_streamlit_cloud_repo"
$RepoUrl = "https://github.com/lllight58/portfolio-streamlit-cloud.git"
$Git = "C:\Program Files\Git\cmd\git.exe"

if (-not (Test-Path $Git)) {
    $Git = "git"
}

if (-not (Test-Path $RepoDir)) {
    & $Git clone $RepoUrl $RepoDir
}

& $Git -C $RepoDir pull --ff-only origin master

$TargetDir = Join-Path $RepoDir "portfolio_cloud_mobile_app"
if (-not (Test-Path $TargetDir)) {
    New-Item -ItemType Directory -Path $TargetDir | Out-Null
}

robocopy $AppDir $TargetDir /MIR `
    /XD ".git" ".venv" "__pycache__" "data" "backups" "exports" `
    /XF ".env" "secrets.toml" "*.pyc" "*.log" "mobile_sync.pid" "mobile_sync.log" | Out-Null

if ($LASTEXITCODE -gt 7) {
    throw "robocopy failed with exit code $LASTEXITCODE"
}

Remove-Item -Path (Join-Path $TargetDir "mobile_sync.pid") -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $TargetDir "mobile_sync.log") -Force -ErrorAction SilentlyContinue

$DeployInfo = [ordered]@{
    deployed_at_kst = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), "Korea Standard Time").ToString("yyyy-MM-dd HH:mm:ss")
    message = $Message
    streamlit_url = "https://lllight58-portfolio-stream-portfolio-cloud-mobile-appapp-6nltfr.streamlit.app/"
}
$DeployInfoPath = Join-Path $TargetDir "deploy_info.json"
$DeployInfo | ConvertTo-Json | Set-Content -Path $DeployInfoPath -Encoding UTF8

& $Git -C $RepoDir config user.name "Portfolio User"
& $Git -C $RepoDir config user.email "portfolio-user@example.com"

& $Git -C $RepoDir add portfolio_cloud_mobile_app

$Changes = & $Git -C $RepoDir diff --cached --name-only
if (-not $Changes) {
    Write-Host "No deploy changes."
    exit 0
}

& $Git -C $RepoDir commit -m $Message
& $Git -C $RepoDir push origin master

Write-Host "Pushed to GitHub. Streamlit Cloud will redeploy automatically."
Write-Host "Mobile app URL: https://lllight58-portfolio-stream-portfolio-cloud-mobile-appapp-6nltfr.streamlit.app/"
