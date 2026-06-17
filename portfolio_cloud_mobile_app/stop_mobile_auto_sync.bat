@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path '%~dp0mobile_sync.pid') { $p = Get-Content '%~dp0mobile_sync.pid' -ErrorAction SilentlyContinue; if ($p) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }; Remove-Item '%~dp0mobile_sync.pid' -Force -ErrorAction SilentlyContinue; Write-Host 'Mobile auto-sync watcher stopped.' } else { Write-Host 'Mobile auto-sync watcher is not running.' }"
