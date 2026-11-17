@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Import the HS master Excel (drag the .xlsx file onto this file), or show the current status.
rem Nhap file Excel ma HS (keo file .xlsx tha vao file nay), hoac xem trang thai.
if "%~1"=="" (
  ".venv\Scripts\python.exe" -m engine.master
) else (
  ".venv\Scripts\python.exe" -m engine.master "%~1"
)
pause
