@echo off
REM ===== Penguix - Windows EXE build script =====
REM Run this from the PROJECT ROOT, inside your activated venv:
REM     & .\.venv\Scripts\Activate.ps1
REM     .\build_exe.bat

echo.
echo Building Penguix.exe ...
echo.

REM 0. sanity: is PyInstaller available in THIS Python? (usually the venv)
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: PyInstaller is not available in the active Python.
    echo  Activate your virtual environment first, then re-run:
    echo      ^& .\.venv\Scripts\Activate.ps1
    echo  ^(or install it:  python -m pip install pyinstaller^)
    echo.
    pause
    exit /b 1
)

REM 1. make sure app deps are installed (into the active env)
python -m pip install -r requirements.txt >nul 2>&1

REM 2. remove the previous exe so a stale file can never look like "success"
if exist "dist\Penguix.exe" del /q "dist\Penguix.exe"

REM 3. clean build from the spec
python -m PyInstaller --noconfirm --clean penguix.spec

if not exist "dist\Penguix.exe" (
    echo.
    echo  BUILD FAILED - dist\Penguix.exe was not produced. Scroll up for the error.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  SUCCESS:  dist\Penguix.exe
echo  Double-click it, or copy it to any Windows PC.
echo ============================================
pause
