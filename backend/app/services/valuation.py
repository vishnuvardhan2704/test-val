"""Deterministic valuation math. No LLM calls. No network calls.

Every number produced here must be traceable to either a peer's reported
multiple, a disclosed DCF assumption, or a disclosed formula/constant
(discount rate, weight). This is the auditability guarantee for the panel.

This module blends three valuation methods rather than relying on a single
peer multiple:
  1. EV/EBITDA  — median peer multiple x target EBITDA
  2. EV/Revenue — median peer multiple x target revenue (always computed
     alongside EV/EBITDA when peer data allows, not only as a fallback)
  3. DCF        — a simplified 5-year discounted cash flow, independent of
     peer data entirely, so a valuation is still possible even when peer
     discovery finds few or no usable comparables.
A fourth method, asset-based net worth, is listed but is `applicable=False`
in the current interview flow because no balance-sheet data is collected
from the founder — it is included so the report is explicit about what an
industry-grade valuation would also consider, rather than silently omitting it.

The methods are blended with disclosed weights (config.METHOD_WEIGHTS),
renormalized over whichever subset is actually applicable for a given
company. The private-company illiquidity discount is no longer a flat
constant: it starts from a revenue-band base and is adjusted by growth,
margin quality, customer concentration, company maturity, and how much
verified external data backed the valuation (see DiscountBreakdown).
"""
from __future__ import annotations

import statistics
from typing import Optional

from app.config import (
    BASE_DISCOUNT_BY_REVENUE_BAND,
    DCF_DEFAULT_GROWTH_PCT,
    DCF_EQUITY_RISK_PREMIUM,
    DCF_PROJECTION_YEARS,
    DCF_RISK_FREE_RATE,
    DCF_SIZE_PREMIUM_SMALL_CAP,
    DCF_TERMINAL_GROWTH_RATE,
    MAX_FINAL_DISCOUNT,
    MIN_FINAL_DISCOUNT,
    METHOD_WEIGHTS,
)
from app.models import (
    CompanyProfile,
    DataSourceStatus,
    DiscountBreakdown,
    PeerCompany,
    ScreenerSnapshot,
    ValuationMethodResult,
    ValuationRange,
    ValuationResult,
)

# Simplified EBITDA -> unlevered free cash flow conversion factor, standing
# in for tax + maintenance capex + working-capital build, since none of
# those are collected in the interview. Disclosed in every DCF note.
DCF_EBITDA_TO_FCF_CONVERSION = 0.65

# Discount-rate / growth bump used to derive a low/high DCF sensitivity band
# instead of a single point estimate.
DCF_SENSITIVITY_GROWTH_DELTA = 0.02
DCF_SENSITIVITY_RATE_DELTA = 0.015

# Thresholds used by the qualitative discount adjustments below. These are
# disclosed assumptions, not industry constants — every one shows up as a
# one-line note in DiscountBreakdown.notes.
HIGH_GROWTH_THRESHOLD_PCT = 15.0
LOW_GROWTH_THRESHOLD_PCT = 5.0
HIGH_MARGIN_THRESHOLD = 0.20
LOW_MARGIN_THRESHOLD = 0.08
HIGH_CONCENTRATION_PCT = 50.0
MODERATE_CONCENTRATION_PCT = 30.0


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


def _revenue_band(profile: CompanyProfile) -> str:
    revenue = profile.revenue_cr or 0.0
    if revenue < 10:
        return "under_10cr"
    if revenue <= 50:
        return "10_50cr"
    return "over_50cr"


