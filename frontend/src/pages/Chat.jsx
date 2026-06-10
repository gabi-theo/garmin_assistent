import { useState, useRef, useEffect } from 'react'
import { streamChat } from '../api'

const METRICS = [
  'heart_rate', 'sleep', 'stress', 'steps',
  'body_battery', 'hrv', 'activity', 'vo2max',
]

export default function Chat() {
  const [messages, setMessages] = useState([])
  const [metric, setMetric] = useState('heart_rate')
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSend(e) {
    e.preventDefault()
    if (!input.trim() || streaming) return

    const question = input.trim()
    setInput('')
    setMessages(prev => [
      ...prev,
      { role: 'user', text: question },
      { role: 'assistant', text: '' },
    ])
    setStreaming(true)

    try {
      for await (const token of streamChat(metric, question)) {
        setMessages(prev => {
          const next = [...prev]
          const last = next[next.length - 1]
          next[next.length - 1] = { ...last, text: last.text + token }
          return next
        })
      }
    } catch (err) {
      setMessages(prev => {
        const next = [...prev]
        next[next.length - 1] = { ...next[next.length - 1], text: `Error: ${err.message}` }
        return next
      })
    } finally {
      setStreaming(false)
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>AI Chat</h1>
        <p>Ask questions about your health data</p>
      </div>
      <div className="chat-container">
        <div className="chat-controls">
          <select value={metric} onChange={e => setMetric(e.target.value)}>
            {METRICS.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          <span>Metric context</span>
        </div>
        <div className="chat-messages">
          {messages.length === 0 && (
            <div className="empty" style={{ padding: '2rem 0' }}>
              Ask anything — e.g. "How was my sleep last week?" or "Any anomalies in my HRV?"
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`chat-bubble ${msg.role}`}>
              {msg.text || (msg.role === 'assistant' && streaming ? '▌' : '')}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
        <form className="chat-input-row" onSubmit={handleSend}>
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask about your health data…"
            disabled={streaming}
            autoFocus
          />
          <button className="btn" type="submit" disabled={!input.trim() || streaming}>
            {streaming ? '…' : 'Send'}
          </button>
        </form>
      </div>
    </>
  )
}
