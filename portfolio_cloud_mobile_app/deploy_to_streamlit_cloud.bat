@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy_to_streamlit_cloud.ps1" -Message "%~1"