def _compute_multiple_method(
    method_name: str,
    profile: CompanyProfile,
    peers: list[PeerCompany],
    multiple_attr: str,
    base_metric: Optional[float],
    base_metric_label: str,
    is_equity_multiple: bool = False,
) -> ValuationMethodResult:
    valid_peers = [p for p in peers if getattr(p, multiple_attr, None) is not None and getattr(p, multiple_attr) > 0]
    
    if not valid_peers or not base_metric or base_metric <= 0:
        return ValuationMethodResult(
            method=method_name,
            applicable=False,
            detail=f"Not applicable — need at least one peer with a usable {method_name} multiple and a positive target {base_metric_label}."
        )

    total_weight = 0.0
    data = []
    
    import math
    for p in valid_peers:
        multiple = getattr(p, multiple_attr)
        distance = getattr(p, "similarity_score", None)
        
        # M&A Guardrail: Exponential decay weight for rigorous distance penalty
        weight = math.exp(-distance) if distance is not None else 1.0
            
        data.append((multiple, weight))
        total_weight += weight
        
    if not data:
        return ValuationMethodResult(
            method=method_name,
            applicable=False,
            detail=f"Not applicable — no valid peers found."
        )
        
    # M&A Guardrail: Weighted Median (naturally immune to extreme outliers like 1000x P/E)
    data.sort(key=lambda x: x[0])
    cumulative_weight = 0.0
    weighted_multiple = data[-1][0]
    for multiple, weight in data:
        cumulative_weight += weight
        if cumulative_weight >= total_weight / 2.0:
            weighted_multiple = multiple
            break
            
    multiples = [x[0] for x in data]
    
    p25_multiple = _percentile(sorted(multiples), 0.25)
    p75_multiple = _percentile(sorted(multiples), 0.75)

    value_low = p25_multiple * base_metric
    value_med = weighted_multiple * base_metric
    value_high = p75_multiple * base_metric

    debt = profile.debt_cr or 0.0
    
    equity_low = value_low if is_equity_multiple else value_low - debt
    equity_med = value_med if is_equity_multiple else value_med - debt
    equity_high = value_high if is_equity_multiple else value_high - debt
    
    debt_text = "" if is_equity_multiple else f", minus debt (Rs.{debt:.2f} Cr)"

    return ValuationMethodResult(
        method=method_name,
        applicable=True,
        equity_value_cr=round(equity_med, 2),
        detail=(
            f"Weighted peer {method_name} multiple ({weighted_multiple:.2f}x, n={len(valid_peers)} peers) x target "
            f"{base_metric_label} (Rs.{base_metric:.2f} Cr){debt_text}."
        ),
        inputs={
            "n_peers": len(valid_peers),
            "median_multiple": round(weighted_multiple, 4), # retained key for backwards compatibility
            "p25_multiple": round(p25_multiple, 4),
            "p75_multiple": round(p75_multiple, 4),
            "base_metric_cr": round(base_metric, 2),
            "debt_cr": round(debt, 2),
            "equity_value_low_cr": round(equity_low, 2),
            "equity_value_high_cr": round(equity_high, 2),
        },
    )


def _compute_ev_ebitda_method(profile: CompanyProfile, peers: list[PeerCompany]) -> ValuationMethodResult:
    return _compute_multiple_method("EV/EBITDA", profile, peers, "ev_ebitda", profile.ebitda_cr, "EBITDA")


def _compute_ev_revenue_method(profile: CompanyProfile, peers: list[PeerCompany]) -> ValuationMethodResult:
    return _compute_multiple_method("EV/Revenue", profile, peers, "ev_revenue", profile.revenue_cr, "revenue")


def _compute_pe_method(profile: CompanyProfile, peers: list[PeerCompany]) -> ValuationMethodResult:
    # Since we do not yet natively collect Net Profit from the founder, we approximate PAT 
    # as (EBITDA - 10% interest on debt) * 75% tax rate, for the P/E multiple
    target_net_profit = None
    if profile.ebitda_cr and profile.ebitda_cr > 0:
        interest = (profile.debt_cr or 0.0) * 0.10
        pbt = profile.ebitda_cr - interest
        target_net_profit = pbt * 0.75 if pbt > 0 else 0.0
        
    return _compute_multiple_method("P/E", profile, peers, "pe_ratio", target_net_profit, "estimated Net Profit", is_equity_multiple=True)


