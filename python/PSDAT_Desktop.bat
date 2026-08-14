@echo off
rem PSDAT Desktop launcher - finds a working Python (incl. Miniconda/Anaconda,
rem which are not on the global PATH) and opens the lab as an app window.
setlocal
set "HERE=%~dp0"
set "PY="

rem --- 1) the Windows py launcher ---
py -c "import numpy,matplotlib" >nul 2>&1
if not errorlevel 1 set "PY=py"

rem --- 2) python on PATH (skips the Microsoft Store stub automatically,
rem        because the stub fails the import test) ---
if not defined PY (
  python -c "import numpy,matplotlib" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)

rem --- 3) conda/base installations in the usual places ---
if not defined PY (
  for %%P in ("%USERPROFILE%\miniconda3\python.exe"
              "%USERPROFILE%\anaconda3\python.exe"
              "%LOCALAPPDATA%\miniconda3\python.exe"
              "%LOCALAPPDATA%\anaconda3\python.exe"
              "C:\miniconda3\python.exe"
              "C:\anaconda3\python.exe"
              "C:\ProgramData\miniconda3\python.exe"
              "C:\ProgramData\anaconda3\python.exe") do (
    if not defined PY (
      "%%~P" -c "import numpy,matplotlib" >nul 2>&1
      if not errorlevel 1 set "PY=%%~P"
    )
  )
)

rem --- 4) every conda environment (e.g. qml1) ---
if not defined PY (
  for /d %%E in ("%USERPROFILE%\miniconda3\envs\*") do (
    if not defined PY (
      "%%E\python.exe" -c "import numpy,matplotlib" >nul 2>&1
      if not errorlevel 1 set "PY=%%E\python.exe"
    )
  )
)
if not defined PY (
  for /d %%E in ("%USERPROFILE%\anaconda3\envs\*") do (
    if not defined PY (
      "%%E\python.exe" -c "import numpy,matplotlib" >nul 2>&1
      if not errorlevel 1 set "PY=%%E\python.exe"
    )
  )
)

if not defined PY (
  echo.
  echo   Could not find a Python with numpy + matplotlib on this computer.
  echo   Open your Anaconda/Miniconda Prompt and run:
  echo       python "%HERE%PSDAT_Desktop.py"
  echo.
  pause
  exit /b 1
)

rem --- prefer the window-less pythonw.exe: the app opens with NO console ---
set "PYW=%PY:python.exe=pythonw.exe%"
if /i "%PY%"=="py" set "PYW="
if /i "%PY%"=="python" set "PYW="
if defined PYW if /i "%PYW%"=="%PY%" set "PYW="
if defined PYW if not exist "%PYW%" set "PYW="
if defined PYW (
  start "" "%PYW%" "%HERE%PSDAT_Desktop.py"
  exit /b 0
)
echo Using Python: %PY%
"%PY%" "%HERE%PSDAT_Desktop.py"
if errorlevel 1 pause
