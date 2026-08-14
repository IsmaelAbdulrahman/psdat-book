@echo off
setlocal
set "DEST=%LOCALAPPDATA%\PSDAT"
echo.
echo  Installing PSDAT to "%DEST%" ...
robocopy "%~dp0PSDAT" "%DEST%" /E /NFL /NDL /NJH /NJS /NP >nul 2>&1
if %ERRORLEVEL% GEQ 8 (
  echo  PSDAT could not be copied to "%DEST%".
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0shortcuts.ps1" -Dest "%DEST%" >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\PSDAT" /f /v DisplayName /t REG_SZ /d "PSDAT 2.1 - Power System Dynamic Analysis Toolbox" >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\PSDAT" /f /v DisplayVersion /t REG_SZ /d "2.1" >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\PSDAT" /f /v Publisher /t REG_SZ /d "Dr. Ismael Khorshed Abdulrahman, Erbil Polytechnic University" >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\PSDAT" /f /v InstallLocation /t REG_SZ /d "%DEST%" >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\PSDAT" /f /v DisplayIcon /t REG_SZ /d "%DEST%\PSDAT.ico" >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\PSDAT" /f /v UninstallString /t REG_SZ /d "\"%DEST%\uninstall.cmd\"" >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\PSDAT" /f /v EstimatedSize /t REG_DWORD /d 430000 >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\PSDAT" /f /v NoModify /t REG_DWORD /d 1 >nul
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\PSDAT" /f /v NoRepair /t REG_DWORD /d 1 >nul
echo  Done. Starting PSDAT ...
start "" "%DEST%\PSDAT.exe"
exit /b 0
