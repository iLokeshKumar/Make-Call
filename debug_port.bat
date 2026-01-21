@echo off
set PORT=6060
echo Searching for processes on port %PORT%...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :%PORT% ^| findstr LISTENING') do (
    set PID=%%a
)

if "%PID%"=="" (
    echo [OK] Port %PORT% is free.
) else (
    echo [CONFLICT] Process ID %PID% is using port %PORT%.
    tasklist /FI "PID eq %PID%"
    echo.
    set /p choice="Do you want to kill this process? (y/n): "
    if "%choice%"=="y" (
        taskkill /F /PID %PID%
        echo Process killed.
    )
)
pause
