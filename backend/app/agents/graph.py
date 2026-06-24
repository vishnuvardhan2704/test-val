"""LangGraph orchestration for the valuation pipeline.

interview_extract (LLM) -> [missing fields? -> ask_question (LLM) -> END]
                         -> [complete? -> peer_discovery -> valuation -> report (LLM) -> END]

Peer discovery and valuation are pure deterministic Python (see app.services.*).
Only extraction, question phrasing, and the final report are LLM calls.
"""
import json
from typing import TypedDict

from langgraph.graph import StateGraph, END

from app.agents import prompts
from app.agents.gemini_client import generate_json, generate_text
from app.models import CompanyProfile
from app.services.peer_discovery import discover_peers
from app.services.valuation import compute_valuation
from app.services.website_context import extract_website_url, fetch_website_context, normalize_website_url


class GraphState(TypedDict):
    history: list[dict]
    profile: dict
    website_context: str | None
    stage: str
    assistant_message: str
    report: dict | None


def _conversation_text(history: list[dict]) -> str:
    return "\n".join(f"{turn['role']}: {turn['content']}" for turn in history) or "(no messages yet)"


def extract_profile_node(state: GraphState) -> GraphState:
    if not state["history"]:
        return state
    conversation = _conversation_text(state["history"])
    profile = dict(state["profile"])
    website_context = state.get("website_context")

    prompt = prompts.EXTRACTION_PROMPT.format(
        conversation=conversation,
        website_context=website_context or "(not provided)",
    )
    extracted = generate_json(prompt)

    for key, value in extracted.items():
        if value is not None and key in profile:
            profile[key] = value

    website_url = normalize_website_url(profile.get("website_url")) or extract_website_url(conversation)
    if website_url:
        profile["website_url"] = website_url
        fetched_context = website_context or fetch_website_context(website_url)
        if fetched_context:
            website_context = fetched_context
            website_prompt = prompts.EXTRACTION_PROMPT.format(
                conversation=conversation,
                website_context=website_context,
            )
            website_extracted = generate_json(website_prompt)
            for key, value in website_extracted.items():
                if value is not None and key in profile:
                    profile[key] = value

    return {**state, "profile": profile, "website_context": website_context}


def route_after_extract(state: GraphState) -> str:
    profile = CompanyProfile(**state["profile"])
    return "ask_question" if profile.missing_required_fields() else "run_valuation"


def ask_question_node(state: GraphState) -> GraphState:
    profile = CompanyProfile(**state["profile"])
    missing = profile.missing_required_fields()
    prompt = prompts.NEXT_QUESTION_PROMPT.format(
        profile_json=json.dumps(state["profile"], indent=2),
        missing_fields=", ".join(missing),
        conversation=_conversation_text(state["history"]),
        website_context=state.get("website_context") or "(not provided)",
    )
    message = generate_text(prompt)
    return {**state, "assistant_message": message, "stage": "interview"}


def run_valuation_node(state: GraphState) -> GraphState:
    profile = CompanyProfile(**state["profile"])

    discovery = discover_peers(profile, website_context=state.get("website_context"))
    result = compute_valuation(profile, discovery.peers)
    result = result.model_copy(update={"methodology_notes": discovery.methodology_notes + result.methodology_notes})

    report_text = generate_text(
        prompts.REPORT_PROMPT.format(
            profile_json=result.profile.model_dump_json(indent=2),
            website_context=state.get("website_context") or "(not provided)",
            peers_json=json.dumps([p.model_dump() for p in result.peers_used], indent=2),
            valuation_json=result.model_dump_json(
                indent=2, exclude={"profile", "peers_used", "verification_note"}
            ),
            verification_note=result.verification_note,
        )
    )

    report = result.model_dump()
    report["narrative"] = report_text

    return {
        **state,
        "profile": profile.model_dump(),
        "stage": "report_ready",
        "assistant_message": report_text,
        "report": report,
    }


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("extract_profile", extract_profile_node)
    graph.add_node("ask_question", ask_question_node)
    graph.add_node("run_valuation", run_valuation_node)

    graph.set_entry_point("extract_profile")
    graph.add_conditional_edges(
        "extract_profile",
        route_after_extract,
        {"ask_question": "ask_question", "run_valuation": "run_valuation"},
    )
    graph.add_edge("ask_question", END)
    graph.add_edge("run_valuation", END)

    return graph.compile()


_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph
