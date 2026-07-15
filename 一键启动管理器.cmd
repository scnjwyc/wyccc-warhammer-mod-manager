@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_desktop.ps1"
set "WMM_EXIT_CODE=%ERRORLEVEL%"
if not "%WMM_EXIT_CODE%"=="0" (
    echo.
    echo Wyccc's Mod Manager failed to start. See the error above.
    pause
)
exit /b %WMM_EXIT_CODE%