def _dcf_discount_rate() -> float:
    return DCF_RISK_FREE_RATE + DCF_EQUITY_RISK_PREMIUM + DCF_SIZE_PREMIUM_SMALL_CAP


def _run_dcf(revenue: float, margin: float, debt: float, initial_growth: float, discount_rate: float, exit_multiple: Optional[float] = None) -> float:
    """Returns equity value for one growth/discount-rate scenario."""
    discounted_fcf_sum = 0.0
    fcf_year_n = 0.0
    ebitda_year_n = 0.0
    revenue_y = revenue
    
    # M&A Guardrail: Linearly fade hyper-growth to the terminal rate over 5 years
    fade_step = max(0.0, (initial_growth - DCF_TERMINAL_GROWTH_RATE) / DCF_PROJECTION_YEARS)
    current_growth = initial_growth

    for year in range(1, DCF_PROJECTION_YEARS + 1):
        revenue_y = revenue_y * (1 + current_growth)
        ebitda_y = revenue_y * margin
        fcf_y = ebitda_y * DCF_EBITDA_TO_FCF_CONVERSION
        discounted_fcf_sum += fcf_y / ((1 + discount_rate) ** year)
        fcf_year_n = fcf_y
        ebitda_year_n = ebitda_y
        
        current_growth = max(DCF_TERMINAL_GROWTH_RATE, current_growth - fade_step)

    if exit_multiple and exit_multiple > 0:
        terminal_value = ebitda_year_n * exit_multiple
    elif discount_rate > DCF_TERMINAL_GROWTH_RATE:
        terminal_value = (fcf_year_n * (1 + DCF_TERMINAL_GROWTH_RATE)) / (discount_rate - DCF_TERMINAL_GROWTH_RATE)
    else:
        terminal_value = 0.0
        
    discounted_terminal = terminal_value / ((1 + discount_rate) ** DCF_PROJECTION_YEARS)

    enterprise_value = discounted_fcf_sum + discounted_terminal
    return enterprise_value - debt


def _compute_dcf_method(profile: CompanyProfile, exit_multiple: Optional[float] = None) -> ValuationMethodResult:
    revenue = profile.revenue_cr
    margin = profile.ebitda_margin
    if not revenue or revenue <= 0 or margin is None or margin <= 0:
        return ValuationMethodResult(
            method="DCF",
            applicable=False,
            detail="Not applicable — requires a positive target revenue and EBITDA margin.",
        )

    debt = profile.debt_cr or 0.0
    discount_rate = _dcf_discount_rate()

    if profile.revenue_growth_pct is not None:
        growth = profile.revenue_growth_pct / 100.0
        growth_source = "founder/website-reported growth (linearly faded to terminal rate over 5Y)"
    else:
        growth = DCF_DEFAULT_GROWTH_PCT
        growth_source = f"no growth figure available from any source — assumed {DCF_DEFAULT_GROWTH_PCT*100:.0f}% as a conservative default (faded to terminal)"

    base_equity = _run_dcf(revenue, margin, debt, growth, discount_rate, exit_multiple)
    low_equity = _run_dcf(
        revenue, margin, debt, growth - DCF_SENSITIVITY_GROWTH_DELTA, discount_rate + DCF_SENSITIVITY_RATE_DELTA, exit_multiple
    )
    high_equity = _run_dcf(
        revenue, margin, debt, growth + DCF_SENSITIVITY_GROWTH_DELTA, discount_rate - DCF_SENSITIVITY_RATE_DELTA, exit_multiple
    )

    term_desc = f"Terminal Exit Multiple: {exit_multiple:.1f}x" if exit_multiple else "Gordon Growth Terminal Value"

    return ValuationMethodResult(
        method="DCF",
        applicable=True,
        equity_value_cr=round(base_equity, 2),
        detail=(
            f"{DCF_PROJECTION_YEARS}-year DCF: {growth*100:.1f}% annual revenue growth ({growth_source}), "
            f"{margin*100:.1f}% EBITDA margin held flat, {DCF_EBITDA_TO_FCF_CONVERSION*100:.0f}% EBITDA-to-FCF "
            f"conversion (proxy for tax + capex + working capital), discounted at "
            f"{discount_rate*100:.1f}%. ({term_desc}) "
            f"Minus debt (Rs.{debt:.2f} Cr)."
        ),
        inputs={
            "growth_pct": round(growth * 100, 2),
            "growth_source": growth_source,
            "ebitda_margin_pct": round(margin * 100, 2),
            "discount_rate_pct": round(discount_rate * 100, 2),
            "terminal_growth_pct": round(DCF_TERMINAL_GROWTH_RATE * 100, 2),
            "fcf_conversion_pct": round(DCF_EBITDA_TO_FCF_CONVERSION * 100, 2),
            "projection_years": DCF_PROJECTION_YEARS,
            "equity_value_low_cr": round(low_equity, 2),
            "equity_value_high_cr": round(high_equity, 2),
        },
    )


