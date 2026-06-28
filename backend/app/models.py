from typing import Optional, Literal
from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class CompanyProfile(BaseModel):
    company_name: Optional[str] = None
    sector: Optional[str] = None
    nse_sector_tag: Optional[str] = None
    website_url: Optional[str] = None
    industry: Optional[str] = None
    sub_industry: Optional[str] = None
    customer_type: Optional[str] = None
    competitors: Optional[list[str]] = None
    keywords: Optional[list[str]] = None
    geography: Optional[str] = None
    city: Optional[str] = None
    years_operating: Optional[float] = None
    business_model: Optional[str] = None
    revenue_cr: Optional[float] = None
    ebitda_cr: Optional[float] = None
    debt_cr: Optional[float] = None
    gstin: Optional[str] = None
    # Optional extras — never asked of the founder directly. Filled in (when
    # available) from Screener.in data or volunteered conversation, and used
    # to make the valuation and discount more than a 3-number formula.
    revenue_growth_pct: Optional[float] = None
    customer_concentration_pct: Optional[float] = None  # % of revenue from top customer/segment, if mentioned

    @property
    def ebitda_margin(self) -> Optional[float]:
        if self.revenue_cr and self.ebitda_cr is not None and self.revenue_cr > 0:
            return round(self.ebitda_cr / self.revenue_cr, 4)
        return None

    def missing_required_fields(self) -> list[str]:
        required = ["company_name", "sector", "revenue_cr", "ebitda_cr", "debt_cr", "city"]
        return [f for f in required if getattr(self, f) is None]


class PeerCompany(BaseModel):
    ticker: str
    name: str
    sector_tag: str
    sector: Optional[str] = None
    sector_key: Optional[str] = None
    industry: Optional[str] = None
    industry_key: Optional[str] = None
    country: Optional[str] = None
    revenue_growth: Optional[float] = None
    enterprise_value_cr: Optional[float] = None
    full_time_employees: Optional[float] = None
    long_business_summary: Optional[str] = None
    ev_ebitda: Optional[float] = None
    ev_revenue: Optional[float] = None
    ebitda_margin: Optional[float] = None
    market_cap_cr: Optional[float] = None
    revenue_cr: Optional[float] = None
    net_profit_cr: Optional[float] = None
    pe_ratio: Optional[float] = None
    roce_pct: Optional[float] = None
    debt_cr: Optional[float] = None
    source: str = "screener.in"
    source_url: Optional[str] = None  # link to where this peer's data came from (e.g. its Screener.in page)
    similarity_score: Optional[float] = None
    ranking_rationale: Optional[str] = None




class ValuationRange(BaseModel):
    low_cr: float
    median_cr: float
    high_cr: float


class DataSourceStatus(BaseModel):
    """One row per external data source the pipeline attempted to use this
    run. Surfaced directly on the dashboard so the founder (and anyone
    auditing the report) can see exactly what data did and didn't come
    through, instead of a black box."""

    name: str  # e.g. "Screener.in", "yfinance peers", "NSE Emerge list", "Company website"
    attempted: bool = True
    success: bool = False
    fields_retrieved: list[str] = Field(default_factory=list)
    detail: str = ""


class ScreenerSnapshot(BaseModel):
    """Structured fields scraped from the company's Screener.in page, if one
    could be found and matched via the site's search box. Every field is
    optional and independently None-safe — a partial match (e.g. ratios found
    but no shareholding table) is still useful and is reported as such via
    fields_found."""

    matched_company_name: Optional[str] = None
    screener_url: Optional[str] = None
    market_cap_cr: Optional[float] = None
    current_price: Optional[float] = None
    pe_ratio: Optional[float] = None
    book_value: Optional[float] = None
    dividend_yield_pct: Optional[float] = None
    roce_pct: Optional[float] = None
    roe_pct: Optional[float] = None
    face_value: Optional[float] = None
    sales_cr: Optional[float] = None
    sales_growth_3y_pct: Optional[float] = None
    profit_cr: Optional[float] = None
    profit_growth_3y_pct: Optional[float] = None
    opm_pct: Optional[float] = None
    debt_cr: Optional[float] = None
    promoter_holding_pct: Optional[float] = None
    fields_found: list[str] = Field(default_factory=list)


class ValuationMethodResult(BaseModel):
    """One row per valuation method attempted (EV/EBITDA, EV/Revenue, DCF,
    asset-based). `applicable=False` means the method couldn't be computed
    for this company (e.g. no peer EV/EBITDA data, or no book-value figure
    for the asset check) — it is still listed so the report shows what was
    considered and why it was or wasn't used, rather than silently omitting it."""

    method: Literal["EV/EBITDA", "EV/Revenue", "P/E", "DCF", "Asset-based (sanity check)"]
    applicable: bool
    weight: float = 0.0  # share of the blended estimate this method contributed, 0-1
    equity_value_cr: Optional[float] = None
    detail: str = ""
    inputs: dict = Field(default_factory=dict)


class DiscountBreakdown(BaseModel):
    """Replaces the old flat 25% illiquidity discount. Starts from a
    revenue-band base discount and is adjusted up/down by disclosed amounts
    for growth, margin quality, customer concentration, company maturity,
    and how much real data backed this valuation — every adjustment is a
    plain number with a one-line reason, so the final discount is auditable
    rather than a constant pulled from thin air."""

    base_illiquidity_discount: float
    growth_adjustment: float = 0.0
    margin_adjustment: float = 0.0
    concentration_adjustment: float = 0.0
    maturity_adjustment: float = 0.0
    data_confidence_adjustment: float = 0.0
    final_discount: float
    notes: list[str] = Field(default_factory=list)


class ValuationResult(BaseModel):
    profile: CompanyProfile
    peers_used: list[PeerCompany]
    median_ev_ebitda: Optional[float] = None
    median_ev_revenue: Optional[float] = None
    enterprise_value_cr: Optional[float] = None
    equity_value_pre_discount_cr: Optional[float] = None
    discount_applied: float
    equity_value_post_discount_cr: Optional[float] = None
    range: Optional[ValuationRange] = None
    methodology_notes: list[str] = Field(default_factory=list)
    verified: bool = False
    verification_note: str = "Unverified — GST/MCA verification not yet implemented in this version."
    # NEW: full transparency surface for the dashboard.
    method_results: list[ValuationMethodResult] = Field(default_factory=list)
    discount_breakdown: Optional[DiscountBreakdown] = None
    screener_snapshot: Optional[ScreenerSnapshot] = None
    data_sources: list[DataSourceStatus] = Field(default_factory=list)
    parameters_considered: list[str] = Field(default_factory=list)


class SessionState(BaseModel):
    session_id: str
    history: list[ChatTurn] = Field(default_factory=list)
    profile: CompanyProfile = Field(default_factory=CompanyProfile)
    stage: Literal["interview", "report_ready"] = "interview"
    report: Optional[dict] = None
    # Persisted across turns so a fetched company website isn't silently
    # dropped (and re-fetched on every single message).
    website_context: Optional[str] = None
