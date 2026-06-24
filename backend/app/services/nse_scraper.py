"""Live discovery of NSE SME/small-cap peer candidates by sector.

Primary path: scrape nseindia.com's unofficial JSON endpoints for the SME
Emerge list. nseindia.com runs Akamai Bot Manager, which blocks most non-browser
clients (confirmed: even with full browser headers, requests get an Akamai
challenge page, not data) — so this will commonly fail outside a real browser
session. When it does, we fall back to a small curated list of real NSE-listed
small-cap tickers per sector, each validated to return live data via yfinance.
The peer *list* is static in the fallback case; every financial figure for
those peers is still pulled live from yfinance at request time.
"""
import logging
from typing import NamedTuple

import requests

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/market-data/sme-emerge",
}


class PeerCandidate(NamedTuple):
    ticker: str
    sector_tag: str
    source: str  # "nse_live_scrape" | "fallback_seed_list"


# Curated NSE-listed small/mid-cap tickers, hand-picked as listed proxies per
# sector and individually validated against live yfinance data. Used only
# when the live NSE scrape is blocked.
_FALLBACK_SEED_LIST: dict[str, list[str]] = {
    "Textiles": [
        "SUTLEJTEX.NS", "NITINSPIN.NS", "KPRMILL.NS", "VTL.NS",
        "TRIDENT.NS", "RSWM.NS", "ALOKINDS.NS", "NAHARSPING.NS",
    ],
    "Pharma": [
        "AARTIDRUGS.NS", "NATCOPHARM.NS", "GRANULES.NS", "CAPLIPOINT.NS",
        "INDOCO.NS", "MARKSANS.NS",
    ],
    "Engineering": [
        "KIRLOSENG.NS", "ELGIEQUIP.NS", "GREAVESCOT.NS", "TITAGARH.NS", "JASH.NS",
    ],
    "FMCG": [
        "BAJAJCON.NS", "DODLA.NS", "VADILALIND.NS", "HATSUN.NS", "BIKAJI.NS",
    ],
    "Chemicals": [
        "AARTIIND.NS", "VINATIORGA.NS", "NOCIL.NS", "GUJALKALI.NS",
        "DEEPAKNTR.NS", "FINEORG.NS",
    ],
}


def _try_live_scrape(sector_tag: str) -> list[PeerCandidate] | None:
    """Attempt to pull the live SME Emerge list from nseindia.com. Returns None on any failure."""
    try:
        session = requests.Session()
        session.headers.update(_BROWSER_HEADERS)
        home = session.get("https://www.nseindia.com/market-data/sme-emerge", timeout=10)
        if home.status_code != 200:
            logger.warning("NSE live scrape blocked (status %s) — using fallback seed list", home.status_code)
            return None

        resp = session.get(
            "https://www.nseindia.com/api/equity-stockIndices",
            params={"index": "SME EMERGE"},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("NSE SME Emerge API blocked (status %s) — using fallback seed list", resp.status_code)
            return None

        data = resp.json()
        candidates = [
            PeerCandidate(ticker=f"{row['symbol']}.NS", sector_tag=sector_tag, source="nse_live_scrape")
            for row in data.get("data", [])
            if row.get("symbol")
        ]
        return candidates or None
    except Exception as exc:
        logger.warning("NSE live scrape failed (%s) — using fallback seed list", exc)
        return None


def get_peer_candidates(sector_tag: str) -> list[PeerCandidate]:
    """Returns peer candidate tickers for a sector — live scrape first, static fallback second."""
    live = _try_live_scrape(sector_tag)
    if live:
        return live

    tickers = _FALLBACK_SEED_LIST.get(sector_tag, [])
    return [PeerCandidate(ticker=t, sector_tag=sector_tag, source="fallback_seed_list") for t in tickers]


def available_sectors() -> list[str]:
    return list(_FALLBACK_SEED_LIST.keys())
