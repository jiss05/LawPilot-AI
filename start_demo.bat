@echo off
REM ==========================================================================
REM  LawPilot demo launcher  (double-click this file)
REM
REM  Opens two windows:
REM    1. "LawPilot backend"  - the FastAPI server on http://localhost:8000
REM    2. "LawPilot frontend" - the React app on http://localhost:5173
REM  then opens the browser tabs used in the demo, in demo order.
REM
REM  Before running: the Docker PC (Postgres + Qdrant) must be switched on.
REM  To stop the demo: close the two windows.
REM ==========================================================================

set ROOT=%~dp0

echo Starting the backend ...
start "LawPilot backend" cmd /k "cd /d %ROOT%backend && call .venv\Scripts\activate.bat && uvicorn app.main:app --port 8000"

echo Starting the frontend ...
if not exist "%ROOT%frontend\node_modules" (
    echo First run: installing frontend packages, this takes a minute ...
    start "LawPilot frontend" cmd /k "cd /d %ROOT%frontend && npm install && npm run dev"
) else (
    start "LawPilot frontend" cmd /k "cd /d %ROOT%frontend && npm run dev"
)

echo Waiting 20 seconds for the servers to start (the AI models load at start-up) ...
timeout /t 20 /nobreak >nul

start "" http://localhost:8000/api/v1/health/ready
start "" http://localhost:5173
start "" http://localhost:8000/docs
start "" http://100.118.215.122:6333/dashboard

echo.
echo Check the first browser tab: it must say "ready".
echo If it does not, wait 30 seconds and refresh it.
echo.
pause
