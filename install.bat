@echo off
setlocal enabledelayedexpansion

echo.
echo  ====================================================
echo   LucyLive AI  --  Dependency Installer for 3ds Max
echo  ====================================================
echo.

rem ── Find Max Python (newest first) ──────────────────────────────────────
set "MAX_PYTHON="
set "MAX_VERSION="

for %%V in (2025 2026 2027) do (
    if "!MAX_PYTHON!"=="" (
        if exist "C:\Program Files\Autodesk\3ds Max %%V\Python\python.exe" (
            set "MAX_PYTHON=C:\Program Files\Autodesk\3ds Max %%V\Python\python.exe"
            set "MAX_VERSION=%%V"
        )
    )
)

if "!MAX_PYTHON!"=="" (
    echo  [ERROR] No 3ds Max Python found.
    echo  Checked: 2025 / 2026 / 2027
    echo  Make sure 3ds Max is installed in the default location.
    echo.
    pause
    exit /b 1
)

echo  Found: 3ds Max !MAX_VERSION!
echo  Python: !MAX_PYTHON!
echo.
"!MAX_PYTHON!" --version
echo.

rem ── Create venv in project folder ───────────────────────────────────────
set "SCRIPT_DIR=%~dp0"
set "VENV=%SCRIPT_DIR%venv310"

echo  Creating virtual environment ...
"!MAX_PYTHON!" -m venv "!VENV!"
if errorlevel 1 (
    echo  [ERROR] venv creation failed.
    pause
    exit /b 1
)

rem ── Upgrade pip silently ────────────────────────────────────────────────
echo  Upgrading pip ...
"!VENV!\Scripts\python.exe" -m pip install --upgrade pip --quiet

rem ── Install packages ────────────────────────────────────────────────────
echo  Installing decart SDK, livekit, av, Pillow ...
echo.
"!VENV!\Scripts\pip.exe" install ^
    --trusted-host pypi.org ^
    --trusted-host files.pythonhosted.org ^
    decart ^
    livekit ^
    livekit-api ^
    av==16.1.0 ^
    Pillow==12.3.0

if errorlevel 1 (
    echo.
    echo  [ERROR] Package installation failed.
    echo  Check your internet connection and try again.
    pause
    exit /b 1
)

rem ── Write ready marker ──────────────────────────────────────────────────
echo !MAX_VERSION! > "!VENV!\.lucy_live_ready"

echo.
echo  ====================================================
echo   Done!  venv ready at:
echo   !VENV!
echo.
echo   Next step: open 3ds Max ^> Scripting ^> Run Script
echo   and select lucylive_panel.ms
echo  ====================================================
echo.
pause
