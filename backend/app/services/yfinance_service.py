"""Live financials pull for a single NSE-listed ticker via yfinance.

Network call only — no LLM involvement. Returns None fields rather than
raising when Yahoo doesn't have a particular metric, so callers can decide
how to handle partial data.
"""
import logging
import time
from typing import Optional

from app import config  # noqa: F401  (sets YF_DISABLE_CURL_CFFI before yfinance import)
import yfinance as yf

logger = logging.getLogger(__name__)

CR_PER_RUPEE = 1 / 1e7  # 1 crore = 1e7 rupees


class PeerFinancials:
    def __init__(self, info: dict):
        self.sector = info.get("sector")
        self.sector_key = info.get("sectorKey")
        self.industry = info.get("industry")
        self.industry_key = info.get("industryKey")
        self.country = info.get("country")
        self.revenue_growth = info.get("revenueGrowth")
        self.enterprise_value_cr = _to_cr(info.get("enterpriseValue"))
        self.full_time_employees = info.get("fullTimeEmployees")
        self.long_business_summary = info.get("longBusinessSummary")
        self.market_cap_cr = _to_cr(info.get("marketCap"))
        self.revenue_cr = _to_cr(info.get("totalRevenue"))
        self.ev_ebitda = info.get("enterpriseToEbitda")
        self.ev_revenue = info.get("enterpriseToRevenue")
        self.ebitda_margin = info.get("ebitdaMargins")
        self.name = info.get("shortName") or info.get("longName")


def _to_cr(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value * CR_PER_RUPEE, 2)


def fetch_financials(ticker: str, retries: int = 2, delay_seconds: float = 1.5) -> Optional[PeerFinancials]:
    """Fetch live financials for one NSE ticker (e.g. 'TCS.NS'). Returns None on failure."""
    last_error = None
    for attempt in range(retries + 1):
        try:
            info = yf.Ticker(ticker).info
            if not info or info.get("regularMarketPrice") is None and info.get("marketCap") is None:
                raise ValueError("empty/invalid info payload")
            return PeerFinancials(info)
        except Exception as exc:  # yfinance raises a variety of exception types
            last_error = exc
            if attempt < retries:
                time.sleep(delay_seconds)
    logger.warning("yfinance fetch failed for %s after %d attempts: %s", ticker, retries + 1, last_error)
    return None
