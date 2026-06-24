from app.models import CompanyProfile, PeerCompany
from app.services.valuation import compute_valuation


def make_peer(ticker, ev_ebitda=None, ev_revenue=None):
    return PeerCompany(ticker=ticker, name=ticker, sector_tag="Textiles", ev_ebitda=ev_ebitda, ev_revenue=ev_revenue)


def test_basic_ev_ebitda_valuation():
    profile = CompanyProfile(company_name="Acme Textiles", sector="Textiles", revenue_cr=18, ebitda_cr=2.8, debt_cr=0, city="Surat")
    peers = [
        make_peer("SUTLEJTEX", ev_ebitda=7.2),
        make_peer("DONEAR", ev_ebitda=6.8),
        make_peer("GOKAKTEX", ev_ebitda=8.1),
        make_peer("SPORTKING", ev_ebitda=7.5),
        make_peer("NITIN", ev_ebitda=6.2),
    ]
    result = compute_valuation(profile, peers)

    assert result.median_ev_ebitda == 7.2
    assert result.enterprise_value_cr == round(7.2 * 2.8, 2)
    assert result.equity_value_pre_discount_cr == result.enterprise_value_cr
    assert result.equity_value_post_discount_cr == round(result.enterprise_value_cr * 0.75, 2)
    assert result.range.median_cr == result.equity_value_post_discount_cr
    assert result.range.low_cr < result.range.median_cr < result.range.high_cr
    assert result.discount_applied == 0.25


def test_debt_is_subtracted_before_discount():
    profile = CompanyProfile(company_name="X", sector="Textiles", revenue_cr=10, ebitda_cr=2, debt_cr=3, city="Surat")
    peers = [make_peer("A", ev_ebitda=5), make_peer("B", ev_ebitda=5)]
    result = compute_valuation(profile, peers)

    ev = 5 * 2
    expected_pre_discount = ev - 3
    assert result.enterprise_value_cr == ev
    assert result.equity_value_pre_discount_cr == expected_pre_discount
    assert result.equity_value_post_discount_cr == round(expected_pre_discount * 0.75, 2)


def test_falls_back_to_ev_revenue_when_no_ebitda_multiples():
    profile = CompanyProfile(company_name="X", sector="Textiles", revenue_cr=10, ebitda_cr=2, debt_cr=0, city="Surat")
    peers = [make_peer("A", ev_revenue=1.5), make_peer("B", ev_revenue=2.0)]
    result = compute_valuation(profile, peers)

    assert result.median_ev_ebitda is None
    assert result.median_ev_revenue == 1.75
    assert result.enterprise_value_cr == round(1.75 * 10, 2)


def test_no_usable_peer_multiples_returns_empty_result():
    profile = CompanyProfile(company_name="X", sector="Textiles", revenue_cr=10, ebitda_cr=2, debt_cr=0, city="Surat")
    peers = [make_peer("A"), make_peer("B")]
    result = compute_valuation(profile, peers)

    assert result.enterprise_value_cr is None
    assert result.range is None
    assert "could not be computed" in result.methodology_notes[0]


def test_missing_target_financials_returns_no_enterprise_value():
    profile = CompanyProfile(company_name="X", sector="Textiles", debt_cr=0, city="Surat")
    peers = [make_peer("A", ev_ebitda=5)]
    result = compute_valuation(profile, peers)

    assert result.enterprise_value_cr is None
    assert result.median_ev_ebitda == 5
