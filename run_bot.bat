@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist .env (
  copy .env.example .env >nul
  echo.
  echo  .env file created. Paste your BOT_TOKEN from @BotFather into it, save, and run this file again.
  echo.
  notepad .env
  pause
  exit /b
)

if not exist .venv\Scripts\python.exe (
  echo Creating Python environment...
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
if not exist .venv\Scripts\python.exe (
  echo Python not found. Install Python 3.11+ from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b
)

echo Installing libraries...
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt

echo.
echo  Bot is running. Keep this window open. Close it to stop the bot.
echo.
.venv\Scripts\python.exe bot.py
pause
