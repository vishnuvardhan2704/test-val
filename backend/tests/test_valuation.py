from app.config import BASE_DISCOUNT_BY_REVENUE_BAND, MAX_FINAL_DISCOUNT, MIN_FINAL_DISCOUNT
from app.models import CompanyProfile, PeerCompany, ScreenerSnapshot
from app.services.valuation import compute_valuation


def make_peer(ticker, ev_ebitda=None, ev_revenue=None):
    return PeerCompany(ticker=ticker, name=ticker, sector_tag="Textiles", ev_ebitda=ev_ebitda, ev_revenue=ev_revenue)


def _weighted_sum(method_results):
    applicable = [m for m in method_results if m.applicable and m.equity_value_cr is not None]
    return sum(m.weight * m.equity_value_cr for m in applicable)


def test_all_applicable_methods_are_blended():
    profile = CompanyProfile(company_name="Acme Textiles", sector="Textiles", revenue_cr=18, ebitda_cr=2.8, debt_cr=0, city="Surat")
    peers = [
        make_peer("SUTLEJTEX", ev_ebitda=7.2, ev_revenue=1.1),
        make_peer("DONEAR", ev_ebitda=6.8, ev_revenue=0.9),
        make_peer("GOKAKTEX", ev_ebitda=8.1, ev_revenue=1.3),
        make_peer("SPORTKING", ev_ebitda=7.5, ev_revenue=1.0),
        make_peer("NITIN", ev_ebitda=6.2, ev_revenue=0.8),
    ]
    result = compute_valuation(profile, peers)

    methods = {m.method: m for m in result.method_results}
    assert set(methods) == {"EV/EBITDA", "EV/Revenue", "P/E", "DCF", "Asset-based (sanity check)"}
    assert methods["EV/EBITDA"].applicable
    assert methods["EV/Revenue"].applicable
    assert methods["DCF"].applicable
    assert not methods["Asset-based (sanity check)"].applicable

    applicable = [m for m in result.method_results if m.applicable]
    assert abs(sum(m.weight for m in applicable) - 1.0) < 1e-6

    assert result.discount_breakdown is not None
    assert MIN_FINAL_DISCOUNT <= result.discount_breakdown.final_discount <= MAX_FINAL_DISCOUNT
    assert result.discount_applied == result.discount_breakdown.final_discount

    blended_pre = _weighted_sum(result.method_results)
    expected_post = round(blended_pre * (1 - result.discount_breakdown.final_discount), 2)
    assert result.equity_value_post_discount_cr == expected_post
    assert result.range.low_cr < result.range.median_cr < result.range.high_cr


def test_debt_is_subtracted_in_multiple_methods():
    profile = CompanyProfile(company_name="X", sector="Textiles", revenue_cr=10, ebitda_cr=2, debt_cr=3, city="Surat")
    peers = [make_peer("A", ev_ebitda=5), make_peer("B", ev_ebitda=5)]
    result = compute_valuation(profile, peers)

    ev_ebitda_method = next(m for m in result.method_results if m.method == "EV/EBITDA")
    assert ev_ebitda_method.applicable
    assert ev_ebitda_method.equity_value_cr == round(5 * 2 - 3, 2)


def test_dcf_is_applicable_even_with_zero_peers():
    """The headline fix: a valuation should still be produced from DCF alone
    when peer discovery finds nothing usable, instead of returning an empty
    'could not be computed' result like the old single-formula engine did."""
    profile = CompanyProfile(company_name="X", sector="Textiles", revenue_cr=10, ebitda_cr=2, debt_cr=0, city="Surat")
    result = compute_valuation(profile, peers=[])

    methods = {m.method: m for m in result.method_results}
    assert not methods["EV/EBITDA"].applicable
    assert not methods["EV/Revenue"].applicable
    assert methods["DCF"].applicable
    assert methods["DCF"].equity_value_cr is not None
    assert methods["DCF"].weight == 1.0
    assert result.range is not None
    assert result.enterprise_value_cr is not None


def test_no_method_applicable_when_financials_missing():
    profile = CompanyProfile(company_name="X", sector="Textiles", debt_cr=0, city="Surat")
    peers = [make_peer("A", ev_ebitda=5)]
    result = compute_valuation(profile, peers)

    assert result.range is None
    assert result.enterprise_value_cr is None
    assert result.discount_applied == BASE_DISCOUNT_BY_REVENUE_BAND["under_10cr"]
    assert any("No valuation method was applicable" in n for n in result.methodology_notes)


def test_discount_breakdown_reflects_disclosed_adjustments():
    profile = CompanyProfile(
        company_name="X",
        sector="Textiles",
        revenue_cr=18,
        ebitda_cr=4.5,  # 25% margin -> high-margin adjustment
        debt_cr=0,
        city="Surat",
        years_operating=1,  # young -> maturity adjustment
        revenue_growth_pct=20,  # high growth -> growth adjustment
        customer_concentration_pct=60,  # high concentration -> concentration adjustment
    )
    peers = [make_peer("A", ev_ebitda=7), make_peer("B", ev_ebitda=7.5), make_peer("C", ev_ebitda=6.5)]
    screener = ScreenerSnapshot(matched_company_name="X Ltd", fields_found=["roe_pct"])

    result = compute_valuation(profile, peers, screener=screener)
    b = result.discount_breakdown

    assert b.base_illiquidity_discount == BASE_DISCOUNT_BY_REVENUE_BAND["10_50cr"]
    assert b.growth_adjustment == -0.03
    assert b.margin_adjustment == -0.02
    assert b.concentration_adjustment == 0.05
    assert b.maturity_adjustment == 0.04
    assert b.data_confidence_adjustment == -0.02  # screener matched + 3 peers
    assert len(b.notes) >= 5


def test_parameters_considered_lists_actual_inputs_used():
    profile = CompanyProfile(company_name="X", sector="Textiles", revenue_cr=10, ebitda_cr=2, debt_cr=0, city="Surat")
    result = compute_valuation(profile, peers=[])

    joined = " ".join(result.parameters_considered)
    assert "Revenue" in joined
    assert "EBITDA" in joined
    assert "Screener.in data not available" in joined
