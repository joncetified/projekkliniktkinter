@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.tools\python\python.exe" (
  "%~dp0.tools\python\python.exe" "%~dp0desktop_app\main.py" %*
) else (
  python "%~dp0desktop_app\main.py" %*
)
if errorlevel 1 pause
endlocal
