@echo off
echo Starting LinuxTV Flash Tool...
python "%~dp0linuxtv-flash-tool.py"
if errorlevel 1 (
    echo.
    echo Error: Python is required.
    echo Please install Python from https://www.python.org/downloads/
    pause
)
