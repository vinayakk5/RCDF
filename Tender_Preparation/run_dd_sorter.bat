@echo off
title RCDF DD Smart Sorter
cd /d "%~dp0"
echo =====================================================================
echo  Starting RCDF DD Smart Sorter (Vision LLM + MICR)
echo =====================================================================
if "%~1"=="" (
    .\.venv\Scripts\python.exe -u dd_sorter.py
) else if "%~2"=="" (
    .\.venv\Scripts\python.exe -u dd_sorter.py --dd-zip "%~1"
) else (
    .\.venv\Scripts\python.exe -u dd_sorter.py --dd-zip "%~1" --dd-map "%~2"
)
pause
