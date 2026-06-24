from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.gemini_client import QuotaExceededError
from app.agents.graph import get_graph
from app.models import ChatTurn
from app.session_store import get_session, save_session

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str
    message: str


@router.post("/api/chat")
def chat(req: ChatRequest):
    session = get_session(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    session.history.append(ChatTurn(role="user", content=req.message))

    graph_state = {
        "history": [turn.model_dump() for turn in session.history],
        "profile": session.profile.model_dump(),
        "website_context": None,
        "stage": session.stage,
        "assistant_message": "",
        "report": None,
    }

    try:
        result = get_graph().invoke(graph_state)
    except QuotaExceededError:
        session.history.pop()  # don't keep the user message stuck waiting for a reply
        save_session(session)
        return {
            "stage": session.stage,
            "message": "I've hit today's free-tier rate limit on the AI model. Please try again in a little while.",
            "profile": session.profile.model_dump(),
            "report": session.report,
        }

    session.profile = session.profile.model_copy(update=result["profile"])
    session.stage = result["stage"]
    session.history.append(ChatTurn(role="assistant", content=result["assistant_message"]))
    if result["report"] is not None:
        session.report = result["report"]
    save_session(session)

    return {
        "stage": session.stage,
        "message": result["assistant_message"],
        "profile": session.profile.model_dump(),
        "report": session.report,
    }
