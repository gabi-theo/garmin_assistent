import { useEffect, useState } from 'react'
import { getInsights } from '../api'

export default function Insights() {
  const [insights, setInsights] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getInsights(20)
      .then(setInsights)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <>
      <div className="page-header">
        <h1>AI Insights</h1>
        <p>Coaching observations generated from your biometric data</p>
      </div>
      {loading ? (
        <div className="loading">Loading insights…</div>
      ) : insights.length === 0 ? (
        <div className="empty">
          No insights yet. Make sure your Garmin poller is running.
        </div>
      ) : (
        <div className="insights-list">
          {insights.map(ins => (
            <div key={ins.id} className="insight-card">
              <div className="insight-header">
                <span className="metric-badge">{ins.metric}</span>
                {ins.anomaly_detected && (
                  <span className="anomaly-badge">
                    ⚠ Anomaly
                    {ins.deviation_pct != null
                      ? ` (${ins.deviation_pct.toFixed(1)}%)`
                      : ''}
                  </span>
                )}
              </div>
              <p className="insight-text">{ins.insight}</p>
              <p className="insight-meta">{new Date(ins.created_at).toLocaleString()}</p>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
