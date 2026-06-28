#!/usr/bin/env bash
echo "============================================"
echo "  MSME Valuation Agent - Starting..."
echo "============================================"
echo ""

# Check if .env exists
if [ ! -f "backend/.env" ]; then
    echo "[WARNING] backend/.env not found!"
    echo "Copying backend/.env.example to backend/.env..."
    cp backend/.env.example backend/.env
    echo "Created backend/.env from template - please edit it with your keys, then re-run."
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "backend/.venv" ]; then
    echo "[INFO] Creating Python virtual environment in backend/.venv..."
    cd backend
    python3 -m venv .venv
    echo "[INFO] Installing requirements..."
    ./.venv/bin/pip install -r requirements.txt
    cd ..
fi

echo "Starting FastAPI server on http://127.0.0.1:8001 ..."
echo ""
echo "Frontend: http://127.0.0.1:8001"
echo "API docs: http://127.0.0.1:8001/docs"
echo ""
echo "Press Ctrl+C to stop the server."
echo ""

# Open browser based on OS
sleep 2 && (
    if command -v xdg-open &> /dev/null; then
        xdg-open "http://127.0.0.1:8001"
    elif command -v open &> /dev/null; then
        open "http://127.0.0.1:8001"
    fi
) &

# Run uvicorn from the backend directory so the .env is picked up
cd backend
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
