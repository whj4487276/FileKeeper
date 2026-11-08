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
if not exist "dist_folder\电脑百宝箱\电脑百宝箱.exe" (
    echo.
    echo   [ERROR] Folder build not found.
    echo   Run build_folder_exe.bat first.
    echo.
    pause
    exit /b 1
)

echo Using Python: %PY%
echo.
echo Building folder installer (dist\电脑百宝箱安装包_目录版.exe)...
"%PY%" -m PyInstaller ^
    --noconfirm --clean --onefile --windowed ^
    --name 电脑百宝箱安装包_目录版 ^
    --icon assets\app.ico ^
    --version-file installer\setup_version.txt ^
    --add-data "dist_folder\电脑百宝箱;payload\app" ^
    --add-data "installer\uninstall.bat;payload" ^
    --add-data "assets\app.ico;assets" ^
    --add-data "assets\icons\logo_96.png;assets" ^
    installer\setup_app.py
if errorlevel 1 goto :fail

echo.
echo Done: %~dp0dist\电脑百宝箱安装包_目录版.exe
pause
exit /b 0

:fail
echo.
echo Build failed.
pause
exit /b 1
