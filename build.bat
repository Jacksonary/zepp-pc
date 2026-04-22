@echo off
REM Build script for Zepp PC Manager on Windows
REM Requires: Python 3.10+, pip, and the project dependencies

echo ========================================
echo  Zepp PC Manager - Windows Build
echo ========================================
echo.

REM Check if venv exists
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate
) else (
    call .venv\Scripts\activate
)

echo.
echo Installing uv...
pip install --quiet uv

echo.
echo Installing project dependencies...
uv pip install -e ".[dev]" pyinstaller

echo.
echo Running tests...
pytest tests/ -v
if errorlevel 1 (
    echo Tests failed! Aborting build.
    exit /b 1
)

echo.
echo Building executable...
pyinstaller build.spec --clean

echo.
echo ========================================
echo  Build complete!
echo  Output: dist\zepp-pc.exe
echo ========================================
pause
