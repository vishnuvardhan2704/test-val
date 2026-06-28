"""LangGraph orchestration for the valuation pipeline.

interview_extract (LLM) -> [missing fields? -> ask_question (LLM) -> END]
                         -> [complete? -> peer_discovery + screener scrape -> valuation -> report (LLM) -> END]

Peer discovery, the Screener.in scrape, and valuation are pure deterministic
Python (see app.services.*) — only extraction, question phrasing, and the
final report narrative are LLM calls. Every external data source attempted
in run_valuation_node (live listed peers, Screener.in, company website) is
recorded as a DataSourceStatus row so the dashboard can show exactly what
worked and what didn't, instead of a black box.
"""
import json
import logging
from typing import TypedDict

from langgraph.graph import StateGraph, END

from app.agents import prompts
from app.agents.gemini_client import generate_json, generate_text
from app.models import CompanyProfile, DataSourceStatus, ScreenerSnapshot
from app.services import screener_scraper
from app.services.peer_discovery import discover_peers
from app.services.valuation import compute_valuation
from app.services.website_context import extract_website_url, fetch_website_context, normalize_website_url

logger = logging.getLogger(__name__)


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


# Screener.in field -> CompanyProfile field, used only to *fill gaps*, never
# to overwrite a value the founder already gave us directly.
_SCREENER_PROFILE_FALLBACKS = {
    "sales_growth_3y_pct": "revenue_growth_pct",
    "debt_cr": "debt_cr",
}


def _run_screener_scrape(profile: CompanyProfile) -> tuple[ScreenerSnapshot, DataSourceStatus]:
    query = profile.company_name or ""
    try:
        result = screener_scraper.scrape_company(query)
    except Exception as exc:  # belt-and-suspenders: scrape_company contracts to never raise
        logger.warning("Unexpected exception from screener_scraper.scrape_company: %s", exc)
        result = screener_scraper.ScreenerScrapeResult(success=False, detail=f"Unexpected error: {exc}")

    snapshot = ScreenerSnapshot(
        matched_company_name=result.matched_company_name,
        screener_url=result.screener_url,
        fields_found=result.fields_found,
        **{k: v for k, v in result.fields.items() if k in ScreenerSnapshot.model_fields},
    )
    status = DataSourceStatus(
        name="Screener.in",
        attempted=True,
        success=result.success,
        fields_retrieved=result.fields_found,
        detail=result.detail,
    )
    return snapshot, status


def _apply_screener_fallbacks(profile: CompanyProfile, snapshot: ScreenerSnapshot) -> CompanyProfile:
    updates = {}
    if profile.revenue_growth_pct is None and snapshot.sales_growth_3y_pct is not None:
        updates["revenue_growth_pct"] = snapshot.sales_growth_3y_pct
    if not updates:
        return profile
    return profile.model_copy(update=updates)


def run_valuation_node(state: GraphState) -> GraphState:
    profile = CompanyProfile(**state["profile"])
    data_sources: list[DataSourceStatus] = []

    website_context = state.get("website_context")
    data_sources.append(
        DataSourceStatus(
            name="Company website",
            attempted=bool(profile.website_url),
            success=bool(website_context),
            fields_retrieved=["page text context"] if website_context else [],
            detail=(
                f"Fetched context from {profile.website_url}." if website_context
                else ("No website URL available." if not profile.website_url else "Website provided but fetch failed or returned nothing usable.")
            ),
        )
    )

    screener_snapshot, screener_status = _run_screener_scrape(profile)
    data_sources.append(screener_status)
    profile = _apply_screener_fallbacks(profile, screener_snapshot)

    # Discover peers purely from Screener.in's "Peer Comparison" table
    screener_peers, screener_peer_detail = discover_peers(profile)
    usable_screener_peers = [p for p in screener_peers if p.ev_ebitda is not None or p.ev_revenue is not None]
    
    data_sources.append(
        DataSourceStatus(
            name="Screener.in peer comparison",
            attempted=bool(profile.company_name),
            success=len(usable_screener_peers) > 0,
            fields_retrieved=[f"{p.name} ({p.ticker})" for p in usable_screener_peers],
            detail=screener_peer_detail,
        )
    )

    methodology_notes: list[str] = []
    if usable_screener_peers:
        peers_used = usable_screener_peers
        methodology_notes.append(
            f"Peer set sourced directly from Screener.in's own peer-comparison table "
            f"({len(usable_screener_peers)} peer(s) with a usable EV/EBITDA or EV/Revenue multiple)."
        )
    else:
        peers_used = []
        methodology_notes.append(
            "Screener.in's peer-comparison table did not yield usable peers for this run "
            f"({screener_peer_detail}). Valuation will rely heavily on the DCF method."
        )

    result = compute_valuation(profile, peers_used, screener=screener_snapshot, data_sources=data_sources)
    result = result.model_copy(update={"methodology_notes": methodology_notes + result.methodology_notes})

    report_text = generate_text(
        prompts.REPORT_PROMPT.format(
            profile_json=result.profile.model_dump_json(indent=2),
            website_context=website_context or "(not provided)",
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
        "website_context": website_context,
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
