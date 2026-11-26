@echo off
setlocal
python -B -X utf8 "%~dp0serve.py" %*
if errorlevel 1 pause
