@echo off
rem ============================================================================
rem  PSDAT_MakeApp.bat  --  build the FULLY PORTABLE PSDAT Windows package.
rem  Builds the CURRENT full edition (browser GUI: diagram, studies, SCADA
rem  operator mode, state estimation, night theme, .psdat projects) into a
rem  single PSDAT.exe. Source code is sealed inside the exe as bytecode --
rem  no .py files are visible in the distributed package.
rem
rem  Run this ONCE on a Windows PC that has Python with numpy/scipy/matplotlib
rem  (your Miniconda works) and internet (only to fetch the PyInstaller
rem  packager the first time).  It produces, next to this file:
rem
rem      PSDAT_Portable\            the self-contained package (a folder)
rem        PSDAT.exe                the application  (double-click to run)
rem        docs\                     manual, problem set, solutions, model map
rem        README.txt                how to run
rem      PSDAT_Portable.zip         the same package, zipped for distribution
rem
rem  The .exe carries its own Python, numpy, scipy and matplotlib INSIDE it, so
rem  the package runs on ANY supported Windows computer with NOTHING installed
rem  (no Python, no MATLAB, no internet, no admin rights).  A user just
rem  extracts the zip anywhere and double-clicks PSDAT.exe -- the full
rem  Interactive Lab (single-line-diagram editor, power flow, dynamic
rem  simulation, small-signal analysis, reports, export, print) opens in its
rem  own window and runs completely offline.  Upload PSDAT_Portable.zip to a
rem  permanent host (Zenodo / GitHub Releases / institutional repo / Drive) and
rem  put that link in the paper's Software Availability section.
rem
rem  Notes: the .exe is ~150-250 MB (it bundles the scientific stack) and takes
rem  a few seconds to start the first time.  Windows SmartScreen may ask once to
rem  confirm running an unsigned app  ("More info" -> "Run anyway").
rem ============================================================================
setlocal enabledelayedexpansion
rem  Ignore the shared per-user site-packages (AppData\Roaming\Python):
rem  leftover/broken packages there poison the build analysis.
set "PYTHONNOUSERSITE=1"
set "HERE=%~dp0"
set "PY="

rem --- find a Python with numpy + scipy + matplotlib ---------------------------
py -c "import numpy,scipy,matplotlib" >nul 2>&1
if not errorlevel 1 set "PY=py"
if not defined PY (
  python -c "import numpy,scipy,matplotlib" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
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
      "%%~P" -c "import numpy,scipy,matplotlib" >nul 2>&1
      if not errorlevel 1 set "PY=%%~P"
    )
  )
)
if not defined PY (
  for /d %%E in ("%USERPROFILE%\miniconda3\envs\*" "%USERPROFILE%\anaconda3\envs\*") do (
    if not defined PY (
      "%%E\python.exe" -c "import numpy,scipy,matplotlib" >nul 2>&1
      if not errorlevel 1 set "PY=%%E\python.exe"
    )
  )
)
if not defined PY (
  echo Could not find a Python with numpy + scipy + matplotlib on this computer.
  echo Open your Anaconda/Miniconda Prompt and run this file from there,
  echo or first run:  pip install numpy scipy matplotlib
  pause
  exit /b 1
)
echo Using Python: %PY%

echo.
echo [1/4] installing the PyInstaller packager (one-time download) ...
"%PY%" -m pip install --quiet --upgrade pyinstaller
if errorlevel 1 ( echo pip install pyinstaller failed - check your internet. & pause & exit /b 1 )

echo.
echo [2/4] building PSDAT.exe (this bundles Python+numpy+scipy+matplotlib; 3-8 min) ...
cd /d "%HERE%"
set "ICON="
if exist "PSDAT.ico" set "ICON=--icon PSDAT.ico"
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --name PSDAT %ICON% ^
  --add-data "case68_16m.m;." ^
  --hidden-import psdat_gui ^
  --hidden-import scipy.integrate ^
  --hidden-import scipy.integrate._ivp ^
  --collect-submodules scipy.optimize ^
  --hidden-import studies ^
  --hidden-import figstyle ^
  --hidden-import cases --hidden-import system --hidden-import units ^
  --hidden-import network --hidden-import linearize --hidden-import design ^
  --hidden-import simulate --hidden-import facts ^
  --hidden-import matplotlib.backends.backend_agg ^
  --exclude-module PySide2 --exclude-module PyQt5 ^
  --exclude-module PySide6 --exclude-module PyQt6 --exclude-module tkinter ^
  --exclude-module pytest --exclude-module _pytest --exclude-module IPython ^
  psdat_launch.py
