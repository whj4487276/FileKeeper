@echo off
setlocal
cd /d "%~dp0"

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if defined PY goto :found

python -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto :found

set "CAND=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if exist "%CAND%" set "PY=%CAND%"
if defined PY goto :found

echo.
echo   [ERROR] No usable Python 3.10+ was found on this computer.
echo   Install Python from https://www.python.org/downloads/
echo   and tick "Add python.exe to PATH" during setup.
echo.
pause
exit /b 1

:found
echo Using Python: %PY%
echo.
echo [1/3] Installing PyInstaller...
"%PY%" -m pip install --upgrade pyinstaller
if errorlevel 1 goto :fail

echo [2/3] Regenerating icons...
"%PY%" tools\make_icons.py

echo [3/3] Building single-file exe (first run may take 1-3 minutes)...
"%PY%" -m PyInstaller ^
    --noconfirm --clean --windowed --onefile ^
    --name 电脑百宝箱 ^
    --icon assets\app.ico ^
    --version-file installer\app_version.txt ^
    --add-data "assets;assets" ^
    main.py
if errorlevel 1 goto :fail

echo.
echo Done: %~dp0dist\电脑百宝箱.exe
echo To build the installer, run build_installer.bat next.
echo.
pause
exit /b 0

:fail
echo.
echo Build failed. Please check the messages above.
pause
exit /b 1