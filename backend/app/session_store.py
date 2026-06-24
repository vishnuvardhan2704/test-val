"""In-memory session storage. Restart loses sessions — acceptable for a demo,
no DB dependency. Holds conversation history and partial profile only,
never third-party financial data (that's always pulled live, never cached)."""
import uuid
from app.models import SessionState, CompanyProfile

_sessions: dict[str, SessionState] = {}


def create_session() -> SessionState:
    session = SessionState(session_id=str(uuid.uuid4()), profile=CompanyProfile())
    _sessions[session.session_id] = session
    return session


def get_session(session_id: str) -> SessionState | None:
    return _sessions.get(session_id)


def save_session(session: SessionState) -> None:
    _sessions[session.session_id] = session