if errorlevel 1 ( echo Build failed - scroll up for the error. & pause & exit /b 1 )
rem  If the build is too large or scipy causes trouble, delete the two
rem  "--hidden-import scipy..." lines above: the alternative ODE solvers then
rem  fall back to the built-in RK4 and everything else is unchanged.

rem  --- put the finished SINGLE-FILE app where the user will actually see it,
rem      right next to the two .bat launchers at the top of the package --------
copy /y "dist\PSDAT.exe" "%HERE%..\PSDAT.exe" >nul 2>&1

echo.
echo [3/4] assembling the portable package (app + docs + examples + README) ...
set "PKG=%HERE%PSDAT_Portable"
if exist "%PKG%" rmdir /s /q "%PKG%"
mkdir "%PKG%"
copy /y "dist\PSDAT.exe" "%PKG%\PSDAT.exe" >nul
mkdir "%PKG%\docs" 2>nul
if exist "%HERE%..\docs" (
  copy /y "%HERE%..\docs\*.pdf"  "%PKG%\docs\" >nul 2>&1
  copy /y "%HERE%..\docs\*.docx" "%PKG%\docs\" >nul 2>&1
  copy /y "%HERE%..\docs\*.md"   "%PKG%\docs\" >nul 2>&1
)
if exist "%HERE%..\README.md" copy /y "%HERE%..\README.md" "%PKG%\docs\README.md" >nul 2>&1
rem  bundled example networks are inside the .exe (IEEE 9-bus, Kundur two-area,
rem  68-bus NETS-NYPS); the raw case files are copied for reference:
mkdir "%PKG%\examples" 2>nul
copy /y "%HERE%case68_16m.m" "%PKG%\examples\" >nul 2>&1
copy /y "%HERE%IEEE9Bus.m"   "%PKG%\examples\" >nul 2>&1
copy /y "%HERE%..\matlab\Kundur2A.m" "%PKG%\examples\" >nul 2>&1

> "%PKG%\README.txt" echo PSDAT - Power System Dynamic Analysis Toolbox (portable)
>>"%PKG%\README.txt" echo ============================================================
>>"%PKG%\README.txt" echo.
>>"%PKG%\README.txt" echo HOW TO RUN
>>"%PKG%\README.txt" echo   1. Extract this folder anywhere (Desktop, USB drive, ...).
>>"%PKG%\README.txt" echo   2. Double-click  PSDAT.exe .
>>"%PKG%\README.txt" echo   The application opens in its own window and runs fully
>>"%PKG%\README.txt" echo   offline. No installation, no Python or MATLAB, no admin.
>>"%PKG%\README.txt" echo.
>>"%PKG%\README.txt" echo WHAT IS INCLUDED
>>"%PKG%\README.txt" echo   - Single-line-diagram editor, power flow (NR/FDLF/GS),
>>"%PKG%\README.txt" echo     dynamic simulation, small-signal + control-design tools.
>>"%PKG%\README.txt" echo   - Example networks: IEEE 9-bus, Kundur two-area, 68-bus.
>>"%PKG%\README.txt" echo   - docs\      manual, problem set, solutions, model sources.
>>"%PKG%\README.txt" echo   - examples\  raw case files for reference.
>>"%PKG%\README.txt" echo.
>>"%PKG%\README.txt" echo NOTES
>>"%PKG%\README.txt" echo   - First launch takes a few seconds while the app unpacks.
>>"%PKG%\README.txt" echo   - Windows SmartScreen may ask once: More info -> Run anyway.
>>"%PKG%\README.txt" echo   - Reports/exports are written next to the app on your PC.
>>"%PKG%\README.txt" echo.
>>"%PKG%\README.txt" echo (c) Dr. Ismael Khorshed Abdulrahman - PSDAT, building on
>>"%PKG%\README.txt" echo     the original [IEEE Open Access Journal of Power and Energy, 2020].

echo.
echo [4/4] zipping PSDAT_Portable.zip for distribution ...
powershell -NoProfile -Command "Compress-Archive -Path '%PKG%\*' -DestinationPath '%HERE%PSDAT_Portable.zip' -Force"

echo.
echo ================================================================
echo   Done!
echo.
echo   YOUR SINGLE-FILE APP (this is the whole program, one file):
echo       %HERE%..\PSDAT.exe
echo   Double-click it. Copy it anywhere. It runs on any Windows PC
echo   with nothing installed. This is the "just one .exe" file.
echo.
echo   Optional, if you also want the docs bundled next to it:
echo       folder : %PKG%
echo       archive: %HERE%PSDAT_Portable.zip   (good for uploading)
echo ================================================================
pause
