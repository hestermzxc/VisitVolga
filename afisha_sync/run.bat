@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip show openpyxl >nul 2>&1 || python -m pip install openpyxl
python afisha_sync.py config.xml
pause
