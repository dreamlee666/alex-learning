@echo off
"%~dp0runtime\python\python.exe" -X utf8 "%~dp0launcher\bootstrap.py" --start
if errorlevel 1 (pause & exit /b 1)
start "" "%~dp0Alex-Game-Companion.exe" --open
