@echo off
setlocal
cd /d "%~dp0"
where node >nul 2>nul || goto :missing
set "npm_config_cache=%LOCALAPPDATA%\npm-cache"
node server\launch.mjs
if errorlevel 1 pause
exit /b
:missing
echo Agent Team Board requires Node.js 22.12 or later.
pause
exit /b 1

