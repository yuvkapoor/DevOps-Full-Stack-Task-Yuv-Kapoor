export default function QueryHistory({ history, onSelect }) {
  if (!history.length) return (
    <div className="history-empty">
      No queries yet
    </div>
  )

  return (
    <div>
      {history.map(h => (
        <div key={h.id} className="history-item" onClick={() => onSelect(h.query)}>
          <p style={{ fontSize: 13, marginBottom: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {h.query}
          </p>
          <div className="history-meta">
            <span>
              {new Date(h.timestamp).toLocaleTimeString()}
            </span>
            {h.row_count > 0 && (
              <span>{h.row_count} rows</span>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
