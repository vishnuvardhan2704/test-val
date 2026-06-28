interface Props {
  role: 'user' | 'assistant'
  content: string
}

export default function MessageBubble({ role, content }: Props) {
  const isUser = role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[75%] rounded-2xl px-4 py-2.5 whitespace-pre-wrap text-sm leading-relaxed shadow-sm ${
          isUser ? 'bg-indigo-600 text-white' : 'border border-slate-100 bg-slate-50 text-slate-800'
        }`}
      >
        {content}
      </div>
    </div>
  )
}
