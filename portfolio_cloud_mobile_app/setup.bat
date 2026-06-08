@echo off
setlocal
cd /d "%~dp0"

if not exist .venv (
    py -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m src.db

echo.
echo setup complete. Run run.bat to start the mobile app.
pause
