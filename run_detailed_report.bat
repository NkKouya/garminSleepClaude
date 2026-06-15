@echo off
chcp 65001 >nul
cd /d C:\Users\mckou\garminSleep
C:\Users\mckou\miniconda3\python.exe detailed_report.py %*
pause
