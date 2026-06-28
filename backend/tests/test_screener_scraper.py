"""Tests for the Screener.in scraper. No real browser is launched here (this
sandbox has no Chrome binary) — these tests cover the pure-Python label-text
parsing helpers directly, and confirm the public scrape_company() entry point
honors its fail-soft contract (never raises, always returns a result object)
even when a real browser genuinely cannot be started."""
from selenium.webdriver.common.by import By

from app.services.screener_scraper import (
    ScreenerPeerSetResult,
    ScreenerScrapeResult,
    _extract_financial_rows,
    _extract_growth_and_quality,
    _extract_peer_comparison,
    _extract_quick_ratios,
    _extract_row_value_in_range,
    _parse_number,
    scrape_company,
    scrape_peer_set,
)



class _StubElement:
    def __init__(self, text):
        self.text = text


class _StubDriver:
    """Minimal stand-in for a Selenium WebDriver — only implements what the
    label-text extraction helpers actually call."""

    def __init__(self, body_text):
        self._body_text = body_text

    def find_element(self, by, value):
        assert by == "tag name" and value == "body"
        return _StubElement(self._body_text)


class _NoSuchElement(Exception):
    pass


class _Node:
    """Generic stand-in for a Selenium WebElement (or the driver itself,
    which Selenium treats the same way for find_element/find_elements). A
    node's children are registered per (by, value) pair, mirroring how real
    Selenium queries are scoped — this lets the peer-comparison-table tests
    build a fake DOM (driver -> #peers section -> table -> th/tr/td) without
    needing a real browser, the same approach the existing _StubDriver above
    uses for the simpler body-text extractors."""

    def __init__(self, text="", attrs=None):
        self.text = text
        self._attrs = attrs or {}
        self._children = {}

    def add_children(self, by, value, nodes):
        self._children[(by, value)] = nodes if isinstance(nodes, list) else [nodes]

    def find_element(self, by, value):
        nodes = self._children.get((by, value))
        if not nodes:
            raise _NoSuchElement(f"no element registered for {by}={value!r}")
        return nodes[0]

    def find_elements(self, by, value):
        return self._children.get((by, value), [])

    def get_attribute(self, name):
        return self._attrs.get(name)


def _make_peer_table(headers, rows):
    """rows: list of row-lists; each cell is either a plain string or a
    (text, href) tuple when that cell should carry a link (the name column)."""
    table = _Node(text=" ".join(headers))
    table.add_children(By.TAG_NAME, "th", [_Node(text=h) for h in headers])

    tr_nodes = []
    for row in rows:
        td_nodes = []
        for cell in row:
            text, href = cell if isinstance(cell, tuple) else (cell, None)
            td = _Node(text=text)
            if href:
                td.add_children(By.TAG_NAME, "a", [_Node(text=text, attrs={"href": href})])
            td_nodes.append(td)
        tr = _Node()
        tr.add_children(By.TAG_NAME, "td", td_nodes)
        tr_nodes.append(tr)
    table.add_children(By.CSS_SELECTOR, "tbody tr", tr_nodes)
    return table


def _make_peers_driver(table):
    """A driver whose #peers section directly contains the table — the
    primary lookup path in _extract_peer_comparison."""
    driver = _Node()
    section = _Node()
    section.add_children(By.TAG_NAME, "table", [table])
    driver.add_children(By.ID, "peers", [section])
    return driver


def test_parse_number_handles_commas_and_units():
    assert _parse_number("1,234.56 Cr.") == 1234.56
    assert _parse_number("12.5%") == 12.5
    assert _parse_number("-3.2%") == -3.2
    assert _parse_number("no digits here") is None
    assert _parse_number("") is None


def test_extract_quick_ratios_reads_label_adjacent_values():
    body_text = "\n".join(
        [
            "Market Cap",
            "1,234 Cr.",
            "Current Price",
            "562.10",
            "Stock P/E",
            "18.45",
            "ROCE",
            "21.3 %",
            "ROE",
            "17.9 %",
        ]
    )
    driver = _StubDriver(body_text)
    found = _extract_quick_ratios(driver)

    assert found["market_cap_cr"] == 1234
    assert found["current_price"] == 562.10
    assert found["pe_ratio"] == 18.45
    assert found["roce_pct"] == 21.3
    assert found["roe_pct"] == 17.9


def test_extract_growth_and_quality_reads_compounded_growth_tables():
    """The mini-table lists 10/5/3-year buckets in that order, each as its
    own 'N Years:' label line followed by a value line. The 3-year figure is
    what we want (sales_growth_3y_pct) — this specifically guards against
    misreading the "10" in "10 Years:" as the growth percentage itself,
    which is a real bug the naive first-number-after-header approach hits."""
    body_text = "\n".join(
        [
            "Compounded Sales Growth",
            "10 Years:",
            "12%",
            "5 Years:",
            "14%",
            "3 Years:",
            "16%",
            "Compounded Profit Growth",
            "3 Years:",
            "9%",
            "Promoters",
            "55.20%",
            "OPM",
            "19.5%",
        ]
    )
    driver = _StubDriver(body_text)
    found = _extract_growth_and_quality(driver)

    assert found["sales_growth_3y_pct"] == 16
    assert found["profit_growth_3y_pct"] == 9
    assert found["promoter_holding_pct"] == 55.20
    assert found["opm_pct"] == 19.5


