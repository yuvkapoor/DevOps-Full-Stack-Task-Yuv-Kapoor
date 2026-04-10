export default function ResultsTable({ data }) {
  if (!data?.length) return null
  const columns = Object.keys(data[0])

  return (
    <div className="table-wrapper">
      <table>
        <thead>
          <tr>{columns.map(c => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {data.slice(0, 50).map((row, i) => (
            <tr key={i}>
              {columns.map(c => (
                <td key={c}>
                  {row[c] === null ? <span style={{ color: '#4b5563' }}>null</span>
                    : typeof row[c] === 'number' ? row[c].toLocaleString()
                    : String(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {data.length > 50 && (
        <p style={{ color: '#64748b', fontSize: 12, padding: '8px 12px' }}>
          Showing 50 of {data.length} rows
        </p>
      )}
    </div>
  )
}