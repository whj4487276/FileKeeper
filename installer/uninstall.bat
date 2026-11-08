@echo off
chcp 65001 >nul
setlocal
set "DEST=%~dp0"
if "%DEST:~-1%"=="\" set "DEST=%DEST:~0,-1%"

echo.
echo   ============================================
echo      电脑百宝箱 卸载程序
echo   ============================================
echo.
echo   安装目录：%DEST%
echo.

echo   正在结束运行中的电脑百宝箱...
taskkill /IM "电脑百宝箱.exe" /F >nul 2>nul
taskkill /IM FileKeeper.exe /F >nul 2>nul

echo   正在删除快捷方式...
if exist "%USERPROFILE%\Desktop\电脑百宝箱.lnk" del /f /q "%USERPROFILE%\Desktop\电脑百宝箱.lnk" >nul 2>nul
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\电脑百宝箱.lnk" del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\电脑百宝箱.lnk" >nul 2>nul
if exist "%USERPROFILE%\Desktop\文件管家.lnk" del /f /q "%USERPROFILE%\Desktop\文件管家.lnk" >nul 2>nul
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\文件管家.lnk" del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\文件管家.lnk" >nul 2>nul

echo   正在清理注册表...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\FileKeeper" /f >nul 2>nul
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "FileKeeper" /f >nul 2>nul

echo.
choice /c YN /n /m "  是否同时删除配置和备份日志（data 文件夹）？[Y=删除 data / N=保留 data] "
if errorlevel 2 goto :keepdata

:removedata
echo.
echo   正在删除程序文件和 data 文件夹...
if exist "%DEST%\电脑百宝箱.exe" del /f /q "%DEST%\电脑百宝箱.exe" >nul 2>nul
if exist "%DEST%\install_log.txt" del /f /q "%DEST%\install_log.txt" >nul 2>nul
if exist "%DEST%\data" rmdir /s /q "%DEST%\data" >nul 2>nul
goto :cleanup

:keepdata
echo.
echo   正在删除程序文件，保留 data 文件夹...
if exist "%DEST%\电脑百宝箱.exe" del /f /q "%DEST%\电脑百宝箱.exe" >nul 2>nul
if exist "%DEST%\install_log.txt" del /f /q "%DEST%\install_log.txt" >nul 2>nul

:cleanup
rem 只删除本程序自己的文件；如果目录里还有用户文件，rmdir 会失败并保留目录。
set "CLEAN=%TEMP%\fk_uninstall_cleanup.cmd"
> "%CLEAN%" echo @echo off
>> "%CLEAN%" echo timeout /t 2 ^>nul
>> "%CLEAN%" echo if exist "%DEST%\uninstall.bat" del /f /q "%DEST%\uninstall.bat"
>> "%CLEAN%" echo if exist "%DEST%" rmdir "%DEST%" 2^>nul
>> "%CLEAN%" echo del /f /q "%%~f0"
start "" /min "%CLEAN%"
echo.
echo   卸载完成。若安装目录中还有你自己放的文件，目录会保留。
timeout /t 3 >nul
exit /b 0