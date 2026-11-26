@echo off
cd /d "%~dp0"
set "SHOPSPHERE_WEB_PORT=8765"
set "SHOPSPHERE_OPEN_BROWSER=1"
echo Opening AllCart. Keep this window open while using the site.
".venv\Scripts\python.exe" "..\work\start_shopsphere.py"
if errorlevel 1 pause
