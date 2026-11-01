@echo off
setlocal
cd /d "%~dp0"
if not exist ".inquisitio_runtime\Scripts\python.exe" python -m venv .inquisitio_runtime
call ".inquisitio_runtime\Scripts\activate.bat" || exit /b 1
python -m pip install -r requirements.txt || exit /b 1
python start_inquisitio.py
