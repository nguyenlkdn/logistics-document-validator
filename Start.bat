@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Starts LDV in the background with an icon next to the clock (right-click it: Open / Reports / Quit).
rem Everything is inside one block: cmd reads the whole block first, so an update may replace this file.
(
  if not exist ".venv\Scripts\pythonw.exe" (
    call Setup.bat auto
    if errorlevel 1 ( pause & exit /b 1 )
  )
  ".venv\Scripts\python.exe" -c "import pystray" >nul 2>nul || (
    call Setup.bat auto
    if errorlevel 1 ( pause & exit /b 1 )
  )
  start "" ".venv\Scripts\pythonw.exe" ldv_tray.py %*
  exit /b 0
)
