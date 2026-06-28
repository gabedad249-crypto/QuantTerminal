@echo off
cd /d %~dp0
git pull
python -m pip install -r requirements.txt
pause
