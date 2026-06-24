"""Pure deterministic valuation math. No LLM calls. No network calls.

Every number produced here must be traceable to either a peer's reported
multiple or a disclosed formula/constant (discount rate). This is the
auditability guarantee for the panel.
"""
import statistics
from app.config import PRIVATE_COMPANY_DISCOUNT
from app.models import CompanyProfile, PeerCompany, ValuationResult, ValuationRange


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        raise ValueError("cannot compute percentile of empty list")
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def compute_valuation(profile: CompanyProfile, peers: list[PeerCompany]) -> ValuationResult:
    notes: list[str] = []

    ebitda_multiples = sorted(p.ev_ebitda for p in peers if p.ev_ebitda is not None and p.ev_ebitda > 0)
    revenue_multiples = sorted(p.ev_revenue for p in peers if p.ev_revenue is not None and p.ev_revenue > 0)

    if not ebitda_multiples and not revenue_multiples:
        return ValuationResult(
            profile=profile,
            peers_used=peers,
            discount_applied=PRIVATE_COMPANY_DISCOUNT,
            methodology_notes=[
                "No usable peer multiples were available (peers had no EV/EBITDA or EV/Revenue data). "
                "Valuation could not be computed."
            ],
        )

    median_ev_ebitda = statistics.median(ebitda_multiples) if ebitda_multiples else None
    median_ev_revenue = statistics.median(revenue_multiples) if revenue_multiples else None

    enterprise_value_cr = None
    basis = None
    if median_ev_ebitda is not None and profile.ebitda_cr is not None and profile.ebitda_cr > 0:
        enterprise_value_cr = median_ev_ebitda * profile.ebitda_cr
        basis = "EV/EBITDA"
        notes.append(
            f"Enterprise value = median peer EV/EBITDA ({median_ev_ebitda:.2f}x, n={len(ebitda_multiples)} peers) "
            f"x target EBITDA (Rs.{profile.ebitda_cr:.2f} Cr) = Rs.{enterprise_value_cr:.2f} Cr."
        )
    elif median_ev_revenue is not None and profile.revenue_cr is not None and profile.revenue_cr > 0:
        enterprise_value_cr = median_ev_revenue * profile.revenue_cr
        basis = "EV/Revenue"
        notes.append(
            f"EBITDA-based valuation unavailable; fell back to EV/Revenue. "
            f"Enterprise value = median peer EV/Revenue ({median_ev_revenue:.2f}x, n={len(revenue_multiples)} peers) "
            f"x target revenue (Rs.{profile.revenue_cr:.2f} Cr) = Rs.{enterprise_value_cr:.2f} Cr."
        )

    if enterprise_value_cr is None:
        return ValuationResult(
            profile=profile,
            peers_used=peers,
            median_ev_ebitda=median_ev_ebitda,
            median_ev_revenue=median_ev_revenue,
            discount_applied=PRIVATE_COMPANY_DISCOUNT,
            methodology_notes=notes + ["Target profile missing EBITDA and revenue figures needed to apply multiples."],
        )

    debt = profile.debt_cr or 0.0
    equity_value_pre_discount = enterprise_value_cr - debt
    notes.append(f"Equity value pre-discount = EV (Rs.{enterprise_value_cr:.2f} Cr) - debt (Rs.{debt:.2f} Cr) = Rs.{equity_value_pre_discount:.2f} Cr.")

    equity_value_post_discount = equity_value_pre_discount * (1 - PRIVATE_COMPANY_DISCOUNT)
    notes.append(
        f"Private company discount of {PRIVATE_COMPANY_DISCOUNT*100:.0f}% applied (private/unlisted companies trade "
        f"at a discount to listed peers due to illiquidity and lower governance/disclosure standards). "
        f"Final equity value = Rs.{equity_value_post_discount:.2f} Cr."
    )

    multiples = ebitda_multiples if basis == "EV/EBITDA" else revenue_multiples
    base_metric = profile.ebitda_cr if basis == "EV/EBITDA" else profile.revenue_cr
    p25_multiple = _percentile(multiples, 0.25)
    p75_multiple = _percentile(multiples, 0.75)
    low_cr = max(0.0, (p25_multiple * base_metric - debt) * (1 - PRIVATE_COMPANY_DISCOUNT))
    high_cr = (p75_multiple * base_metric - debt) * (1 - PRIVATE_COMPANY_DISCOUNT)
    notes.append(
        f"Range computed using peer P25 ({p25_multiple:.2f}x) to P75 ({p75_multiple:.2f}x) multiples, "
        f"same debt subtraction and discount applied to each end."
    )

    return ValuationResult(
        profile=profile,
        peers_used=peers,
        median_ev_ebitda=median_ev_ebitda,
        median_ev_revenue=median_ev_revenue,
        enterprise_value_cr=round(enterprise_value_cr, 2),
        equity_value_pre_discount_cr=round(equity_value_pre_discount, 2),
        discount_applied=PRIVATE_COMPANY_DISCOUNT,
        equity_value_post_discount_cr=round(equity_value_post_discount, 2),
        range=ValuationRange(
            low_cr=round(low_cr, 2),
            median_cr=round(equity_value_post_discount, 2),
            high_cr=round(high_cr, 2),
        ),
        methodology_notes=notes,
    )
