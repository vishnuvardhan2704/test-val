import os
from dotenv import load_dotenv

load_dotenv()

# curl_cffi's bundled CA store isn't trusted on this network (TLS-inspecting
# proxy); force yfinance onto the plain `requests` backend, which respects
# the OS certificate store via pip-system-certs.
os.environ.setdefault("YF_DISABLE_CURL_CFFI", "1")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# ── Valuation methodology constants ─────────────────────────────────────────
# Base illiquidity/private-company discount, tiered by revenue band. Replaces
# the old flat 25% constant. Smaller, less-established companies trade at a
# steeper discount to listed peers than larger, more mature ones.
BASE_DISCOUNT_BY_REVENUE_BAND = {
    "under_10cr": 0.30,
    "10_50cr": 0.25,
    "over_50cr": 0.20,
}

# Bounds the final discount can land in after every adjustment is applied —
# keeps a string of small adjustments from producing an implausible number.
MIN_FINAL_DISCOUNT = 0.15
MAX_FINAL_DISCOUNT = 0.45

# Weights used to blend valuation methods into one headline number, applied
# only to methods that were actually computable for a given company (weights
# are renormalized over whatever subset is applicable — see valuation.py).
METHOD_WEIGHTS = {
    "EV/EBITDA": 0.35,
    "P/E": 0.25,
    "EV/Revenue": 0.15,
    "DCF": 0.25,
}

# DCF assumptions. This is a simplified 5-year DCF, not a full
# institutional-grade model — every input is disclosed in methodology_notes.
DCF_PROJECTION_YEARS = 5
DCF_TERMINAL_GROWTH_RATE = 0.04  # long-run nominal growth assumption (India GDP-proxy)
DCF_RISK_FREE_RATE = 0.072  # approx. 10-year Indian G-Sec yield
DCF_EQUITY_RISK_PREMIUM = 0.06  # broad Indian equity market risk premium
DCF_SIZE_PREMIUM_SMALL_CAP = 0.04  # extra discount-rate premium for unlisted MSME-scale companies
DCF_DEFAULT_GROWTH_PCT = 0.08  # used only when no growth figure is available from any source, and flagged as such

PRIVATE_COMPANY_DISCOUNT = 0.25  # deprecated constant, kept only so any stray import doesn't crash; see BASE_DISCOUNT_BY_REVENUE_BAND
TOP_N_PEERS = 5

# ── Screener.in scraping ─────────────────────────────────────────────────────
SCREENER_BASE_URL = "https://www.screener.in"
SCREENER_SEARCH_TIMEOUT_SECONDS = 20
SCREENER_USERNAME = os.environ.get("SCREENER_USERNAME", "")
SCREENER_PASSWORD = os.environ.get("SCREENER_PASSWORD", "")

