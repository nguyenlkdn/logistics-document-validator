@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo  LDV - Logistics Document Validator - Setup  /  Cai dat (no admin needed)
echo ============================================================

rem Python: the one Setup installed before, else the py launcher, else python on PATH. None, too old, or only the
rem Microsoft Store stub: install Python 3.15 for this user (install_python.ps1: winget, else python.org; no admin).
set "PY315=%LOCALAPPDATA%\Programs\Python\Python315\python.exe"
set "PY="
if exist "%PY315%" set PY="%PY315%"
if not defined PY ( where py >nul 2>nul && (py -3.15 -c "" >nul 2>nul && set "PY=py -3.15" || set "PY=py -3") )
if not defined PY ( where python >nul 2>nul && set "PY=python" )
set "PYOK="
if defined PY ( %PY% -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul && set "PYOK=1" )
if not defined PYOK (
  echo Python 3.11+ not found - installing Python 3.15 for this user / Chua co Python - dang cai Python 3.15...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_python.ps1"
  if exist "%PY315%" ( set PY="%PY315%" & set "PYOK=1" )
)
if not defined PYOK (
  echo [ERROR] Python could not be installed. Install Python 3.15 from python.org, then run Setup.bat again.
  echo [LOI] Khong cai duoc Python. Hay cai Python 3.15 tu python.org roi chay lai Setup.bat.
  if not "%~1"=="auto" pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating local environment / Dang tao moi truong...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Could not create environment / Khong tao duoc moi truong.
    if not "%~1"=="auto" pause
    exit /b 1
  )
)

rem Remove pymupdf 2.x extras left from older installs (not compatible with Python 3.15)
".venv\Scripts\python.exe" -m pip uninstall -y -q pymupdf-layout pymupdf4llm onnxruntime >nul 2>nul

echo Installing libraries / Dang cai thu vien (first time takes a few minutes)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  if exist "wheels\" (
    echo Online install failed, using offline package folder / Dung goi cai dat offline...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --no-index --find-links wheels -r requirements.txt
  )
)
if errorlevel 1 (
  echo [ERROR] Library install failed. Check internet/proxy, or ask for the offline "wheels" folder.
  echo [LOI] Cai thu vien that bai. Kiem tra mang/proxy, hoac xin thu muc "wheels" de cai offline.
  if not "%~1"=="auto" pause
  exit /b 1
)

rem pymupdf needs the Microsoft C++ runtime (MSVCP140.dll), which Python does not include.
rem Install it into .venv (no admin needed); engine\_dllpath.py makes it findable.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q msvc-runtime >nul 2>nul
if errorlevel 1 if exist "wheels\" ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --no-index --find-links wheels msvc-runtime >nul 2>nul

echo Checking the PDF library / Dang kiem tra thu vien PDF...
".venv\Scripts\python.exe" -c "import engine"
if errorlevel 1 (
  echo [ERROR] PDF library cannot start - Microsoft C++ runtime missing.
  echo         Copy MSVCP140.dll, MSVCP140_1.dll, VCRUNTIME140.dll, VCRUNTIME140_1.dll into the "dll" folder here.
  echo [LOI] Thu vien PDF khong chay - thieu thu vien C++ cua Microsoft.
  echo       Chep MSVCP140.dll, MSVCP140_1.dll, VCRUNTIME140.dll, VCRUNTIME140_1.dll vao thu muc "dll" tai day.
  if not "%~1"=="auto" pause
  exit /b 1
)

rem Shortcuts (no admin): Desktop "LDV" and right-click "Send to > LDV Checker", both run without a console window
".venv\Scripts\python.exe" -c "import ldv_tray; ldv_tray.ensure_ico()" >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$w=New-Object -ComObject WScript.Shell; foreach($l in @(@([Environment]::GetFolderPath('SendTo')+'\LDV Checker.lnk','ldv_open.py','Check shipment documents with LDV'), @([Environment]::GetFolderPath('Desktop')+'\LDV.lnk','ldv_tray.py','LDV - Logistics Document Validator'))){ $s=$w.CreateShortcut($l[0]); $s.TargetPath='%CD%\.venv\Scripts\pythonw.exe'; $s.Arguments='\"%CD%\'+$l[1]+'\"'; $s.WorkingDirectory='%CD%'; $s.IconLocation='%CD%\ldv.ico'; $s.Description=$l[2]; $s.Save() }" >nul 2>nul
if errorlevel 1 (
  echo [NOTE] Could not create the shortcuts. Use Start.bat instead.
  echo [LUU Y] Khong tao duoc loi tat. Hay dung Start.bat.
) else (
  echo Desktop shortcut "LDV" added / Da tao loi tat "LDV" tren Desktop
  echo Right-click menu added: Send to ^> LDV Checker / Da them menu chuot phai: Send to ^> LDV Checker
)

rem Skip Streamlit's first-run email question
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  mkdir "%USERPROFILE%\.streamlit" 2>nul
  > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
  >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

echo.
echo Setup complete / Cai dat xong. Double-click "LDV" on the Desktop (or Start.bat) / Bam dup "LDV" tren Desktop (hoac Start.bat).
if not "%~1"=="auto" pause
exit /b 0
