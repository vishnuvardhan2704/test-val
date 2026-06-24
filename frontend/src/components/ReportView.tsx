import ReactMarkdown from 'react-markdown'
import type { ValuationReport } from '../api/client'

function fmtCr(value: number | null): string {
  if (value === null) return '—'
  return `Rs. ${value.toFixed(2)} Cr`
}

function fmtMultiple(value: number | null): string {
  if (value === null) return '—'
  return `${value.toFixed(2)}x`
}

function fmtPct(value: number | null): string {
  if (value === null) return '—'
  return `${(value * 100).toFixed(1)}%`
}

export default function ReportView({ report }: { report: ValuationReport }) {
  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-5">
        <p className="text-sm font-medium text-indigo-700">Estimated Equity Valuation</p>
        {report.range ? (
          <p className="mt-1 text-2xl font-semibold text-indigo-900">
            {fmtCr(report.range.low_cr)} &mdash; {fmtCr(report.range.high_cr)}
          </p>
        ) : (
          <p className="mt-1 text-lg text-indigo-900">Could not be computed — see notes below.</p>
        )}
        {report.range && (
          <p className="text-sm text-indigo-700">Median estimate: {fmtCr(report.range.median_cr)}</p>
        )}
        {report.profile.website_url && (
          <p className="mt-2 text-xs text-indigo-700">
            Website referenced: <span className="break-all">{report.profile.website_url}</span>
          </p>
        )}
      </div>

      <div
        className={`rounded-lg border p-4 text-sm ${
          report.verified ? 'border-green-200 bg-green-50 text-green-800' : 'border-amber-200 bg-amber-50 text-amber-800'
        }`}
      >
        {report.verification_note}
      </div>

      <div className="prose prose-sm max-w-none text-gray-800 [&_h2]:mt-4 [&_h2]:mb-2 [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:mb-1 [&_h3]:text-base [&_h3]:font-semibold [&_p]:mb-2 [&_ul]:mb-2 [&_ul]:list-disc [&_ul]:pl-5">
        <ReactMarkdown>{report.narrative}</ReactMarkdown>
      </div>

      {report.peers_used.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-gray-700">Listed peers used (live data)</h3>
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="w-full text-left text-sm">
              <thead className="bg-gray-50 text-gray-600">
                <tr>
                  <th className="px-3 py-2">Ticker</th>
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">EV/EBITDA</th>
                  <th className="px-3 py-2">EV/Revenue</th>
                  <th className="px-3 py-2">EBITDA Margin</th>
                  <th className="px-3 py-2">Source</th>
                </tr>
              </thead>
              <tbody>
                {report.peers_used.map((p) => (
                  <tr key={p.ticker} className="border-t border-gray-100">
                    <td className="px-3 py-2 font-medium">{p.ticker}</td>
                    <td className="px-3 py-2">{p.name}</td>
                    <td className="px-3 py-2">{fmtMultiple(p.ev_ebitda)}</td>
                    <td className="px-3 py-2">{fmtMultiple(p.ev_revenue)}</td>
                    <td className="px-3 py-2">{fmtPct(p.ebitda_margin)}</td>
                    <td className="px-3 py-2 text-xs text-gray-500">
                      {p.source}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {report.methodology_notes.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-gray-700">Methodology / audit trail</h3>
          <ul className="space-y-1 text-sm text-gray-600">
            {report.methodology_notes.map((note, i) => (
              <li key={i} className="border-l-2 border-gray-200 pl-3">
                {note}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
