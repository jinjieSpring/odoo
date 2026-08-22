@echo off
cd /d "%~dp0"
call D:\CodeSoftware\miniconda3\Scripts\activate.bat odoo-19.0
python odoo-bin -c odoo.conf
if errorlevel 1 pause
