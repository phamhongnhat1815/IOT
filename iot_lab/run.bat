@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Tao moi truong: python -m venv .venv
  echo Cai thu vien: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run web.py
pause
