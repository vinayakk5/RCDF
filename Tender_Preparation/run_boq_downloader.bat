@echo off
title RCDF eProc BOQ Downloader
cd /d "%~dp0"
echo =====================================================================
echo  Starting RCDF eProc BOQ Downloader
echo =====================================================================
.\.venv\Scripts\python.exe -u eproc_boq_downloader.py %*
pause
