@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo  LDV - Logistics Document Validator - Setup  /  Cai dat (no admin needed)
echo ============================================================

set "PY="
where py >nul 2>nul && (py -3.15 -c "" >nul 2>nul && set "PY=py -3.15" || set "PY=py -3")
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo [ERROR] Python not found. Install Python 3.15 from python.org first.
  echo [LOI] Chua co Python. Hay cai Python 3.15 tu python.org truoc.
  if not "%~1"=="auto" pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(sys.version_info < (3, 11))" || (
  echo [ERROR] Python 3.11 or newer is required ^(3.15 recommended^).
  echo [LOI] Can Python 3.11 tro len ^(nen dung 3.15^).
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

rem Right-click menu: Send to > LDV Checker (shortcut in the user's SendTo folder, no admin needed)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('SendTo')+'\LDV Checker.lnk'); $s.TargetPath='%CD%\.venv\Scripts\pythonw.exe'; $s.Arguments='\"%CD%\ldv_open.py\"'; $s.WorkingDirectory='%CD%'; $s.Description='Check shipment documents with LDV'; $s.Save()" >nul 2>nul
if errorlevel 1 (
  echo [NOTE] Could not add the right-click menu "Send to > LDV Checker". Use Start.bat instead.
  echo [LUU Y] Khong tao duoc menu chuot phai "Send to > LDV Checker". Hay dung Start.bat.
) else (
  echo Right-click menu added: select files, right-click, Send to ^> LDV Checker
  echo Da them menu chuot phai: chon file, bam chuot phai, Send to ^> LDV Checker
)

rem Skip Streamlit's first-run email question
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  mkdir "%USERPROFILE%\.streamlit" 2>nul
  > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
  >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

echo.
echo Setup complete / Cai dat xong. Double-click Start.bat to run / Bam dup Start.bat de chay.
if not "%~1"=="auto" pause
exit /b 0
