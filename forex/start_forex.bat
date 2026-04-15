@echo off
REM Rickshaw Forex — Start engine daemon + optional GUI
REM Run at boot or double-click to start

cd /d "%~dp0\.."

REM Start the engine daemon (background, no window)
echo Starting forex engine...
start /B pythonw forex\engine_runner.py --interval 60 --heartbeat-every 5

REM Launch GUI
echo Starting forex GUI...
start pythonw forex\forex_gui.pyw

echo Forex engine and GUI started.
timeout /t 3
