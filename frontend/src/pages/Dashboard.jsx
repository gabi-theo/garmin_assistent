import { useEffect, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { getMetrics } from '../api'

const METRICS = [
  { key: 'steps',        label: 'Steps',        unit: 'steps', color: '#00d4aa' },
  { key: 'sleep',        label: 'Sleep Score',  unit: 'pts',   color: '#667eea' },
  { key: 'stress',       label: 'Stress',       unit: '',      color: '#ed8936' },
  { key: 'body_battery', label: 'Body Battery', unit: '%',     color: '#48bb78' },
  { key: 'hrv',          label: 'HRV',          unit: 'ms',    color: '#9f7aea' },
  { key: 'vo2max',       label: 'VO2 Max',      unit: 'ml/kg', color: '#f56565' },
]

function extractValue(raw) {
  if (raw === null || raw === undefined) return null
  if (typeof raw === 'number') return raw
  if (typeof raw === 'object') {
    return raw.score ?? raw.avg_value ?? raw.duration_minutes ?? raw.duration_seconds ?? Object.values(raw)[0] ?? null
  }
  return parseFloat(raw) || null
}

function MetricCard({ metric, days }) {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    getMetrics(metric.key, days)
      .then(rows =>
        setData(
          rows
            .map(r => ({
              time: new Date(r.time).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
              value: extractValue(r.value),
            }))
            .filter(r => r.value !== null)
        )
      )
      .catch(() => setData([]))
      .finally(() => setLoading(false))
  }, [metric.key, days])

  return (
    <div className="card">
      <h2>
        {metric.label}
        {metric.unit && (
          <span style={{ marginLeft: '0.4rem', fontWeight: 400 }}>({metric.unit})</span>
        )}
      </h2>
      {loading ? (
        <div className="loading">Loading…</div>
      ) : data.length === 0 ? (
        <div className="empty">No data yet</div>
      ) : (
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis dataKey="time" tick={{ fill: '#8892a4', fontSize: 11 }} />
            <YAxis tick={{ fill: '#8892a4', fontSize: 11 }} width={40} />
            <Tooltip
              contentStyle={{ background: '#1a1d27', border: '1px solid #2a2d3d', borderRadius: 8 }}
              labelStyle={{ color: '#e2e8f0' }}
              itemStyle={{ color: metric.color }}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke={metric.color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

export default function Dashboard() {
  const [days, setDays] = useState(7)

  return (
    <>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1>Dashboard</h1>
          <p>Your biometric metrics over time</p>
        </div>
        <select value={days} onChange={e => setDays(Number(e.target.value))} style={{ width: 150 }}>
          <option value={7}>Last 7 days</option>
          <option value={14}>Last 14 days</option>
          <option value={30}>Last 30 days</option>
        </select>
      </div>
      <div className="metrics-grid">
        {METRICS.map(m => <MetricCard key={m.key} metric={m} days={days} />)}
      </div>
    </>
  )
}
