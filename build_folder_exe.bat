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
echo.
pause
exit /b 1

:found
echo Using Python: %PY%
echo.
echo Building folder version (dist_folder\电脑百宝箱\...)
"%PY%" -m PyInstaller ^
    --noconfirm --clean --windowed --onedir ^
    --name 电脑百宝箱 ^
    --distpath dist_folder ^
    --icon assets\app.ico ^
    --version-file installer\app_version.txt ^
    --add-data "assets;assets" ^
    main.py
if errorlevel 1 goto :fail

echo.
echo Done: %~dp0dist_folder\电脑百宝箱\电脑百宝箱.exe
echo Run build_folder_installer.bat to build the folder installer.
pause
exit /b 0

:fail
echo.
echo Build failed.
pause
exit /b 1
