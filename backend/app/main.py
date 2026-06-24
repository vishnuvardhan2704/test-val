from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.routes import session, chat

app = FastAPI(title="MSME Valuation Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routes (registered BEFORE static mounts so /api/* takes priority) ──
app.include_router(session.router)
app.include_router(chat.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── Serve the built frontend from frontend/dist ─────────────────────────────
_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


# SPA fallback middleware: if a GET request gets a 404 and the path is NOT
# under /api (or /assets), serve index.html so client-side routing works.
@app.middleware("http")
async def spa_fallback(request: Request, call_next):
    response = await call_next(request)
    if (
        response.status_code == 404
        and request.method == "GET"
        and not request.url.path.startswith("/api")
        and not request.url.path.startswith("/assets")
    ):
        return FileResponse(_DIST / "index.html")
    return response


# Mount the assets sub-directory (JS, CSS, images, etc.)
app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

# Mount remaining static files at root (favicon, icons, etc.)
app.mount("/", StaticFiles(directory=_DIST, html=True), name="static-root")
