@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_python.bat"
if errorlevel 1 goto end
"%YAO_PYTHON%" -X utf8 "collect_results.py" 
if errorlevel 1 echo FAILED - keep this window and copy the error message.
:end
pause
