@echo off
setlocal
cd /d "%~dp0"

set "APP=%~dp0main.py"

rem 1) project-local virtualenv
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%APP%"
    exit /b
)

rem 2) pythonw from PATH (no console window)
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%APP%"
    exit /b
)

rem 3) python from PATH (ignore the Microsoft Store placeholder)
python -c "import sys" >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%APP%" >nul 2>nul
    if errorlevel 1 start "" python "%APP%"
    exit /b
)

rem 4) built-in runtime that ships with this machine
set "FALLBACK=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"
if exist "%FALLBACK%" (
    start "" "%FALLBACK%" "%APP%"
    exit /b
)

rem 5) nothing found
echo.
echo   [ERROR] No usable Python 3.10+ was found on this computer.
echo.
echo   How to fix (pick one):
echo     1. Install Python 3.12 from https://www.python.org/downloads/
echo        During setup, tick "Add python.exe to PATH".
echo     2. Copy this folder to a PC that already has Python installed.
echo     3. Run build_exe.bat to build a standalone FileKeeper.exe.
echo.
pause
exit /b 1