def test_extract_growth_and_quality_handles_inline_period_values():
    """Some layouts put the value on the same line as the period label
    ("3 Years: 16%") instead of the next line — both must work."""
    body_text = "\n".join(
        [
            "Compounded Sales Growth",
            "10 Years: 12%",
            "5 Years: 14%",
            "3 Years: 16%",
            "Compounded Profit Growth",
            "3 Years: 9%",
        ]
    )
    driver = _StubDriver(body_text)
    found = _extract_growth_and_quality(driver)

    assert found["sales_growth_3y_pct"] == 16
    assert found["profit_growth_3y_pct"] == 9


def test_scrape_company_empty_query_never_raises():
    result = scrape_company("")
    assert isinstance(result, ScreenerScrapeResult)
    assert result.success is False
    assert "No company name" in result.detail


def test_scrape_company_without_a_real_browser_fails_soft():
    """In this environment there is no Chrome binary, so this exercises the
    real _make_driver() failure path end-to-end and confirms scrape_company
    degrades to success=False with a human-readable detail instead of
    propagating an exception."""
    result = scrape_company("Some Test Company Ltd")
    assert isinstance(result, ScreenerScrapeResult)
    assert result.success is False
    assert result.detail


def test_extract_peer_comparison_reads_table_via_id_with_header_aliases():
    """Primary lookup path: a #peers section containing the table directly.
    Headers are matched by alias text, not column position, since
    screener.in lets users reorder peer-table columns."""
    headers = ["Name", "CMP", "P/E", "Mar Cap Rs.Cr.", "ROCE %"]
    rows = [
        [("Peer One Ltd", "https://www.screener.in/company/PEER1/"), "120.50", "15.2", "5,000", "18.5"],
        [("Peer Two Ltd", "https://www.screener.in/company/PEER2/"), "85.00", "22.1", "1,200", "12.3"],
    ]
    driver = _make_peers_driver(_make_peer_table(headers, rows))

    peers = _extract_peer_comparison(driver)

    assert len(peers) == 2
    assert peers[0]["name"] == "Peer One Ltd"
    assert peers[0]["screener_url"] == "https://www.screener.in/company/PEER1/"
    assert peers[0]["cmp"] == 120.50
    assert peers[0]["pe_ratio"] == 15.2
    assert peers[0]["market_cap_cr"] == 5000
    assert peers[0]["roce_pct"] == 18.5
    assert peers[1]["name"] == "Peer Two Ltd"
    assert peers[1]["market_cap_cr"] == 1200


def test_extract_peer_comparison_falls_back_to_heuristic_table_scan():
    """If there's no #peers element (page layout drifted), fall back to
    scanning every <table> on the page for one whose header text mentions
    both 'p/e' and 'roce'."""
    unrelated_table = _Node(text="Quarterly Results Sales OPM Net Profit")
    peer_table = _make_peer_table(
        ["Name", "P/E", "ROCE %"],
        [[("Peer Three Ltd", "https://www.screener.in/company/PEER3/"), "10.0", "20.0"]],
    )
    driver = _Node()  # no #peers child registered -> find_element(By.ID, "peers") raises
    driver.add_children(By.TAG_NAME, "table", [unrelated_table, peer_table])

    peers = _extract_peer_comparison(driver)

    assert len(peers) == 1
    assert peers[0]["name"] == "Peer Three Ltd"
    assert peers[0]["pe_ratio"] == 10.0
    assert peers[0]["roce_pct"] == 20.0


def test_extract_peer_comparison_returns_empty_when_no_table_found():
    driver = _Node()  # neither #peers nor any <table> registered
    assert _extract_peer_comparison(driver) == []


def test_extract_peer_comparison_returns_empty_when_table_has_no_name_column():
    """A table that happens to mention p/e and roce but has no identifiable
    name column isn't a usable peer-comparison table — must not be misread."""
    table = _make_peer_table(["P/E", "ROCE %"], [["10.0", "20.0"]])
    driver = _make_peers_driver(table)
    assert _extract_peer_comparison(driver) == []


def test_extract_row_value_in_range_returns_most_recent_year():
    lines = [
        "Sales",
        "120",
        "145",
        "162",
        "189",
        "210",
    ]
    assert _extract_row_value_in_range(lines, 0, len(lines), "Sales") == 210
    assert _extract_row_value_in_range(lines, 0, len(lines), "Nonexistent Row") is None


def test_extract_financial_rows_reads_sales_and_borrowings():
    body_text = "\n".join([
        "Profit & Loss",
        "Sales",
        "120",
        "145",
        "162",
        "OPM %",
        "12%",
        "15%",
        "Balance Sheet",
        "Borrowings",
        "40",
        "35",
        "30"
    ])
    driver = _StubDriver(body_text)
    found = _extract_financial_rows(driver)
    assert found["sales_cr"] == 162
    assert found["debt_cr"] == 30
    assert found["opm_pct"] == 15


def test_extract_financial_rows_handles_missing_rows_gracefully():
    driver = _StubDriver("Nothing relevant here")
    assert _extract_financial_rows(driver) == {}


def test_scrape_peer_set_empty_query_never_raises():
    result = scrape_peer_set("")
    assert isinstance(result, ScreenerPeerSetResult)
    assert result.success is False
    assert "No company name" in result.detail


def test_scrape_peer_set_without_a_real_browser_fails_soft():
    """Same fail-soft contract as scrape_company: no Chrome binary in this
    sandbox should degrade to success=False with a readable detail, never
    an exception."""
    result = scrape_peer_set("Some Test Company Ltd")
    assert isinstance(result, ScreenerPeerSetResult)
    assert result.success is False
    assert result.detail
