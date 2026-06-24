from app.models import AnchorCompany, CompanyProfile, PeerCompany
from app.services import peer_discovery


class _FakeTicker:
    def __init__(self, info):
        self.info = info


class _FakeSearchResult:
    def __init__(self, quotes):
        self.quotes = quotes


class _FakeSector:
    def __init__(self, key):
        self.key = key
        self.top_companies = [{"symbol": "SECT1"}, {"symbol": "SECT2"}]


class _FakeIndustry:
    def __init__(self, key):
        self.key = key
        self.top_companies = [{"symbol": "IND1"}]
        self.top_growth_companies = [{"symbol": "IND2"}]
        self.top_performing_companies = [{"symbol": "IND3"}]


def _fake_financials(ticker: str):
    mapping = {
        "ANCHOR1": {"shortName": "Anchor One", "longBusinessSummary": "Anchor One summary", "marketCap": 2000000000, "totalRevenue": 500000000, "enterpriseToEbitda": 12.0, "enterpriseToRevenue": 2.0, "ebitdaMargins": 0.2, "sector": "Industrials", "industry": "Specialty Chemicals", "country": "India", "enterpriseValue": 2200000000, "revenueGrowth": 0.11, "fullTimeEmployees": 5000, "sectorKey": "industrials", "industryKey": "specialty-chemicals"},
        "SECT1": {"shortName": "Sector One", "longBusinessSummary": "Sector one summary", "marketCap": 1500000000, "totalRevenue": 450000000, "enterpriseToEbitda": 11.0, "enterpriseToRevenue": 1.9, "ebitdaMargins": 0.18, "sector": "Industrials", "industry": "Specialty Chemicals", "country": "India", "enterpriseValue": 1700000000, "revenueGrowth": 0.09, "fullTimeEmployees": 3200, "sectorKey": "industrials", "industryKey": "specialty-chemicals"},
        "SECT2": {"shortName": "Sector Two", "longBusinessSummary": "Sector two summary", "marketCap": 500000000, "totalRevenue": 100000000, "enterpriseToEbitda": 4.0, "enterpriseToRevenue": 0.8, "ebitdaMargins": 0.08, "sector": "Consumer Staples", "industry": "Food Products", "country": "United States", "enterpriseValue": 600000000, "revenueGrowth": 0.03, "fullTimeEmployees": 800, "sectorKey": "consumer-staples", "industryKey": "food-products"},
        "IND1": {"shortName": "Industry One", "longBusinessSummary": "Industry one summary", "marketCap": 1800000000, "totalRevenue": 550000000, "enterpriseToEbitda": 10.0, "enterpriseToRevenue": 1.7, "ebitdaMargins": 0.19, "sector": "Industrials", "industry": "Specialty Chemicals", "country": "India", "enterpriseValue": 1900000000, "revenueGrowth": 0.12, "fullTimeEmployees": 4100, "sectorKey": "industrials", "industryKey": "specialty-chemicals"},
        "IND2": {"shortName": "Industry Two", "longBusinessSummary": "Industry two summary", "marketCap": 1600000000, "totalRevenue": 530000000, "enterpriseToEbitda": 9.5, "enterpriseToRevenue": 1.6, "ebitdaMargins": 0.17, "sector": "Industrials", "industry": "Specialty Chemicals", "country": "India", "enterpriseValue": 1750000000, "revenueGrowth": 0.1, "fullTimeEmployees": 3800, "sectorKey": "industrials", "industryKey": "specialty-chemicals"},
        "IND3": {"shortName": "Industry Three", "longBusinessSummary": "Industry three summary", "marketCap": 1400000000, "totalRevenue": 520000000, "enterpriseToEbitda": 8.0, "enterpriseToRevenue": 1.4, "ebitdaMargins": 0.16, "sector": "Industrials", "industry": "Specialty Chemicals", "country": "India", "enterpriseValue": 1500000000, "revenueGrowth": 0.08, "fullTimeEmployees": 3500, "sectorKey": "industrials", "industryKey": "specialty-chemicals"},
    }
    return peer_discovery.yfinance_service.PeerFinancials(mapping[ticker])


