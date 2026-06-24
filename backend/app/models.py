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
    source: str = "yfinance"
    similarity_score: Optional[float] = None
    ranking_rationale: Optional[str] = None


class AnchorCompany(BaseModel):
    name: str
    ticker: Optional[str] = None
    rationale: Optional[str] = None


class PeerDiscoveryResult(BaseModel):
    anchors: list[AnchorCompany] = Field(default_factory=list)
    peers: list[PeerCompany] = Field(default_factory=list)
    methodology_notes: list[str] = Field(default_factory=list)
    candidate_universe_size: int = 0


class ValuationRange(BaseModel):
    low_cr: float
    median_cr: float
    high_cr: float


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


class SessionState(BaseModel):
    session_id: str
    history: list[ChatTurn] = Field(default_factory=list)
    profile: CompanyProfile = Field(default_factory=CompanyProfile)
    stage: Literal["interview", "report_ready"] = "interview"
    report: Optional[dict] = None
