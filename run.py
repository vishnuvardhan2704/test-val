#!/usr/bin/env python3
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
DEFAULT_BACKEND_PORT = 8000
DEFAULT_FRONTEND_PORT = 5173
GROQ_MODEL = "llama-3.3-70b-versatile"
COMMON_CHROME_PATHS = [
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/snap/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def find_tool(name):
    if os.name == "nt":
        fallback = f"{name}.cmd"
        return shutil.which(name) or shutil.which(fallback)
    return shutil.which(name)


def is_port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def find_free_port(start_port):
    port = start_port
    while port < 65535:
        if is_port_free(port):
            return port
        port += 1
    raise RuntimeError("No free port available")


def find_chrome_binary():
    env_path = os.environ.get("CHROME_BINARY") or os.environ.get("CHROME_BIN")
    if env_path and Path(env_path).exists():
        return env_path
    for path in COMMON_CHROME_PATHS:
        if Path(path).exists():
            return path
    for candidate in ("google-chrome", "chromium-browser", "chromium"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def start_process(command, cwd, env=None):
    return subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def open_browser(url, delay=2):
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    thread = threading.Thread(target=_open, daemon=True)
    thread.start()


def main():
    if not BACKEND_DIR.exists() or not FRONTEND_DIR.exists():
        print("ERROR: expected backend/ and frontend/ directories in the repository root.")
        sys.exit(1)

    npm_executable = find_tool("npm")
    if npm_executable is None:
        print("ERROR: npm executable not found on PATH. Install Node.js/npm first.")
        sys.exit(1)

    backend_port = DEFAULT_BACKEND_PORT
    frontend_port = DEFAULT_FRONTEND_PORT

    if not is_port_free(backend_port):
        print(f"Warning: backend port {backend_port} is already in use. Looking for a free port...")
        backend_port = find_free_port(backend_port + 1)
        print(f"Using backend port {backend_port} instead.")

    if not is_port_free(frontend_port):
        print(f"Warning: frontend port {frontend_port} is already in use. Looking for a free port...")
        frontend_port = find_free_port(frontend_port + 1)
        print(f"Using frontend port {frontend_port} instead.")

    backend_url = f"http://127.0.0.1:{backend_port}"
    frontend_url = f"http://127.0.0.1:{frontend_port}"

    print("Starting backend and frontend together...")
    print(f"Backend: {backend_url}")
    print(f"Frontend: {frontend_url}")
    print("Press Ctrl+C to stop both servers.")
    print()

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["VITE_BACKEND_URL"] = backend_url
    
    # Forward Groq API Key if set in environment, otherwise let the backend read from backend/.env
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if groq_api_key:
        env["GROQ_API_KEY"] = groq_api_key
    env["GROQ_MODEL"] = os.environ.get("GROQ_MODEL", GROQ_MODEL)

    chrome_binary = find_chrome_binary()
    if chrome_binary:
        env["CHROME_BINARY"] = chrome_binary
        print(f"Using Chrome/Chromium binary: {chrome_binary}")
    else:
        print(
            "Warning: no Chrome/Chromium binary found on the host. "
            "Screener.in Selenium scraping will be disabled until you install one."
        )

    # Use virtual environment's Python if it exists, otherwise fall back to system Python
    venv_python = BACKEND_DIR / ".venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable

    backend_cmd = [
        python_exe,
        "-m",
        "uvicorn",
        "app.main:app",
        "--reload",
        "--host",
        "0.0.0.0",
        "--port",
        str(backend_port),
    ]
    frontend_cmd = [npm_executable, "run", "dev", "--", "--host", "0.0.0.0", "--port", str(frontend_port)]

    backend_proc = start_process(backend_cmd, BACKEND_DIR, env=env)
    frontend_proc = start_process(frontend_cmd, FRONTEND_DIR, env=env)

    open_browser(frontend_url)

    def shutdown(signum=None, frame=None):
        print("\nShutting down frontend and backend...")
        for proc in (frontend_proc, backend_proc):
            if proc and proc.poll() is None:
                proc.terminate()
        time.sleep(1)
        for proc in (frontend_proc, backend_proc):
            if proc and proc.poll() is None:
                proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    try:
        while True:
            backend_exit = backend_proc.poll()
            frontend_exit = frontend_proc.poll()
            if backend_exit is not None or frontend_exit is not None:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown()

    if backend_exit is not None:
        print(f"Backend exited with code {backend_exit}.")
    if frontend_exit is not None:
        print(f"Frontend exited with code {frontend_exit}.")

    shutdown()


if __name__ == "__main__":
    main()
