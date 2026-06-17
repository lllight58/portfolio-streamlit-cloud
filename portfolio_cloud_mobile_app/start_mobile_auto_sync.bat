@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath powershell.exe -WindowStyle Hidden -WorkingDirectory '%~dp0' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0sync_mobile_on_change.ps1')"
echo Mobile auto-sync watcher started.