def _compute_asset_based_method(profile: CompanyProfile, screener: Optional[ScreenerSnapshot]) -> ValuationMethodResult:
    # Always disclosed, almost always inapplicable in this interview flow:
    # net asset value requires a target balance sheet (total assets minus
    # total liabilities), which is not collected from the founder. Screener
    # book-value figures belong to listed peers, not the target, so they
    # cannot substitute here without misrepresenting whose balance sheet it is.
    return ValuationMethodResult(
        method="Asset-based (sanity check)",
        applicable=False,
        detail=(
            "Not applicable — would require the target company's own total assets and liabilities "
            "(net asset value), which the interview does not currently collect. Listed here so the "
            "report is explicit that this method was considered, not silently skipped."
        ),
    )


def _compute_discount_breakdown(
    profile: CompanyProfile,
    n_peers_used: int,
    screener_matched: bool,
) -> DiscountBreakdown:
    band = _revenue_band(profile)
    base = BASE_DISCOUNT_BY_REVENUE_BAND[band]
    notes = [f"Base illiquidity discount for revenue band '{band.replace('_', '-')}': {base*100:.0f}%."]

    growth_adj = 0.0
    if profile.revenue_growth_pct is not None:
        if profile.revenue_growth_pct >= HIGH_GROWTH_THRESHOLD_PCT:
            growth_adj = -0.03
            notes.append(f"Revenue growth {profile.revenue_growth_pct:.1f}% is above {HIGH_GROWTH_THRESHOLD_PCT:.0f}% — discount reduced by 3 pts.")
        elif profile.revenue_growth_pct <= LOW_GROWTH_THRESHOLD_PCT:
            growth_adj = 0.03
            notes.append(f"Revenue growth {profile.revenue_growth_pct:.1f}% is at/below {LOW_GROWTH_THRESHOLD_PCT:.0f}% — discount increased by 3 pts.")

    margin_adj = 0.0
    margin = profile.ebitda_margin
    if margin is not None:
        if margin >= HIGH_MARGIN_THRESHOLD:
            margin_adj = -0.02
            notes.append(f"EBITDA margin {margin*100:.1f}% is above {HIGH_MARGIN_THRESHOLD*100:.0f}% — discount reduced by 2 pts.")
        elif margin <= LOW_MARGIN_THRESHOLD:
            margin_adj = 0.03
            notes.append(f"EBITDA margin {margin*100:.1f}% is at/below {LOW_MARGIN_THRESHOLD*100:.0f}% — discount increased by 3 pts.")

    concentration_adj = 0.0
    if profile.customer_concentration_pct is not None:
        if profile.customer_concentration_pct >= HIGH_CONCENTRATION_PCT:
            concentration_adj = 0.05
            notes.append(f"Customer concentration {profile.customer_concentration_pct:.0f}% is high (>= {HIGH_CONCENTRATION_PCT:.0f}%) — discount increased by 5 pts.")
        elif profile.customer_concentration_pct >= MODERATE_CONCENTRATION_PCT:
            concentration_adj = 0.02
            notes.append(f"Customer concentration {profile.customer_concentration_pct:.0f}% is moderate — discount increased by 2 pts.")

    maturity_adj = 0.0
    if profile.years_operating is not None:
        if profile.years_operating < 3:
            maturity_adj = 0.04
            notes.append(f"Company is young ({profile.years_operating:.0f} yrs operating) — discount increased by 4 pts.")
        elif profile.years_operating >= 10:
            maturity_adj = -0.02
            notes.append(f"Company is established ({profile.years_operating:.0f}+ yrs operating) — discount reduced by 2 pts.")

    data_confidence_adj = 0.0
    if screener_matched and n_peers_used >= 3:
        data_confidence_adj = -0.02
        notes.append("Verified Screener.in data plus 3+ live listed peers were available — discount reduced by 2 pts for higher data confidence.")
    elif not screener_matched and n_peers_used == 0:
        data_confidence_adj = 0.03
        notes.append("No Screener.in match and no usable listed peers — discount increased by 3 pts for low data confidence.")

    raw_final = base + growth_adj + margin_adj + concentration_adj + maturity_adj + data_confidence_adj
    final = max(MIN_FINAL_DISCOUNT, min(MAX_FINAL_DISCOUNT, raw_final))
    if final != raw_final:
        notes.append(f"Final discount clamped to the [{MIN_FINAL_DISCOUNT*100:.0f}%, {MAX_FINAL_DISCOUNT*100:.0f}%] band.")

    return DiscountBreakdown(
        base_illiquidity_discount=base,
        growth_adjustment=growth_adj,
        margin_adjustment=margin_adj,
        concentration_adjustment=concentration_adj,
        maturity_adjustment=maturity_adj,
        data_confidence_adjustment=data_confidence_adj,
        final_discount=round(final, 4),
        notes=notes,
    )


