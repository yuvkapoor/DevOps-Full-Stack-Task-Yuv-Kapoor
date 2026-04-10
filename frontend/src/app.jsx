import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import ChatMessage from './components/ChatMessage'
import QueryHistory from './components/QueryHistory'

const SUGGESTIONS = [
  'Show top trending topics in last 30 days',
  'Compare article engagement by topic',
  'Plot daily views trend for AI articles',
  'Which author has the most views?',
  'Show top 5 articles by likes',
  'What countries have the most readers?',
]

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
})

export default function App() {
  const [apiHealth, setApiHealth] = useState({ status: 'checking', translator: 'rules' })
  const [messages, setMessages] = useState([
    {
      role: 'ai',
      content:
        "Hi, I'm SupaChat. Ask for trends, engagement, countries, authors, or article performance and I'll turn that into analytics queries for your Supabase PostgreSQL data.",
      data: [],
      chart_type: 'none',
      sql: null,
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState([])
  const [errorMessage, setErrorMessage] = useState('')
  const bottomRef = useRef(null)
  const translatorLabel = (apiHealth.translator || 'rules_only').replaceAll('_', ' ')

  const loadHistory = async () => {
    try {
      const response = await api.get('/api/history')
      setHistory(response.data.history || [])
    } catch (error) {
      console.error('Failed to load history', error)
    }
  }

  const loadHealth = async () => {
    try {
      const response = await api.get('/health')
      setApiHealth(response.data)
      setErrorMessage('')
    } catch (error) {
      setApiHealth({ status: 'offline', translator: 'rules' })
      setErrorMessage('Backend is not reachable yet. Start the FastAPI server on port 8000.')
    }
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  useEffect(() => {
    loadHistory()
    loadHealth()
    const timer = window.setInterval(loadHealth, 20000)
    return () => window.clearInterval(timer)
  }, [])

  const sendMessage = async (text = input) => {
    if (!text.trim() || loading) return

    const userMsg = text.trim()
    setInput('')
    setErrorMessage('')
    setMessages((current) => [...current, { role: 'user', content: userMsg }])
    setLoading(true)

    try {
      const { data } = await api.post('/api/chat', { message: userMsg })
      setMessages((current) => [
        ...current,
        {
          role: 'ai',
          content: data.text,
          sql: data.sql,
          data: data.data,
          chart_type: data.chart_type,
          x_key: data.x_key,
          y_key: data.y_key,
        },
      ])
      await loadHistory()
      await loadHealth()
    } catch (error) {
      const detail =
        error.response?.data?.detail ||
        'Server error. Check the backend and database settings.'
      setErrorMessage(detail)
      setMessages((current) => [
        ...current,
        {
          role: 'ai',
          content: `Error: ${detail}`,
          data: [],
          chart_type: 'none',
          sql: null,
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <h1>SupaChat</h1>
          <p>Conversational analytics for your blog database.</p>
          <div
            className={`status-pill ${
              apiHealth.status === 'offline'
                ? 'offline'
                : apiHealth.status === 'degraded'
                  ? 'degraded'
                  : ''
            }`}
          >
            <span className="status-dot" />
            {apiHealth.status === 'healthy'
              ? 'Database connected'
              : apiHealth.status === 'degraded'
                ? 'Database degraded'
                : apiHealth.status === 'offline'
                  ? 'Backend offline'
                  : 'Checking backend'}
          </div>
        </div>

        <div className="sidebar-section">
          <h2>Try asking</h2>
          <div className="suggestion-list">
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                className="suggestion-button"
                onClick={() => sendMessage(suggestion)}
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>

        <div className="sidebar-section" style={{ paddingBottom: 10 }}>
          <h2>Query history</h2>
        </div>
        <div className="history-scroll">
          <QueryHistory history={history} onSelect={(query) => sendMessage(query)} />
        </div>
      </aside>

      <main className="workspace">
        <div className="workspace-header">
          <div>
            <h2>Ask analytics questions in plain English</h2>
            <p>Each response includes a summary, generated SQL, a chart, and a result table.</p>
          </div>
          <div className="translator-chip">
            Translator: {translatorLabel}
          </div>
        </div>

        {errorMessage && <div className="error-banner">{errorMessage}</div>}

        <div className="message-list">
          {messages.map((msg, index) => (
            <ChatMessage key={index} msg={msg} />
          ))}

          {loading && (
            <div className="loading-row">
              <div className="message-avatar assistant">SC</div>
              <div className="panel">
                <div className="loading-dots">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        <div className="composer">
          <div className="composer-form">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  sendMessage()
                }
              }}
              placeholder="Ask about your blog analytics. Example: Plot daily views trend for AI articles."
              disabled={loading}
              rows={3}
            />
            <button
              className="send-button"
              onClick={() => sendMessage()}
              disabled={loading || !input.trim()}
            >
              {loading ? 'Working...' : 'Run query'}
            </button>
          </div>
          <div className="composer-footnote">
            Press Enter to send, or Shift+Enter for a new line.
          </div>
        </div>
      </main>
    </div>
  )
}
