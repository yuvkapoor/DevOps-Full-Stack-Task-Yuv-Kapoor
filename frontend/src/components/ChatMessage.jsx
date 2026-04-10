import ChartView from './ChartView'
import ResultsTable from './ResultsTable'
import { useState } from 'react'

export default function ChatMessage({ msg }) {
  const [showSql, setShowSql] = useState(false)
  const [showGraph, setShowGraph] = useState(false)
  const [showTable, setShowTable] = useState(false)

  if (msg.role === 'user') {
    return (
      <div className="message-row user">
        <div className="chat-bubble-user">{msg.content}</div>
      </div>
    )
  }

  const tagClass = `tag tag-${msg.chart_type || 'none'}`
  const hasData = Array.isArray(msg.data) && msg.data.length > 0
  const hasChart = hasData && msg.chart_type && msg.chart_type !== 'none'

  return (
    <div className="message-row assistant">
      <div className="message-avatar assistant">S</div>
      <div className="message-content">
        <div className="chat-bubble-ai">
          <p className="message-text">{msg.content}</p>

          {msg.sql && (
            <div className="toggle-block">
              <button
                onClick={() => setShowSql(!showSql)}
                className="toggle-button"
              >
                {showSql ? 'Hide SQL' : 'Show SQL'}
              </button>
              {showSql && <div className="sql-block">{msg.sql}</div>}
            </div>
          )}

          {hasData && (
            <div className="result-section">
              <div className="result-meta">
                <span>{msg.data.length} rows</span>
                {msg.chart_type && msg.chart_type !== 'none' && (
                  <span className={tagClass}>{msg.chart_type} chart</span>
                )}
              </div>

              {hasChart && (
                <div className="toggle-block">
                  <button
                    onClick={() => setShowGraph(!showGraph)}
                    className="toggle-button"
                  >
                    {showGraph ? 'Hide graph' : 'Show graph'}
                  </button>
                  {showGraph && (
                    <ChartView
                      data={msg.data}
                      chartType={msg.chart_type}
                      xKey={msg.x_key}
                      yKey={msg.y_key}
                    />
                  )}
                </div>
              )}

              <div className="toggle-block">
                <button
                  onClick={() => setShowTable(!showTable)}
                  className="toggle-button"
                >
                  {showTable ? 'Hide table' : 'Show table'}
                </button>
                {showTable && <ResultsTable data={msg.data} />}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