def _parameters_considered(profile: CompanyProfile, peers: list[PeerCompany], screener: Optional[ScreenerSnapshot]) -> list[str]:
    params = [
        f"Revenue: Rs.{profile.revenue_cr:.2f} Cr" if profile.revenue_cr else None,
        f"EBITDA: Rs.{profile.ebitda_cr:.2f} Cr ({profile.ebitda_margin*100:.1f}% margin)" if profile.ebitda_cr is not None and profile.ebitda_margin is not None else None,
        f"Total debt: Rs.{profile.debt_cr:.2f} Cr" if profile.debt_cr is not None else None,
        f"Sector: {profile.sector}" if profile.sector else None,
        f"Business model: {profile.business_model}" if profile.business_model else None,
        f"Years operating: {profile.years_operating:.0f}" if profile.years_operating is not None else None,
        f"Revenue growth: {profile.revenue_growth_pct:.1f}%" if profile.revenue_growth_pct is not None else None,
        f"Customer concentration: {profile.customer_concentration_pct:.0f}%" if profile.customer_concentration_pct is not None else None,
        f"{len(peers)} live listed peer(s) used" if peers else "No live listed peers available",
        f"Screener.in data matched: {screener.matched_company_name}" if screener and screener.fields_found else "Screener.in data not available for this run",
    ]
    return [p for p in params if p]


