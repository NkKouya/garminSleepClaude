@echo off
chcp 65001 >nul
cd /d C:\Users\mckou\garminSleep
C:\Users\mckou\miniconda3\python.exe main.py >> logs\task.log 2>&1
