@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Everything is inside one block: cmd reads the whole block before running it,
rem so an update may safely replace this file while it runs.
(
  if not exist ".venv\Scripts\streamlit.exe" (
    call Setup.bat auto
    if errorlevel 1 ( pause & exit /b 1 )
  )
  ".venv\Scripts\python.exe" updater.py
  if errorlevel 10 (
    echo Updating libraries / Dang cap nhat thu vien...
    call Setup.bat auto
    if errorlevel 1 ( pause & exit /b 1 )
  )
  echo ============================================================
  echo  LDV is running at http://localhost:8501
  echo  Dang chay tai http://localhost:8501
  echo  Keep this window open while using the app. Close it to stop.
  echo  Giu cua so nay mo khi su dung. Dong cua so de tat chuong trinh.
  echo ============================================================
  rem "nobrowser": started by right-click Send to, which opens the browser itself
  if /i "%~1"=="nobrowser" (
    ".venv\Scripts\python.exe" -m streamlit run app.py --server.headless true
  ) else (
    ".venv\Scripts\python.exe" -m streamlit run app.py
  )
  pause
  exit /b 0
)
