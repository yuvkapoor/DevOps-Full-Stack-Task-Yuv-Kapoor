import {
  BarChart, Bar, LineChart, Line, AreaChart, Area,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts'

const COLORS = ['#818cf8', '#34d399', '#f472b6', '#fbbf24', '#60a5fa', '#a78bfa', '#fb923c']

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: '#1e2139', border: '1px solid #2d3154', borderRadius: 8, padding: '10px 14px' }}>
      <p style={{ color: '#a78bfa', marginBottom: 4, fontSize: 13 }}>{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color, fontSize: 13 }}>
          {p.name}: <strong>{typeof p.value === 'number' ? p.value.toLocaleString() : p.value}</strong>
        </p>
      ))}
    </div>
  )
}

export default function ChartView({ data, chartType, xKey, yKey }) {
  if (!data?.length || chartType === 'none') return null

  // Auto-detect keys if not provided
  const keys = data.length ? Object.keys(data[0]) : []
  const resolvedX = xKey || keys[0]
  const resolvedY = yKey || keys[1]

  const axisStyle = { fill: '#64748b', fontSize: 12 }
  const gridStyle = { stroke: '#1e2139' }

  const commonProps = {
    data,
    margin: { top: 10, right: 20, left: 10, bottom: 40 }
  }

  const renderChart = () => {
    switch (chartType) {
      case 'bar':
        return (
          <BarChart {...commonProps}>
            <CartesianGrid strokeDasharray="3 3" {...gridStyle} />
            <XAxis dataKey={resolvedX} tick={axisStyle} angle={-35} textAnchor="end" interval={0} />
            <YAxis tick={axisStyle} />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ color: '#94a3b8', fontSize: 13 }} />
            <Bar dataKey={resolvedY} fill="#818cf8" radius={[4, 4, 0, 0]} name={resolvedY} />
          </BarChart>
        )

      case 'line':
        return (
          <LineChart {...commonProps}>
            <CartesianGrid strokeDasharray="3 3" {...gridStyle} />
            <XAxis dataKey={resolvedX} tick={axisStyle} angle={-35} textAnchor="end" interval={Math.floor(data.length / 8)} />
            <YAxis tick={axisStyle} />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ color: '#94a3b8', fontSize: 13 }} />
            <Line type="monotone" dataKey={resolvedY} stroke="#34d399" strokeWidth={2} dot={false} name={resolvedY} />
          </LineChart>
        )

      case 'area':
        return (
          <AreaChart {...commonProps}>
            <CartesianGrid strokeDasharray="3 3" {...gridStyle} />
            <XAxis dataKey={resolvedX} tick={axisStyle} angle={-35} textAnchor="end" interval={Math.floor(data.length / 8)} />
            <YAxis tick={axisStyle} />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ color: '#94a3b8', fontSize: 13 }} />
            <Area type="monotone" dataKey={resolvedY} stroke="#818cf8" fill="#1e2139" strokeWidth={2} name={resolvedY} />
          </AreaChart>
        )

      case 'pie':
        return (
          <PieChart margin={{ top: 10, right: 20, left: 10, bottom: 10 }}>
            <Pie
              data={data.slice(0, 8)}
              dataKey={resolvedY}
              nameKey={resolvedX}
              cx="50%" cy="50%"
              outerRadius={110}
              label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
              labelLine={{ stroke: '#475569' }}
            >
              {data.slice(0, 8).map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Pie>
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ color: '#94a3b8', fontSize: 13 }} />
          </PieChart>
        )

      default:
        return null
    }
  }

  return (
    <div className="chart-container">
      <ResponsiveContainer width="100%" height={320}>
        {renderChart()}
      </ResponsiveContainer>
    </div>
  )
}