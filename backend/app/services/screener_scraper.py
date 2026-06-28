"""Headless Selenium scraping of screener.in: search box -> company page ->
structured ratio/financial extraction.

This is the only place in the codebase that drives a real browser. Every
public function here is synchronous (Selenium is blocking) and is called
directly from a sync LangGraph node — no asyncio wrapping needed in this
project's graph (see app.agents.graph, which is built with sync node
functions throughout).

Design contract, matching every other data-source module in this codebase
(nse_scraper.py, website_context.py, yfinance_service.py): this module never
raises. Any failure — no Chrome binary available, network block, search box
markup changed, company not listed on screener.in, page layout drifted —
results in a ScreenerScrapeResult with success=False and a human-readable
detail string, never an exception propagating to the caller. Screener.in's
own HTML structure is not a stable public API and can change without notice;
every selector below is intentionally written as "search visible text for a
known label, then read the adjacent number" rather than a brittle CSS class
name, specifically so small markup tweaks on their end don't break this.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from app.config import SCREENER_BASE_URL, SCREENER_SEARCH_TIMEOUT_SECONDS, SCREENER_USERNAME, SCREENER_PASSWORD

logger = logging.getLogger(__name__)

_session_cache = None

def _get_screener_session() -> requests.Session:
    global _session_cache
    if _session_cache is not None:
        return _session_cache
        
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    if not SCREENER_USERNAME or not SCREENER_PASSWORD:
        logger.debug("No Screener credentials configured; using anonymous session.")
        _session_cache = session
        return session
        
    try:
        login_url = urljoin(SCREENER_BASE_URL, "/login/")
        resp = session.get(login_url, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            csrf_input = soup.find('input', {'name': 'csrfmiddlewaretoken'})
            if csrf_input:
                csrf_token = csrf_input.get('value')
                login_data = {
                    'username': SCREENER_USERNAME,
                    'password': SCREENER_PASSWORD,
                    'csrfmiddlewaretoken': csrf_token
                }
                session.headers.update({
                    'Referer': login_url,
                    'X-CSRFToken': csrf_token
                })
                login_resp = session.post(login_url, data=login_data, timeout=15)
                if login_resp.status_code == 200 and any(c.name == 'sessionid' for c in session.cookies):
                    logger.info("Successfully logged into Screener.in as %s", SCREENER_USERNAME)
                else:
                    logger.warning("Screener.in login failed; falling back to anonymous session.")
            else:
                logger.warning("Screener.in CSRF token not found; falling back to anonymous session.")
        else:
            logger.warning("Could not load Screener.in login page; falling back to anonymous session.")
    except Exception as exc:
        logger.warning("Error during Screener.in login flow: %s; falling back to anonymous session.", exc)
        
    _session_cache = session
    return session


_NUMBER_RE = re.compile(r"-?[\d,]*\.?\d+")

# Each entry: (result dict key, list of label substrings to look for, % flag)
_RATIO_LABELS: list[tuple[str, list[str], bool]] = [
    ("market_cap_cr", ["market cap"], False),
    ("current_price", ["current price"], False),
    ("pe_ratio", ["stock p/e", "p/e"], False),
    ("book_value", ["book value"], False),
    ("dividend_yield_pct", ["dividend yield"], True),
    ("roce_pct", ["roce"], True),
    ("roe_pct", ["roe"], True),
    ("face_value", ["face value"], False),
    ("debt_cr", ["debt"], False),
]


def _parse_number(text: str) -> float | None:
    if not text:
        return None
    match = _NUMBER_RE.search(text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


@dataclass
class ScreenerScrapeResult:
    success: bool = False
    matched_company_name: str | None = None
    screener_url: str | None = None
    fields: dict = field(default_factory=dict)
    fields_found: list[str] = field(default_factory=list)
    detail: str = ""


def _make_driver():
    """Build a headless Chrome driver. Imports undetected_chromedriver lazily
    so environments without a Chrome binary (CI, plain unit-test runners,
    this sandbox) can still import this module without crashing at import
    time — only calling scrape_company() requires a real browser."""
    import os
    import undetected_chromedriver as uc

    opts = uc.ChromeOptions()
    binary_location = os.environ.get("CHROME_BINARY") or os.environ.get("CHROME_BIN")
    if binary_location:
        opts.binary_location = binary_location
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1366,900")
    return uc.Chrome(options=opts)


def _search_and_open_company_page(driver, query: str) -> tuple[str | None, str | None]:
    """Drives the screener.in homepage search box, returns
    (matched_company_name, company_page_url) or (None, None) if no usable
    match was found. Tries a couple of plausible search-box selectors and a
    couple of ways to read the autocomplete dropdown, since screener.in's
    exact markup is not a documented stable contract."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    wait = WebDriverWait(driver, SCREENER_SEARCH_TIMEOUT_SECONDS)
    driver.get(SCREENER_BASE_URL)

    search_box = None
    for by, selector in (
        (By.CSS_SELECTOR, "input#search"),
        (By.CSS_SELECTOR, "input.search-box"),
        (By.CSS_SELECTOR, "input[placeholder*='Search']"),
        (By.CSS_SELECTOR, "input[type='search']"),
        (By.CSS_SELECTOR, "input[type='text']"),
    ):
        try:
            search_box = wait.until(EC.presence_of_element_located((by, selector)))
            if search_box:
                break
        except Exception:
            continue

    if search_box is None:
        return None, None

    search_box.clear()
    search_box.send_keys(query)

    # Give the autocomplete dropdown time to populate, then look for the
    # first result link pointing at a /company/<id>/ page.
    result_link = None
    for by, selector in (
        (By.CSS_SELECTOR, "a[href*='/company/']"),
        (By.CSS_SELECTOR, "ul.dropdown-menu a"),
        (By.CSS_SELECTOR, "[role='listbox'] a"),
    ):
        try:
            result_link = wait.until(EC.presence_of_element_located((by, selector)))
            if result_link:
                break
        except Exception:
            continue

    if result_link is None:
        return None, None

    matched_name = (result_link.text or "").strip() or None
    href = result_link.get_attribute("href")
    if not href:
        return matched_name, None

    driver.get(href)
    return matched_name, href


