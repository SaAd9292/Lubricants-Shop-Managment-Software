@echo off
REM ===== Build the Penguix Windows installer =====
REM Requires: 1) dist\Penguix.exe already built (run build_exe.bat first)
REM           2) Inno Setup installed from https://jrsoftware.org/isdl.php
setlocal
cd /d "%~dp0"

if not exist "..\dist\Penguix.exe" goto nodist

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC goto noiscc

"%ISCC%" "penguix_installer.iss"
if exist "output\Penguix-Setup-0.2.0.exe" goto ok
goto maybefail

:nodist
echo.
echo  ERROR: ..\dist\Penguix.exe was not found.
echo  Build the app first - run build_exe.bat in the project root.
echo.
pause
exit /b 1

:noiscc
echo.
echo  Inno Setup compiler ISCC.exe was not found.
echo  Install Inno Setup from https://jrsoftware.org/isdl.php
echo  OR just double-click penguix_installer.iss and press F9 to compile.
echo.
pause
exit /b 1

:ok
echo.
echo  ============================================
echo   SUCCESS:  installer\output\Penguix-Setup-0.2.0.exe
echo   Give THIS file to a shop to install Penguix.
echo  ============================================
echo.
pause
exit /b 0

:maybefail
echo.
echo  Compile finished but the Setup .exe was not found - scroll up for errors.
echo.
pause
exit /b 1
