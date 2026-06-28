import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import type {
  DataSourceStatus,
  DiscountBreakdown,
  PeerCompany,
  ScreenerSnapshot,
  ValuationMethodResult,
  ValuationReport,
} from '../api/client'

function fmtCr(value: number | null): string {
  if (value === null || Number.isNaN(value)) return '—'
  return `Rs. ${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })} Cr`
}

function fmtMultiple(value: number | null): string {
  if (value === null || Number.isNaN(value)) return '—'
  return `${value.toFixed(2)}x`
}

/** value is a 0-100 number already (e.g. 12.5 means 12.5%) */
function fmtPctRaw(value: number | null): string {
  if (value === null || Number.isNaN(value)) return '—'
  return `${value.toFixed(1)}%`
}

/** value is a 0-1 fraction (e.g. 0.25 means 25%) */
function fmtPctFraction(value: number): string {
  return `${(value * 100).toFixed(1)}%`
}

function fmtSignedPts(value: number): string {
  const pts = Math.round(value * 1000) / 10
  if (pts === 0) return '±0 pts'
  return `${pts > 0 ? '+' : ''}${pts.toFixed(1)} pts`
}

function formatInputValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(2)
  }
  return String(value)
}

function prettyLabel(key: string): string {
  return key
    .replace(/_cr$/, ' (Cr)')
    .replace(/_pct$/, ' (%)')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/** One plain-language line that plugs the actual numbers into the formula
 * for this method, so the dashboard doesn't make the reader reconstruct the
 * calculation from a raw key-value dump. */
function methodFormula(result: ValuationMethodResult): string | null {
  if (!result.applicable) return null
  const inp = result.inputs || {}
  const num = (k: string) => (typeof inp[k] === 'number' ? (inp[k] as number) : null)

  if (result.method === 'EV/EBITDA' || result.method === 'EV/Revenue') {
    const multiple = num('median_multiple')
    const base = num('base_metric_cr')
    const debt = num('debt_cr')
    if (multiple === null || base === null || debt === null) return null
    const label = result.method === 'EV/EBITDA' ? 'EBITDA' : 'revenue'
    return `${multiple.toFixed(2)}x median peer multiple × Rs. ${base.toFixed(2)} Cr ${label} − Rs. ${debt.toFixed(2)} Cr debt = ${fmtCr(result.equity_value_cr)}`
  }

  if (result.method === 'DCF') {
    const growth = num('growth_pct')
    const margin = num('ebitda_margin_pct')
    const rate = num('discount_rate_pct')
    const years = num('projection_years')
    if (growth === null || margin === null || rate === null) return null
    return `${years ?? 5}-yr cash flows at ${growth.toFixed(1)}% growth, ${margin.toFixed(1)}% margin, discounted at ${rate.toFixed(1)}% = ${fmtCr(result.equity_value_cr)}`
  }

  return null
}

function StatusBadge({ ok, attempted }: { ok: boolean; attempted: boolean }) {
  if (!attempted) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-500">
        <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
        Not attempted
      </span>
    )
  }
  return ok ? (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-700">
      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
      Success
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-700">
      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
      Unavailable
    </span>
  )
}

function SectionCard({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-100 px-5 py-4">
        <h3 className="text-sm font-semibold tracking-wide text-slate-800">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  )
}

function DataSourcesPanel({ sources }: { sources: DataSourceStatus[] }) {
  if (sources.length === 0) return null
  return (
    <SectionCard title="Data sources" subtitle="What was attempted and what actually came through, this run.">
      <div className="grid gap-3 sm:grid-cols-2">
        {sources.map((s) => (
          <div key={s.name} className="rounded-xl border border-slate-100 bg-slate-50 p-3">
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium text-slate-800">{s.name}</p>
              <StatusBadge ok={s.success} attempted={s.attempted} />
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-600">{s.detail}</p>
            {s.fields_retrieved.length > 0 && (
              <p className="mt-1.5 text-xs text-slate-400">
                {s.fields_retrieved.length} field(s): {s.fields_retrieved.slice(0, 6).join(', ')}
                {s.fields_retrieved.length > 6 ? ', …' : ''}
              </p>
            )}
          </div>
        ))}
      </div>
    </SectionCard>
  )
}

