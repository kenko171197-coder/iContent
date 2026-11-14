@echo off
rem Mo Studio566 nhu mot phan mem rieng. Muon xem nhat ky tren dong lenh: icontent.cmd ui
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m icontent ui --app %*
) else (
  ".venv\Scripts\python.exe" -m icontent ui %*
  if errorlevel 1 pause
)
