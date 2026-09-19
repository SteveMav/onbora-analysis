@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0lancer.ps1"
if errorlevel 1 pause