def _extract_quick_ratios(driver) -> dict:
    """Reads the top-of-page 'quick ratios' box (Market Cap, P/E, ROCE, etc.)
    by scanning visible text for each known label and pulling the number
    that follows it — robust to class-name churn since it keys off label
    text, not CSS selectors."""
    found: dict = {}
    try:
        body_text = driver.find_element("tag name", "body").text
    except Exception:
        return found

    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    lower_lines = [line.lower() for line in lines]

    for key, labels, _is_pct in _RATIO_LABELS:
        for i, line in enumerate(lower_lines):
            if any(label in line for label in labels):
                # The value is often on the same line ("Market Cap 1,234 Cr.")
                # or the very next line, depending on layout.
                value = _parse_number(lines[i])
                if value is None and i + 1 < len(lines):
                    value = _parse_number(lines[i + 1])
                if value is not None:
                    found[key] = value
                break
    return found


def _extract_growth_and_quality(driver) -> dict:
    """Reads the 'Compounded Sales Growth' / 'Compounded Profit Growth'
    mini-tables and the shareholding pattern's Promoters row, all by
    text-label search for the same reason as _extract_quick_ratios.

    The growth mini-tables render as period labels like "10 Years:",
    "5 Years:", "3 Years:" each followed by a percentage — either inline
    ("3 Years: 16%") or on the next line. We specifically target the
    3-year figure rather than "the first number after the section header",
    because the header is immediately followed by a "10 Years:" line whose
    own label text ("10") would otherwise be misread as the growth value.
    """
    found: dict = {}
    try:
        body_text = driver.find_element("tag name", "body").text
    except Exception:
        return found

    lines = [line.strip() for line in body_text.splitlines() if line.strip()]

    def _value_near(label_substr: str, window: int = 4) -> float | None:
        for i, line in enumerate(lines):
            if re.search(rf"\b{re.escape(label_substr.lower())}\b", line.lower()):
                for j in range(i, min(i + window, len(lines))):
                    value = _parse_number(lines[j])
                    if value is not None and lines[j].strip() not in ("3", "5", "10"):
                        return value
        return None

    def _growth_value_for_period(header_substr: str, period_substr: str = "3 year", window: int = 8) -> float | None:
        header_idx = None
        for i, line in enumerate(lines):
            if header_substr in line.lower():
                header_idx = i
                break
        if header_idx is None:
            return None

        section = lines[header_idx: header_idx + window]
        for i, line in enumerate(section):
            low = line.lower()
            if period_substr not in low:
                continue
            # Value may be inline ("3 Years: 16%") ...
            tail = low.split(period_substr, 1)[1]
            inline_value = _parse_number(tail)
            if inline_value is not None:
                return inline_value
            # ... or on one of the next couple of lines.
            for j in range(i + 1, min(i + 3, len(section))):
                value = _parse_number(section[j])
                if value is not None:
                    return value
        return None

    sales_growth = _growth_value_for_period("compounded sales growth", "3 year")
    profit_growth = _growth_value_for_period("compounded profit growth", "3 year")
    promoter_holding = _value_near("promoters")
    opm = _value_near("opm")

    if sales_growth is not None:
        found["sales_growth_3y_pct"] = sales_growth
    if profit_growth is not None:
        found["profit_growth_3y_pct"] = profit_growth
    if promoter_holding is not None:
        found["promoter_holding_pct"] = promoter_holding
    if opm is not None:
        found["opm_pct"] = opm

    return found


