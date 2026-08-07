@echo off
setlocal
title prop_bot
cd /d C:\code\mt5_live\fundednext

set PY=C:\Users\User\AppData\Local\Programs\Python\Python311\python.exe

if not exist "%PY%" (
    echo ERROR: python not found at %PY%
    pause
    exit /b 1
)
if not exist "live_mt5_bot_PROP.py" (
    echo ERROR: live_mt5_bot_PROP.py not found in C:\code\mt5_live\fundednext
    pause
    exit /b 1
)
if not exist "spread_audit.py" (
    echo WARNING: spread_audit.py not found - starting bot WITHOUT the audit.
) else (
    tasklist /fi "windowtitle eq spread_audit" 2>nul | find /i "python" >nul
    if errorlevel 1 (
        echo starting spread audit collector in a minimized window...
        start "spread_audit" /min "%PY%" spread_audit.py --collect
    ) else (
        echo spread audit already running - not starting a second one.
    )
)

echo.
echo IMPORTANT: this window IS the bot. Close it to stop the bot.
echo Make sure no OTHER window is already running live_mt5_bot_PROP.py!
echo.
"%PY%" live_mt5_bot_PROP.py

echo.
echo ============================================
echo The bot process has EXITED. Read any error above.
echo ============================================
pause
