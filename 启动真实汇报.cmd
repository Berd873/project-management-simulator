@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" scripts\serve_course_demo.py
if errorlevel 1 pause
