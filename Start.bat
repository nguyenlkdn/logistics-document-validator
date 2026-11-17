@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\streamlit.exe" (
  call Setup.bat auto
  if errorlevel 1 ( pause & exit /b 1 )
)
echo ============================================================
echo  LDV is running at http://localhost:8501
echo  Dang chay tai http://localhost:8501
echo  Keep this window open while using the app. Close it to stop.
echo  Giu cua so nay mo khi su dung. Dong cua so de tat chuong trinh.
echo ============================================================
".venv\Scripts\python.exe" -m streamlit run app.py
pause
