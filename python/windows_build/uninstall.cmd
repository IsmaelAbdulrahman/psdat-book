@echo off
setlocal
set "DEST=%LOCALAPPDATA%\PSDAT"
echo.
echo  This removes PSDAT from this computer (your exported results are kept).
choice /C YN /M " Continue"
if errorlevel 2 exit /b 0
powershell -NoProfile -Command "Get-Process pythonw,python -ErrorAction SilentlyContinue | Where-Object {$_.Path -like \"$env:LOCALAPPDATA\PSDAT*\"} | Stop-Process -Force" >nul 2>&1
powershell -NoProfile -Command "Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('Desktop')) 'PSDAT.lnk') -ErrorAction SilentlyContinue" >nul 2>&1
rd /s /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\PSDAT" >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\PSDAT" /f >nul 2>&1
start "" cmd /c "ping -n 3 127.0.0.1 >nul & rd /s /q "%DEST%""
exit /b 0
