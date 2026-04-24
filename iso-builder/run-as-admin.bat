@echo off
:: LinuxTV Flash Tool - Administrator Launcher
:: This script requests admin rights and launches the flash tool

echo Checking administrator privileges...

net session >nul 2>&1
if %errorLevel% == 0 (
    echo Running as Administrator. Launching LinuxTV Flash Tool...
    python "%~dp0linuxtv-flash-tool.py"
) else (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process '%~dp0linuxtv-flash-tool.py' -Verb RunAs"
)