def compute_valuation(
    profile: CompanyProfile,
    peers: list[PeerCompany],
    screener: Optional[ScreenerSnapshot] = None,
    data_sources: Optional[list[DataSourceStatus]] = None,
) -> ValuationResult:
    notes: list[str] = []
    data_sources = data_sources or []

    ev_ebitda_result = _compute_ev_ebitda_method(profile, peers)
    ev_revenue_result = _compute_ev_revenue_method(profile, peers)
    pe_result = _compute_pe_method(profile, peers)
    
    exit_multiple = ev_ebitda_result.inputs.get("median_multiple") if ev_ebitda_result.applicable else None
    dcf_result = _compute_dcf_method(profile, exit_multiple)
    
    asset_result = _compute_asset_based_method(profile, screener)
    method_results = [ev_ebitda_result, pe_result, ev_revenue_result, dcf_result, asset_result]

    for result in method_results:
        notes.append(f"[{result.method}] {result.detail}")

    applicable = [m for m in method_results if m.applicable and m.equity_value_cr is not None]
    screener_matched = bool(screener and screener.fields_found)

    if not applicable:
        return ValuationResult(
            profile=profile,
            peers_used=peers,
            discount_applied=BASE_DISCOUNT_BY_REVENUE_BAND[_revenue_band(profile)],
            methodology_notes=notes + ["No valuation method was applicable — target profile is missing the financial figures needed for every method."],
            method_results=method_results,
            data_sources=data_sources,
            screener_snapshot=screener,
            parameters_considered=_parameters_considered(profile, peers, screener),
        )

    total_weight = sum(METHOD_WEIGHTS.get(m.method, 0.0) for m in applicable)
    if total_weight <= 0:
        equal_weight = 1.0 / len(applicable)
        for m in applicable:
            m.weight = equal_weight
        notes.append("No configured weights matched the applicable methods — falling back to equal weighting.")
    else:
        for m in applicable:
            m.weight = round(METHOD_WEIGHTS.get(m.method, 0.0) / total_weight, 4)

    blended_pre_discount = sum(m.weight * m.equity_value_cr for m in applicable)
    blended_low_pre = sum(
        m.weight * (m.inputs.get("equity_value_low_cr", m.equity_value_cr)) for m in applicable
    )
    blended_high_pre = sum(
        m.weight * (m.inputs.get("equity_value_high_cr", m.equity_value_cr)) for m in applicable
    )

    notes.append(
        "Blended pre-discount equity value = "
        + " + ".join(f"{m.weight*100:.0f}% x [{m.method}] Rs.{m.equity_value_cr:.2f} Cr" for m in applicable)
        + f" = Rs.{blended_pre_discount:.2f} Cr."
    )

    discount_breakdown = _compute_discount_breakdown(profile, len(peers), screener_matched)
    final_discount = discount_breakdown.final_discount
    notes.extend(discount_breakdown.notes)

    equity_post = blended_pre_discount * (1 - final_discount)
    low_cr = blended_low_pre * (1 - final_discount)
    high_cr = blended_high_pre * (1 - final_discount)
    notes.append(
        f"Final blended discount applied: {final_discount*100:.1f}%. Equity value = Rs.{blended_pre_discount:.2f} Cr "
        f"x (1 - {final_discount*100:.1f}%) = Rs.{equity_post:.2f} Cr."
    )

    ebitda_multiples_result = next((m for m in applicable if m.method == "EV/EBITDA"), None)
    revenue_multiples_result = next((m for m in applicable if m.method == "EV/Revenue"), None)

    return ValuationResult(
        profile=profile,
        peers_used=peers,
        median_ev_ebitda=ebitda_multiples_result.inputs.get("median_multiple") if ebitda_multiples_result else None,
        median_ev_revenue=revenue_multiples_result.inputs.get("median_multiple") if revenue_multiples_result else None,
        enterprise_value_cr=round(blended_pre_discount + (profile.debt_cr or 0.0), 2),
        equity_value_pre_discount_cr=round(blended_pre_discount, 2),
        discount_applied=round(final_discount, 4),
        equity_value_post_discount_cr=round(equity_post, 2),
        range=ValuationRange(
            low_cr=round(max(0.0, low_cr), 2),
            median_cr=round(equity_post, 2),
            high_cr=round(high_cr, 2),
        ),
        methodology_notes=notes,
        method_results=method_results,
        discount_breakdown=discount_breakdown,
        screener_snapshot=screener,
        data_sources=data_sources,
        parameters_considered=_parameters_considered(profile, peers, screener),
    )
