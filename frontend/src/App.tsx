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
    <div className="min-h-screen bg-gray-50">
      <header className="border-b border-gray-200 bg-white px-6 py-4">
        <h1 className="text-lg font-semibold text-gray-900">MSME Valuation Assistant</h1>
        <p className="text-sm text-gray-500">Conversational valuation using live listed-peer data</p>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-6">
        {error && <p className="text-sm text-red-600">{error}</p>}

        {!error && !report && sessionId && (
          <div className="h-[70vh] rounded-xl border border-gray-200 bg-white shadow-sm">
            <ChatWindow sessionId={sessionId} initialMessages={initialMessages} onReportReady={handleReportReady} />
          </div>
        )}

        {report && (
          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <ReportView report={report} />
          </div>
        )}
      </main>
    </div>
  )
}

export default App
