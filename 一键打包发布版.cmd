@echo off
setlocal
cd /d "%~dp0" || exit /b 1
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\package_release.ps1" %*
set "WMM_EXIT_CODE=%ERRORLEVEL%"
echo.
if "%WMM_EXIT_CODE%"=="0" (
    echo Wyccc's Mod Manager build command completed. See the result above.
) else (
    echo Wyccc's Mod Manager release build failed. See the error above.
)
if defined WMM_NO_PAUSE exit /b %WMM_EXIT_CODE%
pause
exit /b %WMM_EXIT_CODE%
