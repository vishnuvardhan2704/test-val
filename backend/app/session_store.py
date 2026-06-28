"""In-memory session storage. Restart loses sessions — acceptable for a demo,
no DB dependency. Holds conversation history and partial profile only,
never third-party financial data (that's always pulled live, never cached)."""
import uuid
import os
import json
from datetime import datetime
from app.models import SessionState, CompanyProfile

_sessions: dict[str, SessionState] = {}
LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

def create_session() -> SessionState:
    session = SessionState(session_id=str(uuid.uuid4()), profile=CompanyProfile())
    _sessions[session.session_id] = session
    return session

def get_session(session_id: str) -> SessionState | None:
    return _sessions.get(session_id)

def save_session(session: SessionState) -> None:
    _sessions[session.session_id] = session
    
    # Save a persistent JSON log of this session
    log_file = os.path.join(LOGS_DIR, f"{session.session_id}.json")
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(session.model_dump_json(indent=2))
