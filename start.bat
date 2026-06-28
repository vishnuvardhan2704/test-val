@echo off
title MSME Valuation Agent
echo ============================================
echo   MSME Valuation Agent - Starting...
echo ============================================
echo.

REM Check if .env exists
if not exist "backend\.env" (
    echo [WARNING] backend\.env not found!
    echo Copy backend\.env.example to backend\.env and fill in your API keys.
    echo.
    copy "backend\.env.example" "backend\.env"
    echo Created backend\.env from template - please edit it with your keys, then re-run.
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist "backend\.venv\Scripts\python.exe" (
    echo [INFO] Creating Python virtual environment in backend\.venv...
    cd backend
    python -m venv .venv
    echo [INFO] Installing requirements...
    ".venv\Scripts\pip.exe" install -r requirements.txt
    cd ..
)

REM Start the backend (also serves the frontend from frontend/dist)
echo Starting FastAPI server on http://127.0.0.1:8001 ...
echo.
echo Frontend: http://127.0.0.1:8001
echo API docs:  http://127.0.0.1:8001/docs
echo.
echo Press Ctrl+C to stop the server.
echo.

REM Open browser after a short delay
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:8001"

REM Run uvicorn from the backend directory so the .env is picked up
cd backend
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
