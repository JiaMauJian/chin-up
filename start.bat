@echo off
rem 在背景啟動 chin-up（不開命令列視窗）
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" chin_up.py
