@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0arreter.ps1"
if errorlevel 1 pause
