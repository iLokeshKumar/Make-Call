@echo off
echo Starting Rio CRM System...

:: Start Backend
start "Rio Backend (FastAPI)" cmd /k "cd backend && myenvironment\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 6060 --reload"
:: Start Frontend
start "Rio Dashboard (Next.js)" cmd /k "cd frontend && npm run dev"

echo.
echo ==================================================
echo   Servers are launching in new windows.
echo   Backend URL: http://localhost:6060
echo   Frontend URL: http://localhost:3006
echo ==================================================
echo.
pause
