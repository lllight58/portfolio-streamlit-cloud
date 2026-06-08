@echo off
setlocal
cd /d "%~dp0"

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

streamlit run app.py --server.port 8502 --server.address 0.0.0.0
