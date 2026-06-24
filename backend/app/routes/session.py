from fastapi import APIRouter

from app.agents.gemini_client import QuotaExceededError
from app.agents.graph import get_graph
from app.models import ChatTurn
from app.session_store import create_session, save_session

router = APIRouter()

_FALLBACK_GREETING = (
    "Hi! I'm your valuation assistant. I've hit today's free-tier rate limit on the AI model, "
    "so please bear with me — try sending your company name and sector in chat in a little while."
)


@router.post("/api/session")
def new_session():
    session = create_session()

    graph_state = {
        "history": [],
        "profile": session.profile.model_dump(),
        "website_context": None,
        "stage": session.stage,
        "assistant_message": "",
        "report": None,
    }
    try:
        result = get_graph().invoke(graph_state)
        message = result["assistant_message"]
    except QuotaExceededError:
        message = _FALLBACK_GREETING

    session.history.append(ChatTurn(role="assistant", content=message))
    save_session(session)

    return {"session_id": session.session_id, "message": message}
