import { useEffect, useRef, useState } from 'react'
import MessageBubble from './MessageBubble'
import { sendMessage, type ChatResponse } from '../api/client'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

interface Props {
  sessionId: string
  initialMessages: Message[]
  onReportReady: (response: ChatResponse) => void
}

export default function ChatWindow({ sessionId, initialMessages, onReportReady }: Props) {
  const [messages, setMessages] = useState<Message[]>(initialMessages)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSend() {
    const text = input.trim()
    if (!text || sending) return
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setSending(true)
    try {
      const response = await sendMessage(sessionId, text)
      setMessages((prev) => [...prev, { role: 'assistant', content: response.message }])
      if (response.stage === 'report_ready' && response.report) {
        onReportReady(response)
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Something went wrong reaching the server. Please try again.' },
      ])
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {messages.map((m, i) => (
          <MessageBubble key={i} role={m.role} content={m.content} />
        ))}
        {sending && <MessageBubble role="assistant" content="Thinking..." />}
        <div ref={bottomRef} />
      </div>
      <div className="flex gap-2 border-t border-gray-200 p-3">
        <input
          className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
          value={input}
          placeholder="Type your answer or paste your company website..."
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleSend()
          }}
          disabled={sending}
        />
        <button
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          onClick={handleSend}
          disabled={sending || !input.trim()}
        >
          Send
        </button>
      </div>
    </div>
  )
}
