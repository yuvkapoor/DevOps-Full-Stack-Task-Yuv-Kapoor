import { useState } from 'react'

export default function DevOpsPanel({ api }) {
  const [token, setToken] = useState('')
  const [service, setService] = useState('backend')
  const [ciLog, setCiLog] = useState('')
  const [result, setResult] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const headers = token ? { 'X-DevOps-Token': token } : {}

  const runAction = async (label, request) => {
    setLoading(true)
    setError('')
    try {
      const response = await request()
      const summary = response.data?.summary || `${label} completed.`
      const extras = { ...response.data }
      delete extras.summary
      setResult(
        `${summary}\n\n${JSON.stringify(extras, null, 2)}`
      )
    } catch (err) {
      const detail = err.response?.data?.detail || `Failed to ${label.toLowerCase()}.`
      setError(detail)
      setResult('')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="devops-card">
      <div className="devops-header">
        <div>
          <h3>DevOps Agent</h3>
          <p>Diagnose, restart, summarize logs, and explain CI/CD failures.</p>
        </div>
        <span className="devops-badge">Bonus</span>
      </div>

      <label className="devops-label">
        DevOps token
        <input
          type="password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="Enter DEVOPS_AGENT_TOKEN"
        />
      </label>

      <div className="devops-grid">
        <button
          className="devops-button"
          disabled={loading}
          onClick={() =>
            runAction('Diagnose stack', () => api.get('/api/devops/diagnose', { headers }))
          }
        >
          Diagnose stack
        </button>
        <button
          className="devops-button"
          disabled={loading}
          onClick={() =>
            runAction('Summarize backend logs', () =>
              api.post(
                '/api/devops/logs',
                { service, tail: 120, errors_only: false },
                { headers }
              )
            )
          }
        >
          Summarize logs
        </button>
        <button
          className="devops-button"
          disabled={loading}
          onClick={() =>
            runAction(`Restart ${service}`, () =>
              api.post('/api/devops/restart', { services: [service] }, { headers })
            )
          }
        >
          Restart service
        </button>
        <button
          className="devops-button"
          disabled={loading}
          onClick={() =>
            runAction('Trigger deploy', () => api.post('/api/devops/deploy', {}, { headers }))
          }
        >
          Trigger deploy
        </button>
      </div>

      <label className="devops-label">
        Service
        <input
          type="text"
          value={service}
          onChange={(event) => setService(event.target.value)}
          placeholder="backend, nginx, frontend..."
        />
      </label>

      <label className="devops-label">
        Explain CI/CD failure
        <textarea
          rows={5}
          value={ciLog}
          onChange={(event) => setCiLog(event.target.value)}
          placeholder="Paste failing GitHub Actions log excerpt here..."
        />
      </label>

      <button
        className="devops-button devops-button-wide"
        disabled={loading || !ciLog.trim()}
        onClick={() =>
          runAction('Explain CI failure', () =>
            api.post('/api/devops/explain-ci', { log_text: ciLog }, { headers })
          )
        }
      >
        Explain CI failure
      </button>

      {loading && <div className="devops-note">Working on it...</div>}
      {error && <div className="devops-error">{error}</div>}
      {result && <pre className="devops-result">{result}</pre>}
      <div className="devops-note">
        Tip: the deploy button needs `GITHUB_ACTIONS_TOKEN` and `GITHUB_REPO` configured in
        `backend/.env`.
      </div>
    </div>
  )
}
