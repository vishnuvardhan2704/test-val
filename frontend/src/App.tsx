import { useEffect, useState } from 'react'
import ChatWindow from './components/ChatWindow'
import ReportView from './components/ReportView'
import { createSession, type ChatResponse, type ValuationReport } from './api/client'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

function App() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [initialMessages, setInitialMessages] = useState<Message[]>([])
  const [report, setReport] = useState<ValuationReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    createSession()
      .then((res) => {
        setSessionId(res.session_id)
        setInitialMessages([{ role: 'assistant', content: res.message }])
      })
      .catch(() => setError('Could not reach the valuation server. Is the backend running?'))
  }, [])

  function handleReportReady(response: ChatResponse) {
    if (response.report) setReport(response.report)
  }

  return (
    <div className="min-h-screen bg-slate-100">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-6 py-4">
          <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">
            MV
          </div>
          <div>
            <h1 className="text-base font-semibold text-slate-900">MSME Valuation Agent</h1>
            <p className="text-xs text-slate-500">
              Multi-method valuation (EV/EBITDA, EV/Revenue, DCF) blended with live listed-peer and Screener.in data
            </p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
        )}

        {!error && !report && sessionId && (
          <div className="h-[75vh] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <ChatWindow sessionId={sessionId} initialMessages={initialMessages} onReportReady={handleReportReady} />
          </div>
        )}

        {report && <ReportView report={report} />}
      </main>

      <footer className="mx-auto max-w-5xl px-6 py-6 text-center text-xs text-slate-400">
        Estimates only — not a substitute for a certified valuer, chartered accountant, or audited financials.
      </footer>
    </div>
  )
}

export default App
