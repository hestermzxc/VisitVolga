@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -c "import openpyxl, bs4" >nul 2>&1 || python -m pip install openpyxl beautifulsoup4
python afisha_sync.py config.xml
pause