def _search_company_via_api(query: str) -> tuple[str | None, str] | None:
    try:
        api_url = urljoin(SCREENER_BASE_URL, f"/api/company/search/?q={quote_plus(query)}")
        session = _get_screener_session()
        response = session.get(api_url, timeout=15)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list) or not data:
            return None
        first = data[0]
        matched_name = (first.get("name") or "").strip() or None
        relative_url = first.get("url")
        if not relative_url:
            return None
        return matched_name, urljoin(SCREENER_BASE_URL, relative_url)
    except Exception as exc:
        logger.debug("Screener.in API search failed for %s: %s", query, exc)
        return None


def _fetch_screener_page_text(url: str) -> str | None:
    try:
        session = _get_screener_session()
        response = session.get(url, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        return soup.get_text(separator="\n")
    except Exception as exc:
        logger.warning("Failed to fetch Screener.in page %s: %s", url, exc)
        return None


def _scrape_company_page_by_url(url: str, matched_name: str | None) -> ScreenerScrapeResult:
    consolidated_url = url
    if not url.rstrip("/").endswith("/consolidated"):
        consolidated_url = urljoin(url, "consolidated/")
    page_text = _fetch_screener_page_text(consolidated_url)
    used_url = consolidated_url
    if not page_text:
        page_text = _fetch_screener_page_text(url)
        used_url = url

    if not page_text:
        return ScreenerScrapeResult(
            success=False,
            matched_company_name=matched_name,
            screener_url=url,
            detail=f"Failed to load Screener.in page at {url}.",
        )

    fields: dict = {}
    fields.update(_extract_quick_ratios_from_text(page_text))
    fields.update(_extract_growth_and_quality_from_text(page_text))

    if not fields:
        return ScreenerScrapeResult(
            success=False,
            matched_company_name=matched_name,
            screener_url=url,
            detail=(
                "Matched a Screener.in page but could not extract any ratio fields from it "
                "(page layout may have changed)."
            ),
        )

    return ScreenerScrapeResult(
        success=True,
        matched_company_name=matched_name,
        screener_url=url,
        fields=fields,
        fields_found=sorted(fields.keys()),
        detail=f"Matched '{matched_name or url}' on Screener.in and extracted {len(fields)} field(s).",
    )


def _extract_quick_ratios_from_text(body_text: str) -> dict:
    class _TextDriver:
        def __init__(self, text: str):
            self._text = text

        def find_element(self, by, value):
            if by == "tag name" and value == "body":
                return type("_StubElement", (), {"text": self._text})()
            raise ValueError(f"Unsupported selector: {by}={value}")

    return _extract_quick_ratios(_TextDriver(body_text))


def _extract_growth_and_quality_from_text(body_text: str) -> dict:
    class _TextDriver:
        def __init__(self, text: str):
            self._text = text

        def find_element(self, by, value):
            if by == "tag name" and value == "body":
                return type("_StubElement", (), {"text": self._text})()
            raise ValueError(f"Unsupported selector: {by}={value}")

    return _extract_growth_and_quality(_TextDriver(body_text))


def _extract_peer_rows_from_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table[data-page-results], table")
    if table is None:
        return []

    header_cells = table.select("thead th") or table.select("th")
    headers = [cell.get_text(strip=True).lower() for cell in header_cells]
    column_for_index: dict[int, str] = {}
    for idx, header in enumerate(headers):
        for key, aliases in _PEER_TABLE_COLUMN_ALIASES.items():
            if any(alias in header for alias in aliases):
                column_for_index[idx] = key
                break

    if "name" not in column_for_index.values():
        return []

    rows = []
    body_rows = table.select("tbody tr") or table.select("tr")[1:]
    for row in body_rows:
        cells = row.select("td")
        if not cells:
            continue
        record: dict = {}
        for idx, cell in enumerate(cells):
            key = column_for_index.get(idx)
            if not key:
                continue
            if key == "name":
                record["name"] = cell.get_text(strip=True)
                link = cell.select_one("a[href]")
                if link and link["href"]:
                    record["screener_url"] = urljoin(SCREENER_BASE_URL, link["href"])
            else:
                value = _parse_number(cell.get_text())
                if value is not None:
                    record[key] = value
        if record.get("name"):
            rows.append(record)
    return rows


def _get_section_ranges(lines: list[str]) -> tuple[int, int, int]:
    """Returns (profit_loss_start, balance_sheet_start, document_end) indices."""
    pl_idx = len(lines)
    bs_idx = len(lines)
    # Real pages are long (>150 lines); skip menu links in the first 100 lines.
    # Small pages are test mocks; do not skip anything.
    skip_limit = 100 if len(lines) > 150 else 0
    for i, line in enumerate(lines):
        if i < skip_limit:
            continue
        line_lower = line.lower()
        if "profit & loss" in line_lower:
            pl_idx = min(pl_idx, i)
        elif "balance sheet" in line_lower:
            bs_idx = min(bs_idx, i)
    return pl_idx, bs_idx, len(lines)


def _extract_row_value_in_range(lines: list[str], start: int, end: int, label: str) -> float | None:
    for i in range(start, end):
        if lines[i].strip().lower() == label.lower():
            values: list[float] = []
            for j in range(i + 1, min(i + 15, end)):
                val_str = lines[j].strip()
                if val_str in ("+", ""):
                    continue
                val = _parse_number(val_str)
                if val is None:
                    if val_str == "%":
                        continue
                    break
                values.append(val)
            if values:
                return values[-1]
    return None


def _extract_financial_rows_from_text(body_text: str) -> dict:
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    pl_start, bs_start, doc_end = _get_section_ranges(lines)
    
    sales = _extract_row_value_in_range(lines, pl_start, bs_start, "Sales")
    opm = _extract_row_value_in_range(lines, pl_start, bs_start, "OPM %")
    borrowings = _extract_row_value_in_range(lines, bs_start, doc_end, "Borrowings")
    
    found: dict = {}
    if sales is not None:
        found["sales_cr"] = sales
    if borrowings is not None:
        found["debt_cr"] = borrowings
    if opm is not None:
        found["opm_pct"] = opm
    return found

_PEER_TABLE_COLUMN_ALIASES: dict[str, list[str]] = {
    "name": ["name"],
    "cmp": ["cmp", "current price"],
    "pe_ratio": ["p/e"],
    "market_cap_cr": ["mar cap", "market cap"],
    "dividend_yield_pct": ["div yld"],
    "net_profit_qtr_cr": ["np qtr"],
    "profit_growth_qtr_pct": ["qtr profit var"],
    "sales_qtr_cr": ["sales qtr"],
    "sales_growth_qtr_pct": ["qtr sales var"],
    "roce_pct": ["roce"],
    "ev_ebitda": ["ev / ebitda", "ev/ebitda"],
    "sales_cr": ["salesrs.cr.", "sales rs.", "sales cr.", "annual sales"],
    "enterprise_value_cr": ["evrs.cr.", "ev rs.", "ev cr.", "enterprise value"],
    "debt_cr": ["debtrs.cr.", "debt cr.", "borrowings"],
    "roe_pct": ["roe"],
}


def _extract_peer_comparison(driver) -> list[dict]:
    """Reads the company page's own "Peer Comparison" table — the same
    sector/industry peer set screener.in's own algorithm already computed
    for this company — and returns one dict per peer row (name,
    screener_url, plus whatever ratio columns that table happens to show).
    Column order on screener.in isn't a documented contract, so headers are
    matched by text rather than assumed by position, the same philosophy as
    every other extractor in this module."""
    from selenium.webdriver.common.by import By

    table = None
    try:
        section = driver.find_element(By.ID, "peers")
        table = section.find_element(By.TAG_NAME, "table")
    except Exception:
        try:
            for candidate in driver.find_elements(By.TAG_NAME, "table"):
                header_text = (candidate.text or "")[:200].lower()
                if "p/e" in header_text and "roce" in header_text:
                    table = candidate
                    break
        except Exception:
            table = None

    if table is None:
        return []

    try:
        header_cells = table.find_elements(By.TAG_NAME, "th")
        headers = [cell.text.strip().lower() for cell in header_cells]
    except Exception:
        return []

    column_for_index: dict[int, str] = {}
    for idx, header in enumerate(headers):
        for key, aliases in _PEER_TABLE_COLUMN_ALIASES.items():
            if any(alias in header for alias in aliases):
                column_for_index[idx] = key
                break

    if "name" not in column_for_index.values():
        return []

    try:
        body_rows = table.find_elements(By.CSS_SELECTOR, "tbody tr")
        if not body_rows:
            body_rows = table.find_elements(By.TAG_NAME, "tr")[1:]
    except Exception:
        return []

    peers: list[dict] = []
    for row in body_rows:
        try:
            cells = row.find_elements(By.TAG_NAME, "td")
        except Exception:
            continue
        if not cells:
            continue
        record: dict = {}
        for idx, cell in enumerate(cells):
            key = column_for_index.get(idx)
            if not key:
                continue
            if key == "name":
                record["name"] = (cell.text or "").strip()
                try:
                    link = cell.find_element(By.TAG_NAME, "a")
                    href = link.get_attribute("href")
                    if href:
                        record["screener_url"] = href
                except Exception:
                    pass
            else:
                value = _parse_number(cell.text)
                if value is not None:
                    record[key] = value
        if record.get("name"):
            peers.append(record)
    return peers


def _extract_financial_rows(driver) -> dict:
    """Reads the latest-year "Sales" and "Borrowings" rows from the annual
    Profit & Loss / Balance Sheet tables, used together with OPM% (from
    _extract_growth_and_quality) to derive a peer's own EV/EBITDA and
    EV/Revenue multiples purely from screener.in data."""
    found: dict = {}
    try:
        body_text = driver.find_element("tag name", "body").text
    except Exception:
        return found
    return _extract_financial_rows_from_text(body_text)


@dataclass
class ScreenerPeerSetResult:
    success: bool = False
    target_matched_name: str | None = None
    target_url: str | None = None
    peers: list[dict] = field(default_factory=list)
    detail: str = ""


def scrape_peer_set(
    query: str, 
    target_revenue_cr: float | None = None,
    target_opm_pct: float | None = None,
    target_growth_pct: float | None = None,
    max_peers: int = 6
) -> ScreenerPeerSetResult:
    """Scrapes the target company's own "Peer Comparison" table on
    screener.in — the same sector/industry peer set screener.in itself
    computes — then visits each peer's own page to pull sales, OPM%, and
    borrowings so EV/EBITDA and EV/Revenue can be derived purely from
    screener.in data. No LLM suggestion and no yfinance call is involved in
    this path. Always returns a result object; never raises. A peer that
    can't be fully enriched is still returned with whatever the comparison
    table itself had (market cap, P/E, ROCE) — compute_valuation already
    skips peers missing ev_ebitda/ev_revenue, so partial data degrades
    gracefully rather than failing the whole run."""
    query = (query or "").strip()
    if not query:
        return ScreenerPeerSetResult(success=False, detail="No company name provided to search for.")

    driver = None
    search_result = _search_company_via_api(query)
    if search_result is None:
        return ScreenerPeerSetResult(
            success=False,
            detail=f"No Screener.in company page could be matched for '{query}' via API search.",
        )

    matched_name, url = search_result
    
    # Try to fetch the main page HTML to extract the dynamic numeric Warehouse ID and Industry Link
    warehouse_id = None
    industry_link = None
    try:
        session = _get_screener_session()
        page_resp = session.get(url, timeout=20)
        page_resp.raise_for_status()
        
        soup = BeautifulSoup(page_resp.text, 'html.parser')
        
        # Look for the Industry link (new format: /market/...)
        for a in soup.find_all('a', href=True):
            if a.get('title') == 'Industry' and '/market/' in a['href']:
                industry_link = urljoin(SCREENER_BASE_URL, a['href'])
                break
                
        import re
        export_match = re.search(r'/user/company/export/(\d+)/', page_resp.text)
        if export_match:
            warehouse_id = export_match.group(1)
    except Exception as exc:
        logger.warning("Failed to fetch main page to resolve warehouse ID for %s: %s", query, exc)

    company_id = warehouse_id
    if not company_id and "/company/" in url:
        company_id = url.rstrip("/").split("/company/")[-1].split("/")[0]

    peer_rows = []
    if industry_link:
        try:
            session = _get_screener_session()
            for page_num in range(1, 6): # Up to 5 pages (250 companies)
                page_url = f"{industry_link}?page={page_num}" if page_num > 1 else industry_link
                response = session.get(page_url, timeout=20)
                response.raise_for_status()
                
                ind_soup = BeautifulSoup(response.text, 'html.parser')
                table = ind_soup.find("table")
                if not table:
                    break
                    
                page_rows = _extract_peer_rows_from_html(str(table))
                if not page_rows:
                    break
                peer_rows.extend(page_rows)
                
                has_next = any(f"?page={page_num + 1}" in a.get("href", "") for a in ind_soup.find_all("a", href=True))
                if not has_next:
                    break
        except Exception as exc:
            logger.warning("Failed to load Screener.in industry pages for %s: %s", query, exc)
            
    if not peer_rows and company_id:
        try:
            session = _get_screener_session()
            peers_url = urljoin(SCREENER_BASE_URL, f"/api/company/{company_id}/peers/")
            response = session.get(peers_url, timeout=20)
            response.raise_for_status()
            peer_rows = _extract_peer_rows_from_html(response.text)
        except Exception as exc:
            logger.warning("Failed to load Screener.in peer table for %s: %s", query, exc)

    if not peer_rows:
        return ScreenerPeerSetResult(
            success=False,
            target_matched_name=matched_name,
            target_url=url,
            detail=(
                f"Matched a Screener.in page for '{query}', but could not load its peer-comparison table "
                "for parsing."
            ),
        )

    # Filter out the target company itself from the peers list
    peer_rows = [r for r in peer_rows if r.get("screener_url", "").strip("/").lower() != url.strip("/").lower()]

    if target_revenue_cr is not None and target_revenue_cr > 0:
        def calculate_distance(r):
            # Size difference (weight 0.5)
            peer_sales = r.get("sales_cr") or r.get("sales_qtr_cr") or 0.0
            sales_dist = min(abs(peer_sales - target_revenue_cr) / target_revenue_cr, 5.0)
            
            # Margin difference (weight 0.3)
            peer_margin = r.get("opm_pct") or 0.0
            margin_target = target_opm_pct or 0.0
            margin_dist = min(abs(peer_margin - margin_target) / max(margin_target, 1.0), 2.0) if margin_target else 0.0
            
            # Growth difference (weight 0.2)
            peer_growth = r.get("profit_growth_3y_pct") or r.get("sales_growth_3y_pct") or 0.0
            growth_target = target_growth_pct or 0.0
            growth_dist = min(abs(peer_growth - growth_target) / max(growth_target, 1.0), 2.0) if growth_target else 0.0
            
            score = (0.5 * sales_dist) + (0.3 * margin_dist) + (0.2 * growth_dist)
            # Stash the score on the record so peer_discovery can surface it
            r["distance_score"] = score
            return score
            
        peer_rows.sort(key=calculate_distance)
    else:
        peer_rows.sort(key=lambda r: r.get("market_cap_cr") or 0.0, reverse=True)

    selected_rows = peer_rows[:max_peers]

    enriched: list[dict] = []
    for row in selected_rows:
        record = dict(row)
        # Skip fetching background page if custom columns are already populated (e.g. when logged in)
        has_custom = record.get("ev_ebitda") is not None and record.get("sales_cr") is not None
        if not has_custom:
            peer_url = row.get("screener_url")
            if peer_url:
                consolidated_url = peer_url
                if not peer_url.rstrip("/").endswith("/consolidated"):
                    consolidated_url = urljoin(peer_url, "consolidated/")
                page_text = _fetch_screener_page_text(consolidated_url)
                if not page_text:
                    page_text = _fetch_screener_page_text(peer_url)
                if page_text:
                    record.update(_extract_quick_ratios_from_text(page_text))
                    record.update(_extract_growth_and_quality_from_text(page_text))
                    record.update(_extract_financial_rows_from_text(page_text))
        enriched.append(record)


    n_enriched = sum(1 for r in enriched if r.get("sales_cr") is not None)
    return ScreenerPeerSetResult(
        success=True,
        target_matched_name=matched_name,
        target_url=url,
        peers=enriched,
        detail=(
            f"Read {len(peer_rows)} row(s) from '{matched_name or query}'s Screener.in peer-comparison "
            f"table; visited {len(selected_rows)} peer page(s) and fully enriched {n_enriched} of them "
            "with sales/OPM/borrowings data."
        ),
    )


def scrape_company(query: str) -> ScreenerScrapeResult:
    """Search screener.in for `query` and collect ratio/financial fields.

    This function prefers a fast JSON search API path for the search step,
    then falls back to browser automation only for page-content scraping when
    necessary. The result object is always returned; the method never raises.
    """
    query = (query or "").strip()
    if not query:
        return ScreenerScrapeResult(success=False, detail="No company name provided to search for.")

    search_result = _search_company_via_api(query)
    if search_result is None:
        # Browser path only if the API search isn't available or fails.
        driver = None
        try:
            driver = _make_driver()
        except Exception as exc:
            logger.warning("Could not start headless Chrome for Screener.in scrape: %s", exc)
            return ScreenerScrapeResult(
                success=False,
                detail=f"Headless browser unavailable in this environment ({exc}); Screener.in data skipped.",
            )

        try:
            matched_name, url = _search_and_open_company_page(driver, query)
        except Exception as exc:
            logger.warning("Screener.in browser search failed for %s: %s", query, exc)
            return ScreenerScrapeResult(success=False, detail=f"Browser search failed: {exc}")

        finally:
            try:
                if driver is not None:
                    driver.quit()
            except Exception:
                pass

        if not url:
            return ScreenerScrapeResult(
                success=False,
                matched_company_name=matched_name,
                detail=f"No Screener.in company page could be matched for '{query}'.",
            )
    else:
        matched_name, url = search_result

    return _scrape_company_page_by_url(url, matched_name)