def test_anchor_generation_and_candidate_expansion(monkeypatch):
    monkeypatch.setattr(peer_discovery, "generate_json", lambda prompt: {"anchors": [{"name": "Anchor One", "ticker": "ANCHOR1", "rationale": "closest public peer"}]})
    monkeypatch.setattr(peer_discovery.yf, "Ticker", lambda ticker: _FakeTicker({"sectorKey": "industrials", "industryKey": "specialty-chemicals"}))
    monkeypatch.setattr(peer_discovery.yf, "Sector", lambda key: _FakeSector(key))
    monkeypatch.setattr(peer_discovery.yf, "Industry", lambda key: _FakeIndustry(key))
    monkeypatch.setattr(peer_discovery.yfinance_service, "fetch_financials", _fake_financials)

    profile = CompanyProfile(company_name="Acme", sector="Specialty Chemicals", revenue_cr=50, ebitda_cr=10, debt_cr=0, city="Surat")
    result = peer_discovery.discover_peers(profile, website_context="Source URL: https://acme.example\nAcme makes specialty chemicals.")

    assert result.anchors[0].name == "Anchor One"
    assert result.candidate_universe_size >= 4
    assert len(result.peers) == 5
    assert result.peers[0].similarity_score >= result.peers[-1].similarity_score
    assert any("Candidate universe size" in note for note in result.methodology_notes)


def test_fallback_uses_anchor_tickers_when_expansion_fails(monkeypatch):
    monkeypatch.setattr(peer_discovery, "generate_json", lambda prompt: {"anchors": [{"name": "Anchor One", "ticker": "ANCHOR1", "rationale": "fallback anchor"}]})
    monkeypatch.setattr(peer_discovery, "_collect_candidate_universe", lambda anchors: ([], ["industry discovery failed"]))
    monkeypatch.setattr(peer_discovery.yfinance_service, "fetch_financials", lambda ticker: _fake_financials(ticker) if ticker == "ANCHOR1" else None)

    profile = CompanyProfile(company_name="Acme", sector="Specialty Chemicals", revenue_cr=50, ebitda_cr=10, debt_cr=0, city="Surat")
    result = peer_discovery.discover_peers(profile, website_context=None)

    assert result.candidate_universe_size == 1
    assert len(result.peers) == 1
    assert result.peers[0].ticker == "ANCHOR1"
    assert any("fallback candidates" in note for note in result.methodology_notes)


def test_similarity_scores_favor_matching_industry_and_description():
    profile = CompanyProfile(
        company_name="Acme",
        sector="Specialty Chemicals",
        industry="Specialty Chemicals",
        sub_industry="Performance chemicals",
        business_model="B2B manufacturer",
        customer_type="Industrial buyers",
        geography="India",
        revenue_cr=50,
        ebitda_cr=10,
        debt_cr=0,
        city="Surat",
        keywords=["chemicals", "industrial"],
    )
    strong_peer = PeerCompany(
        ticker="STRONG",
        name="Strong Peer",
        sector_tag="Specialty Chemicals",
        sector="Industrials",
        industry="Specialty Chemicals",
        country="India",
        revenue_cr=55,
        ebitda_margin=0.2,
        long_business_summary="Manufacturer of specialty chemicals for industrial customers.",
    )
    weak_peer = PeerCompany(
        ticker="WEAK",
        name="Weak Peer",
        sector_tag="Food",
        sector="Consumer Staples",
        industry="Food Products",
        country="United States",
        revenue_cr=500,
        ebitda_margin=0.05,
        long_business_summary="A packaged food brand with a retail focus.",
    )

    strong_score, strong_rationale = peer_discovery._candidate_breakdown(profile, strong_peer, 0.9)
    weak_score, weak_rationale = peer_discovery._candidate_breakdown(profile, weak_peer, 0.1)

    assert 0 <= strong_score <= 1
    assert 0 <= weak_score <= 1
    assert strong_score > weak_score
    assert "industry=" in strong_rationale
    assert "description=" in weak_rationale
