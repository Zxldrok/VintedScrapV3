@echo off
cd /d "%~dp0"
python main.py || py main.py
if errorlevel 1 pause
