@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0sniper.ps1" %*
exit /b %ERRORLEVEL%
