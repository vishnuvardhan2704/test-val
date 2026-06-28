"""Deterministic peer discovery built from Screener.in's peer-comparison tables.
"""
from __future__ import annotations

import logging
import re

from app.models import CompanyProfile, PeerCompany
from app.services import screener_scraper

logger = logging.getLogger(__name__)


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def _ticker_from_screener_record(record: dict) -> str:
    """screener.in peer rows don't carry an exchange ticker — derive a
    short, stable label from the company's screener.in URL so PeerCompany.ticker 
    always has *something* displayable, falling back to a slug of the company name."""
    url = record.get("screener_url") or ""
    match = re.search(r"/company/([A-Za-z0-9]+)/?", url)
    if match:
        return match.group(1).upper()
    name = record.get("name") or "PEER"
    slug = re.sub(r"[^A-Z0-9]", "", name.upper())
    return slug[:12] or "PEER"


def discover_peers(
    profile: CompanyProfile, max_peers: int = 6
) -> tuple[list[PeerCompany], str]:
    """Builds the peer set directly from screener.in's own "Peer Comparison"
    table on the target company's page. Each peer's EV/EBITDA and EV/Revenue multiple 
    is derived purely from screener.in-scraped figures.

    Returns (peers, detail_message).
    """
    sector_tag = profile.nse_sector_tag or _clean_text(profile.sector) or "Unclassified"
    query = _clean_text(profile.company_name)
    if not query:
        return [], "No company name available to look up a Screener.in peer-comparison table."

    target_opm = profile.ebitda_margin * 100.0 if profile.ebitda_margin else None
    result = screener_scraper.scrape_peer_set(
        query, 
        target_revenue_cr=profile.revenue_cr, 
        target_opm_pct=target_opm,
        target_growth_pct=profile.revenue_growth_pct,
        max_peers=max_peers
    )
    if not result.success or not result.peers:
        return [], result.detail

    peers: list[PeerCompany] = []
    for record in result.peers:
        market_cap = record.get("market_cap_cr")
        debt = record.get("debt_cr")
        sales = record.get("sales_cr")
        opm_pct = record.get("opm_pct")
        pe = record.get("pe_ratio")
        
        net_profit = None
        if pe and market_cap and pe > 0:
            net_profit = round(market_cap / pe, 2)

        ev_ebitda = record.get("ev_ebitda")
        ev_revenue = record.get("ev_revenue")

        enterprise_value = record.get("enterprise_value_cr")
        if enterprise_value is None and market_cap is not None:
            enterprise_value = market_cap + (debt or 0.0)

        ebitda_margin = (opm_pct / 100.0) if opm_pct is not None else None
        if ebitda_margin is None and ev_ebitda and ev_ebitda > 0 and enterprise_value and sales and sales > 0:
            ebitda_cr = enterprise_value / ev_ebitda
            ebitda_margin = ebitda_cr / sales
            opm_pct = ebitda_margin * 100.0

        if ev_revenue is None and enterprise_value is not None and sales and sales > 0:
            ev_revenue = round(enterprise_value / sales, 4)

        if ev_ebitda is None and enterprise_value is not None and sales and sales > 0:
            if ebitda_margin and ebitda_margin > 0:
                ebitda_cr = sales * ebitda_margin
                if ebitda_cr > 0:
                    ev_ebitda = round(enterprise_value / ebitda_cr, 4)

        peers.append(
            PeerCompany(
                ticker=_ticker_from_screener_record(record),
                name=record.get("name") or "Unknown",
                sector_tag=sector_tag,
                sector=profile.sector,
                revenue_cr=sales,
                net_profit_cr=net_profit,
                ev_ebitda=ev_ebitda,
                ev_revenue=ev_revenue,
                ebitda_margin=round(ebitda_margin, 4) if ebitda_margin is not None else None,
                market_cap_cr=market_cap,
                enterprise_value_cr=round(enterprise_value, 2) if enterprise_value is not None else None,
                pe_ratio=pe,
                roce_pct=record.get("roce_pct"),
                debt_cr=debt,
                source="screener.in",
                source_url=record.get("screener_url"),
                similarity_score=record.get("distance_score"),
                ranking_rationale="Selected via Smart Discovery (Multi-Factor Distance Score).",
            )
        )

    usable = [p for p in peers if p.ev_ebitda is not None or p.ev_revenue is not None]
    detail = (
        f"Scraped {len(peers)} peer(s) from Screener.in's peer-comparison table for '{query}'; "
        f"{len(usable)} had enough data (sales + OPM%/borrowings) to derive an EV/EBITDA or EV/Revenue multiple."
    )
    return peers, detail
