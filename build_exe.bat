@echo off
REM ===== Penguix - Windows EXE build script =====
REM Run this from the project folder, inside your activated venv.

echo.
echo Building Penguix.exe ...
echo.

REM 1. make sure build tools + app deps are installed
pip install --upgrade pyinstaller >nul 2>&1
pip install -r requirements.txt >nul 2>&1

REM 2. clean previous build and build from the spec
pyinstaller --noconfirm --clean penguix.spec

if exist "dist\Penguix.exe" (
    echo.
    echo ============================================
    echo  SUCCESS:  dist\Penguix.exe
    echo  Double-click it, or copy it to any Windows PC.
    echo ============================================
) else (
    echo.
    echo  Build did not produce dist\Penguix.exe - scroll up for the error.
)
pause