function MethodCard({ result }: { result: ValuationMethodResult }) {
  const entries = Object.entries(result.inputs || {})
  const formula = methodFormula(result)
  return (
    <div className={`rounded-xl border p-4 ${result.applicable ? 'border-indigo-100 bg-indigo-50/40' : 'border-slate-100 bg-slate-50'}`}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-slate-800">{result.method}</p>
        {result.applicable ? (
          <span className="rounded-full bg-indigo-100 px-2.5 py-0.5 text-xs font-medium text-indigo-700">
            {fmtPctFraction(result.weight)} weight
          </span>
        ) : (
          <span className="rounded-full bg-slate-200 px-2.5 py-0.5 text-xs font-medium text-slate-500">Not applicable</span>
        )}
      </div>
      {result.applicable && result.equity_value_cr !== null && (
        <p className="mt-1 text-lg font-semibold text-slate-900">{fmtCr(result.equity_value_cr)}</p>
      )}
      {formula && (
        <p className="mt-1.5 rounded-lg bg-white/70 px-2.5 py-1.5 text-xs font-medium text-indigo-700 ring-1 ring-inset ring-indigo-100">
          {formula}
        </p>
      )}
      <p className="mt-1.5 text-xs leading-relaxed text-slate-600">{result.detail}</p>
      {entries.length > 0 && (
        <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 border-t border-slate-200/70 pt-2">
          {entries.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-2 text-xs">
              <dt className="text-slate-400">{prettyLabel(k)}</dt>
              <dd className="font-medium text-slate-600">{formatInputValue(v)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

/** CSS-only horizontal bar chart comparing equity value across the 4
 * methods, so the blend isn't only readable as four separate cards — you
 * can see at a glance which method pulled the estimate up or down, and how
 * much weight each got in the final blend. */
function MethodComparisonBars({ results }: { results: ValuationMethodResult[] }) {
  const applicable = results.filter((r) => r.applicable && r.equity_value_cr !== null)
  if (applicable.length === 0) return null
  const maxValue = Math.max(...applicable.map((r) => Math.abs(r.equity_value_cr as number)), 1)

  return (
    <SectionCard
      title="Method comparison"
      subtitle="Equity value each method produced on its own, before blending — bar length and weight both matter to the final number."
    >
      <div className="space-y-3">
        {results.map((r) => {
          const value = r.equity_value_cr
          const widthPct = r.applicable && value !== null ? Math.max(4, (Math.abs(value) / maxValue) * 100) : 0
          return (
            <div key={r.method}>
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="font-medium text-slate-700">{r.method}</span>
                <span className="text-slate-500">
                  {r.applicable && value !== null ? `${fmtCr(value)} · ${fmtPctFraction(r.weight)} weight` : 'Not applicable'}
                </span>
              </div>
              <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
                {r.applicable && value !== null && (
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-indigo-400 to-indigo-600"
                    style={{ width: `${widthPct}%` }}
                  />
                )}
              </div>
            </div>
          )
        })}
      </div>
    </SectionCard>
  )
}

function DiscountPanel({ breakdown }: { breakdown: DiscountBreakdown }) {
  const rows: { label: string; value: number }[] = [
    { label: 'Base (revenue-band illiquidity discount)', value: breakdown.base_illiquidity_discount },
    { label: 'Growth adjustment', value: breakdown.growth_adjustment },
    { label: 'Margin quality adjustment', value: breakdown.margin_adjustment },
    { label: 'Customer concentration adjustment', value: breakdown.concentration_adjustment },
    { label: 'Company maturity adjustment', value: breakdown.maturity_adjustment },
    { label: 'Data confidence adjustment', value: breakdown.data_confidence_adjustment },
  ]
  return (
    <SectionCard title="Illiquidity discount breakdown" subtitle="No flat 25% — built up from disclosed, auditable adjustments.">
      <div className="space-y-1.5">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center justify-between text-sm">
            <span className="text-slate-600">{r.label}</span>
            <span className={`font-medium ${r.value > 0 ? 'text-amber-600' : r.value < 0 ? 'text-emerald-600' : 'text-slate-400'}`}>
              {r.label.startsWith('Base') ? fmtPctFraction(r.value) : fmtSignedPts(r.value)}
            </span>
          </div>
        ))}
        <div className="mt-2 flex items-center justify-between border-t border-slate-200 pt-2 text-sm font-semibold">
          <span className="text-slate-800">Final discount applied</span>
          <span className="text-indigo-700">{fmtPctFraction(breakdown.final_discount)}</span>
        </div>
      </div>
      {breakdown.notes.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-slate-100 pt-3 text-xs text-slate-500">
          {breakdown.notes.map((n, i) => (
            <li key={i} className="border-l-2 border-slate-200 pl-2">
              {n}
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  )
}

function ScreenerPanel({ snapshot }: { snapshot: ScreenerSnapshot }) {
  if (snapshot.fields_found.length === 0) return null
  const fields: { label: string; value: string }[] = [
    { label: 'Market cap', value: fmtCr(snapshot.market_cap_cr) },
    { label: 'Current price', value: snapshot.current_price !== null ? `Rs. ${snapshot.current_price}` : '—' },
    { label: 'P/E ratio', value: snapshot.pe_ratio !== null ? snapshot.pe_ratio.toFixed(2) : '—' },
    { label: 'Book value', value: snapshot.book_value !== null ? `Rs. ${snapshot.book_value}` : '—' },
    { label: 'Dividend yield', value: fmtPctRaw(snapshot.dividend_yield_pct) },
    { label: 'ROCE', value: fmtPctRaw(snapshot.roce_pct) },
    { label: 'ROE', value: fmtPctRaw(snapshot.roe_pct) },
    { label: 'OPM', value: fmtPctRaw(snapshot.opm_pct) },
    { label: '3Y sales growth', value: fmtPctRaw(snapshot.sales_growth_3y_pct) },
    { label: '3Y profit growth', value: fmtPctRaw(snapshot.profit_growth_3y_pct) },
    { label: 'Promoter holding', value: fmtPctRaw(snapshot.promoter_holding_pct) },
    { label: 'Debt', value: fmtCr(snapshot.debt_cr) },
  ].filter((f) => f.value !== '—')

  return (
    <SectionCard
      title="Screener.in snapshot"
      subtitle={`Matched: ${snapshot.matched_company_name ?? 'unknown'}${snapshot.screener_url ? '' : ''}`}
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {fields.map((f) => (
          <div key={f.label} className="rounded-lg bg-slate-50 px-3 py-2">
            <p className="text-[11px] uppercase tracking-wide text-slate-400">{f.label}</p>
            <p className="mt-0.5 text-sm font-semibold text-slate-800">{f.value}</p>
          </div>
        ))}
      </div>
      {snapshot.screener_url && (
        <a
          href={snapshot.screener_url}
          target="_blank"
          rel="noreferrer"
          className="mt-3 inline-block text-xs font-medium text-indigo-600 hover:underline"
        >
          View on Screener.in →
        </a>
      )}
    </SectionCard>
  )
}

function SourceBadge({ source }: { source: string }) {
  const isScreener = source === 'screener.in'
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
        isScreener ? 'bg-sky-100 text-sky-700' : 'bg-slate-100 text-slate-500'
      }`}
    >
      {isScreener ? 'Screener.in' : 'yfinance'}
    </span>
  )
}

function PeersTable({ peers }: { peers: PeerCompany[] }) {
  const screenerCount = peers.filter((p) => p.source === 'screener.in').length
  const subtitle =
    screenerCount === peers.length
      ? "Sourced directly from Screener.in's own peer-comparison table for this company's sector/industry — not LLM-suggested."
      : screenerCount > 0
        ? `${screenerCount} of ${peers.length} from Screener.in's peer-comparison table, the rest from live listed-peer expansion.`
        : 'Live market data via listed-peer expansion (Screener.in had no usable peer-comparison data this run).'

  return (
    <SectionCard title="Listed peers used" subtitle={subtitle}>
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">EV/EBITDA</th>
              <th className="px-3 py-2 font-medium">EV/Revenue</th>
              <th className="px-3 py-2 font-medium">EBITDA margin</th>
              <th className="px-3 py-2 font-medium">Market cap</th>
              <th className="px-3 py-2 font-medium">Revenue</th>
              <th className="px-3 py-2 font-medium">P/E</th>
              <th className="px-3 py-2 font-medium">ROCE</th>
              <th className="px-3 py-2 font-medium">Debt</th>
              <th className="px-3 py-2 font-medium">Similarity</th>
              <th className="px-3 py-2 font-medium">Source</th>
            </tr>
          </thead>
          <tbody>
            {peers.map((p) => (
              <tr key={p.ticker} className="border-t border-slate-100">
                <td className="px-3 py-2">
                  {p.source_url ? (
                    <a
                      href={p.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="font-medium text-indigo-600 hover:underline"
                    >
                      {p.name}
                    </a>
                  ) : (
                    <span className="font-medium text-slate-800">{p.name}</span>
                  )}
                  <span className="ml-1.5 text-xs text-slate-400">{p.ticker}</span>
                </td>
                <td className="px-3 py-2 text-slate-600">{fmtMultiple(p.ev_ebitda)}</td>
                <td className="px-3 py-2 text-slate-600">{fmtMultiple(p.ev_revenue)}</td>
                <td className="px-3 py-2 text-slate-600">{p.ebitda_margin !== null ? fmtPctFraction(p.ebitda_margin) : '—'}</td>
                <td className="px-3 py-2 text-slate-600">{fmtCr(p.market_cap_cr)}</td>
                <td className="px-3 py-2 text-slate-600">{fmtCr(p.revenue_cr)}</td>
                <td className="px-3 py-2 text-slate-600">{p.pe_ratio !== null ? p.pe_ratio.toFixed(2) : '—'}</td>
                <td className="px-3 py-2 text-slate-600">{fmtPctRaw(p.roce_pct)}</td>
                <td className="px-3 py-2 text-slate-600">{fmtCr(p.debt_cr)}</td>
                <td className="px-3 py-2 text-slate-600">{p.similarity_score !== null ? p.similarity_score.toFixed(2) : '—'}</td>
                <td className="px-3 py-2">
                  <SourceBadge source={p.source} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  )
}

export default function ReportView({ report }: { report: ValuationReport }) {
  return (
    <div className="space-y-5">
      {/* Hero */}
      <div className="rounded-2xl bg-gradient-to-br from-indigo-600 to-indigo-800 p-6 text-white shadow-md">
        <p className="text-xs font-medium uppercase tracking-wider text-indigo-200">Estimated equity valuation</p>
        {report.range ? (
          <p className="mt-2 text-3xl font-bold tracking-tight">
            {fmtCr(report.range.low_cr)} <span className="text-indigo-300">–</span> {fmtCr(report.range.high_cr)}
          </p>
        ) : (
          <p className="mt-2 text-lg">Could not be computed — see notes below.</p>
        )}
        {report.range && <p className="mt-1 text-sm text-indigo-200">Blended median estimate: {fmtCr(report.range.median_cr)}</p>}

        <div className="mt-4 grid grid-cols-2 gap-3 border-t border-indigo-500/40 pt-4 sm:grid-cols-4">
          <div>
            <p className="text-[11px] uppercase tracking-wide text-indigo-300">Enterprise value</p>
            <p className="text-sm font-semibold">{fmtCr(report.enterprise_value_cr)}</p>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-wide text-indigo-300">Equity, pre-discount</p>
            <p className="text-sm font-semibold">{fmtCr(report.equity_value_pre_discount_cr)}</p>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-wide text-indigo-300">Discount applied</p>
            <p className="text-sm font-semibold">{fmtPctFraction(report.discount_applied)}</p>
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-wide text-indigo-300">Equity, post-discount</p>
            <p className="text-sm font-semibold">{fmtCr(report.equity_value_post_discount_cr)}</p>
          </div>
        </div>
        {report.profile.website_url && (
          <p className="mt-3 text-xs text-indigo-300">
            Website referenced: <span className="break-all text-indigo-100">{report.profile.website_url}</span>
          </p>
        )}
      </div>

      <div
        className={`rounded-xl border p-4 text-sm ${
          report.verified ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-amber-200 bg-amber-50 text-amber-800'
        }`}
      >
        {report.verification_note}
      </div>

      <DataSourcesPanel sources={report.data_sources} />

      {report.method_results.length > 0 && (
        <SectionCard
          title="Valuation methodology"
          subtitle="Every method attempted, its weight in the blend, and how it was computed — nothing hidden behind a single formula."
        >
          <div className="grid gap-3 sm:grid-cols-2">
            {report.method_results.map((m) => (
              <MethodCard key={m.method} result={m} />
            ))}
          </div>
        </SectionCard>
      )}

      {report.method_results.length > 0 && <MethodComparisonBars results={report.method_results} />}

      {report.discount_breakdown && <DiscountPanel breakdown={report.discount_breakdown} />}

      {report.screener_snapshot && <ScreenerPanel snapshot={report.screener_snapshot} />}

      {report.parameters_considered.length > 0 && (
        <SectionCard title="Parameters considered" subtitle="Every input that actually fed into this valuation.">
          <ul className="grid gap-1.5 sm:grid-cols-2">
            {report.parameters_considered.map((p, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-slate-700">
                <span className="mt-1 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-indigo-500" />
                {p}
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      {report.peers_used.length > 0 && <PeersTable peers={report.peers_used} />}

      <SectionCard title="Report narrative">
        <div className="prose prose-sm max-w-none text-slate-800 [&_h2]:mt-4 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:mb-1 [&_h3]:text-sm [&_h3]:font-semibold [&_p]:mb-2 [&_ul]:mb-2 [&_ul]:list-disc [&_ul]:pl-5">
          <ReactMarkdown>{report.narrative}</ReactMarkdown>
        </div>
      </SectionCard>

      {report.methodology_notes.length > 0 && (
        <SectionCard title="Full audit trail" subtitle="Every calculation step, in order.">
          <ul className="space-y-1 text-xs text-slate-500">
            {report.methodology_notes.map((note, i) => (
              <li key={i} className="border-l-2 border-slate-200 pl-3">
                {note}
              </li>
            ))}
          </ul>
        </SectionCard>
      )}
    </div>
  )
}
