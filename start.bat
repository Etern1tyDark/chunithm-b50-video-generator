@echo off
setlocal
set "PYTHON=%~dp0runtime\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
"%PYTHON%" "%~dp0b50.py" %*
