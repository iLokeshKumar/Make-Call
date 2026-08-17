@echo off
echo Starting Rio CRM System...

start "Rio Backend (FastAPI)" cmd /k "cd backend && myenvironment\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 6060 --reload"

start "Rio Worker" cmd /k "cd backend && myenvironment\Scripts\python.exe run_automation_worker.py --poll-interval 30"

start "Rio Dashboard (Next.js)" cmd /k "cd frontend && npm run dev"

echo.
echo ==================================================
echo   Servers are launching in new windows.
echo   Backend URL: http://localhost:6060
echo   Frontend URL: http://localhost:3006
echo   Worker:      30s poll + NOTIFY-driven
echo ==================================================
echo.
pause