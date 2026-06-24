"""Deterministic peer discovery built from LLM anchors plus yfinance expansion.

The LLM may suggest anchor companies, but it never selects the final peer set.
Final peer selection is deterministic and based on yfinance data plus fixed
similarity scoring.
"""
from __future__ import annotations

import logging
import math
import re
from collections import OrderedDict
from typing import Iterable

import yfinance as yf
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.agents import prompts
from app.agents.gemini_client import generate_json
from app.models import AnchorCompany, CompanyProfile, PeerCompany, PeerDiscoveryResult
from app.services import yfinance_service

logger = logging.getLogger(__name__)


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def _normalize_ticker(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip().upper()
    if not candidate:
        return None
    if not re.search(r"\.[A-Z]{2,4}$", candidate):
        return candidate
    return candidate


def _extract_ticker_from_search_result(item) -> str | None:
    if item is None:
        return None
    if isinstance(item, str):
        return _normalize_ticker(item)
    if isinstance(item, dict):
        for key in ("symbol", "ticker", "tickerSymbol", "shortname"):
            candidate = item.get(key)
            if candidate:
                return _normalize_ticker(str(candidate))
        return None
    for attr in ("symbol", "ticker", "tickerSymbol"):
        candidate = getattr(item, attr, None)
        if candidate:
            return _normalize_ticker(str(candidate))
    return None


def _search_ticker(query: str) -> str | None:
    query = _clean_text(query)
    if not query:
        return None
    try:
        result = yf.Search(query)
        quotes = getattr(result, "quotes", None) or getattr(result, "all", None) or []
        for item in quotes:
            ticker = _extract_ticker_from_search_result(item)
            if ticker:
                return ticker
    except Exception as exc:
        logger.warning("yfinance search failed for %s: %s", query, exc)
    return None


def _as_list(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return list(value.values())
    return list(value) if hasattr(value, "__iter__") and not isinstance(value, str) else [value]


def _entry_to_ticker(entry) -> str | None:
    if entry is None:
        return None
    if isinstance(entry, str):
        text = entry.strip()
        if not text:
            return None
        if "." in text:
            return _normalize_ticker(text)
        return _normalize_ticker(text)
    if isinstance(entry, dict):
        for key in ("symbol", "ticker", "tickerSymbol", "name"):
            candidate = entry.get(key)
            if candidate:
                ticker = _normalize_ticker(str(candidate))
                if ticker:
                    return ticker
    for attr in ("symbol", "ticker", "ticker_symbol", "name"):
        candidate = getattr(entry, attr, None)
        if candidate:
            ticker = _normalize_ticker(str(candidate))
            if ticker:
                return ticker
    return None


def _extract_sector_candidates(obj, *attributes: str) -> list[str]:
    tickers: list[str] = []
    for attribute in attributes:
        items = _as_list(getattr(obj, attribute, None))
        for entry in items:
            ticker = _entry_to_ticker(entry)
            if ticker:
                tickers.append(ticker)
    return tickers


def _resolve_anchor_ticker(anchor: AnchorCompany) -> str | None:
    if anchor.ticker:
        ticker = _normalize_ticker(anchor.ticker)
        if ticker:
            return ticker
    return _search_ticker(anchor.name)


def _fallback_anchors(profile: CompanyProfile) -> list[AnchorCompany]:
    anchors: list[AnchorCompany] = []
    if profile.company_name:
        anchors.append(AnchorCompany(name=profile.company_name, ticker=_search_ticker(profile.company_name), rationale="Fallback anchor from founder profile"))
    if profile.competitors:
        for competitor in profile.competitors[:4]:
            anchors.append(AnchorCompany(name=competitor, ticker=_search_ticker(competitor), rationale="Fallback anchor from competitor mention"))
    if not anchors and profile.sector:
        anchors.append(AnchorCompany(name=profile.sector, ticker=_search_ticker(profile.sector), rationale="Fallback anchor from sector description"))
    return anchors[:5]


def generate_anchor_companies(profile: CompanyProfile, website_context: str | None = None) -> list[AnchorCompany]:
    prompt = prompts.ANCHOR_COMPANY_PROMPT.format(
        profile_json=profile.model_dump_json(indent=2),
        website_context=website_context or "(not provided)",
    )
    try:
        payload = generate_json(prompt)
    except Exception as exc:
        logger.warning("Anchor generation failed: %s", exc)
        return _fallback_anchors(profile)

    anchors: list[AnchorCompany] = []
    raw_anchors = payload.get("anchors") if isinstance(payload, dict) else None
    for item in raw_anchors or []:
        if not isinstance(item, dict):
            continue
        name = _clean_text(str(item.get("name") or ""))
        if not name:
            continue
        anchors.append(
            AnchorCompany(
                name=name,
                ticker=_normalize_ticker(str(item.get("ticker") or "")) if item.get("ticker") else _search_ticker(name),
                rationale=_clean_text(str(item.get("rationale") or "")) or None,
            )
        )
    return anchors[:5] or _fallback_anchors(profile)


def _peer_description(profile: CompanyProfile, website_context: str | None = None) -> str:
    pieces: list[str] = [
        profile.company_name or "",
        profile.sector or "",
        profile.industry or "",
        profile.sub_industry or "",
        profile.business_model or "",
        profile.customer_type or "",
        profile.geography or "",
        ", ".join(profile.keywords or []),
        website_context or "",
    ]
    return _clean_text(" . ".join(piece for piece in pieces if piece))


def _candidate_description(peer: PeerCompany) -> str:
    pieces: list[str] = [
        peer.name,
        peer.sector or "",
        peer.industry or "",
        peer.long_business_summary or "",
    ]
    return _clean_text(" . ".join(piece for piece in pieces if piece))


def _region_from_country(country: str | None) -> str:
    text = (country or "").strip().lower()
    if not text:
        return "unknown"
    if any(token in text for token in ("india", "china", "japan", "singapore", "malaysia", "thailand", "indonesia", "vietnam", "philippines", "pakistan", "bangladesh", "sri lanka", "uae", "saudi", "qatar", "kuwait", "hong kong", "taiwan", "korea", "australia", "new zealand")):
        return "asia_pacific"
    if any(token in text for token in ("united states", "usa", "canada", "mexico")):
        return "north_america"
    if any(token in text for token in ("united kingdom", "uk", "germany", "france", "italy", "spain", "netherlands", "switzerland", "sweden", "norway", "denmark", "finland", "poland", "europe")):
        return "europe"
    if any(token in text for token in ("brazil", "argentina", "chile", "colombia", "latin")):
        return "latin_america"
    if any(token in text for token in ("uae", "saudi", "qatar", "kuwait", "middle east", "israel")):
        return "middle_east"
    if any(token in text for token in ("south africa", "nigeria", "kenya", "africa")):
        return "africa"
    return "other"


def _industry_similarity(profile: CompanyProfile, peer: PeerCompany) -> float:
    profile_industry = _clean_text(profile.industry or profile.sub_industry or profile.sector)
    peer_industry = _clean_text(peer.industry or peer.sector)
    if profile_industry and peer_industry and profile_industry.lower() == peer_industry.lower():
        return 1.0
    profile_sector = _clean_text(profile.sector)
    peer_sector = _clean_text(peer.sector)
    if profile_sector and peer_sector and profile_sector.lower() == peer_sector.lower():
        return 0.65
    if profile_sector and peer_sector and any(token in peer_sector.lower() for token in profile_sector.lower().split() if len(token) > 2):
        return 0.45
    return 0.2


def _revenue_similarity(profile: CompanyProfile, peer: PeerCompany) -> float:
    if not profile.revenue_cr or not peer.revenue_cr or profile.revenue_cr <= 0 or peer.revenue_cr <= 0:
        return 0.0
    distance = abs(math.log1p(profile.revenue_cr) - math.log1p(peer.revenue_cr))
    return max(0.0, min(1.0, 1.0 / (1.0 + distance)))


def _margin_similarity(profile: CompanyProfile, peer: PeerCompany) -> float:
    if profile.ebitda_margin is None or peer.ebitda_margin is None:
        return 0.0
    distance = abs(profile.ebitda_margin - peer.ebitda_margin)
    return max(0.0, 1.0 - min(distance, 1.0))


def _geography_similarity(profile: CompanyProfile, peer: PeerCompany) -> float:
    profile_country = _clean_text(profile.geography or profile.city)
    peer_country = _clean_text(peer.country)
    if not profile_country or not peer_country:
        return 0.0
    if profile_country.lower() == peer_country.lower():
        return 1.0
    if _region_from_country(profile_country) == _region_from_country(peer_country):
        return 0.5
    return 0.2


def _description_similarity(profile: CompanyProfile, peers: list[PeerCompany], website_context: str | None = None) -> list[float]:
    target_description = _peer_description(profile, website_context)
    documents = [target_description] + [_candidate_description(peer) for peer in peers]
    if not target_description.strip() or len({doc.lower() for doc in documents if doc.strip()}) < 2:
        return [0.0 for _ in peers]
    try:
        vectorizer = TfidfVectorizer(stop_words="english")
        matrix = vectorizer.fit_transform(documents)
        scores = cosine_similarity(matrix[0:1], matrix[1:]).flatten().tolist()
        return [max(0.0, min(1.0, score)) for score in scores]
    except Exception as exc:
        logger.warning("TF-IDF similarity failed: %s", exc)
        return [0.0 for _ in peers]


def _candidate_breakdown(profile: CompanyProfile, peer: PeerCompany, description_score: float) -> tuple[float, str]:
    industry_score = _industry_similarity(profile, peer)
    revenue_score = _revenue_similarity(profile, peer)
    margin_score = _margin_similarity(profile, peer)
    geography_score = _geography_similarity(profile, peer)
    final_score = (
        0.40 * industry_score
        + 0.20 * revenue_score
        + 0.10 * margin_score
        + 0.10 * geography_score
        + 0.20 * description_score
    )
    rationale = (
        f"industry={industry_score:.2f}, revenue={revenue_score:.2f}, margin={margin_score:.2f}, "
        f"geography={geography_score:.2f}, description={description_score:.2f}"
    )
    return max(0.0, min(1.0, final_score)), rationale


def _collect_candidate_universe(anchors: list[AnchorCompany]) -> tuple[list[str], list[str]]:
    candidate_tickers: list[str] = []
    notes: list[str] = []
    for anchor in anchors:
        ticker = _resolve_anchor_ticker(anchor)
        if not ticker:
            notes.append(f"Could not resolve a ticker for anchor '{anchor.name}'")
            continue
        candidate_tickers.append(ticker)
        try:
            info = yf.Ticker(ticker).info or {}
        except Exception as exc:
            notes.append(f"Failed to inspect anchor ticker {ticker}: {exc}")
            continue

        sector_key = info.get("sectorKey")
        industry_key = info.get("industryKey")
        if sector_key:
            try:
                sector_obj = yf.Sector(sector_key)
                candidate_tickers.extend(_extract_sector_candidates(sector_obj, "top_companies"))
                notes.append(f"Expanded {ticker} via sector key {sector_key}")
            except Exception as exc:
                notes.append(f"Sector expansion failed for {ticker} ({sector_key}): {exc}")
        if industry_key:
            try:
                industry_obj = yf.Industry(industry_key)
                candidate_tickers.extend(_extract_sector_candidates(industry_obj, "top_companies", "top_growth_companies", "top_performing_companies"))
                notes.append(f"Expanded {ticker} via industry key {industry_key}")
            except Exception as exc:
                notes.append(f"Industry expansion failed for {ticker} ({industry_key}): {exc}")

    unique_tickers = list(OrderedDict.fromkeys(ticker for ticker in candidate_tickers if ticker))
    return unique_tickers, notes


def _build_peer_company(ticker: str, sector_tag: str) -> PeerCompany | None:
    financials = yfinance_service.fetch_financials(ticker)
    if financials is None:
        return None
    return PeerCompany(
        ticker=ticker,
        name=financials.name or ticker,
        sector_tag=sector_tag,
        sector=getattr(financials, "sector", None),
        sector_key=getattr(financials, "sector_key", None),
        industry=getattr(financials, "industry", None),
        industry_key=getattr(financials, "industry_key", None),
        country=getattr(financials, "country", None),
        revenue_growth=getattr(financials, "revenue_growth", None),
        enterprise_value_cr=getattr(financials, "enterprise_value_cr", None),
        full_time_employees=getattr(financials, "full_time_employees", None),
        long_business_summary=getattr(financials, "long_business_summary", None),
        ev_ebitda=financials.ev_ebitda,
        ev_revenue=financials.ev_revenue,
        ebitda_margin=financials.ebitda_margin,
        market_cap_cr=financials.market_cap_cr,
        revenue_cr=financials.revenue_cr,
        source="yfinance",
    )


def discover_peers(profile: CompanyProfile, website_context: str | None = None) -> PeerDiscoveryResult:
    anchors = generate_anchor_companies(profile, website_context=website_context)
    methodology_notes: list[str] = []
    if anchors:
        methodology_notes.append(
            "Anchor companies selected: " + ", ".join(f"{anchor.name}{f' ({anchor.ticker})' if anchor.ticker else ''}" for anchor in anchors)
        )
    else:
        methodology_notes.append("No anchors could be generated; proceeding with deterministic fallback anchors.")

    candidate_tickers, expansion_notes = _collect_candidate_universe(anchors)
    methodology_notes.extend(expansion_notes)

    if len(candidate_tickers) < 5:
        fallback_tickers = [ticker for ticker in (_resolve_anchor_ticker(anchor) for anchor in anchors) if ticker]
        candidate_tickers = list(OrderedDict.fromkeys(candidate_tickers + fallback_tickers))
        methodology_notes.append(
            "Candidate universe smaller than 5, so anchor tickers were added directly as fallback candidates."
        )

    methodology_notes.append(f"Candidate universe size discovered: {len(candidate_tickers)}")

    sector_tag = profile.nse_sector_tag or _clean_text(profile.sector) or "Unclassified"
    peers: list[PeerCompany] = []
    for ticker in candidate_tickers:
        try:
            peer = _build_peer_company(ticker, sector_tag)
            if peer is not None:
                peers.append(peer)
        except Exception as exc:
            methodology_notes.append(f"Skipped candidate {ticker} after metadata retrieval failure: {exc}")

    if not peers:
        methodology_notes.append("No candidate had usable financial data; valuation will proceed with an empty peer set.")
        return PeerDiscoveryResult(
            anchors=anchors,
            peers=[],
            methodology_notes=methodology_notes,
            candidate_universe_size=len(candidate_tickers),
        )

    description_scores = _description_similarity(profile, peers, website_context=website_context)
    for peer, description_score in zip(peers, description_scores):
        final_score, rationale = _candidate_breakdown(profile, peer, description_score)
        peer.similarity_score = round(final_score, 4)
        peer.ranking_rationale = rationale

    peers.sort(key=lambda peer: (-float(peer.similarity_score or 0.0), peer.ticker))
    selected = peers[: max(1, min(len(peers), 5))]
    methodology_notes.append(
        "Final peers selected by deterministic weighted score over industry, revenue, margin, geography, and description similarity."
    )
    methodology_notes.append(
        "Final peer ranking: " + ", ".join(f"{peer.ticker} ({peer.similarity_score:.4f})" for peer in selected)
    )

    return PeerDiscoveryResult(
        anchors=anchors,
        peers=selected,
        methodology_notes=methodology_notes,
        candidate_universe_size=len(candidate_tickers),
    )
