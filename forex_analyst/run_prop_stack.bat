@echo off
rem ============================================================
rem  run_prop_stack.bat - one-click start: spread audit + PROP bot
rem  Bot code stays untouched (challenge freeze discipline).
rem  The audit runs as its own minimized window, read-only.
rem ============================================================
cd /d C:\code\mt5_live\fundednext
set PY=C:\Users\User\AppData\Local\Programs\Python\Python311\python.exe

rem -- start the spread collector only if it is not already running
tasklist /fi "windowtitle eq spread_audit*" 2>nul | find /i "python.exe" >nul
if errorlevel 1 (
    echo starting spread audit collector (minimized)...
    start "spread_audit" /min %PY% spread_audit.py --collect
) else (
    echo spread audit already running - not starting a second one.
)

rem -- exactly ONE bot process must ever run: refuse if one exists
tasklist /fi "windowtitle eq prop_bot*" 2>nul | find /i "python.exe" >nul
if not errorlevel 1 (
    echo ERROR: a prop_bot window is already running. Close it first.
    pause
    exit /b 1
)

title prop_bot
%PY% live_mt5_bot_PROP.py
