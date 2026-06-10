import { useEffect, useState } from 'react'
import { getToken } from '../api'

function formatValue(metric, value) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') {
    if (metric === 'sleep') {
      const hrs = ((value.duration_seconds || 0) / 3600).toFixed(1)
      return `${hrs}h sleep, score ${value.score ?? 0}`
    }
    if (metric === 'activity') {
      return `${value.type ?? 'activity'} · ${Math.round(value.duration_minutes ?? 0)} min · ${Math.round(value.calories ?? 0)} kcal`
    }
    return JSON.stringify(value)
  }
  const units = { steps: 'steps', hrv: 'ms', stress: '/100', body_battery: '%', vo2max: 'ml/kg/min', heart_rate: 'bpm' }
  return `${Math.round(value)} ${units[metric] ?? ''}`
}

export default function LiveAlerts() {
  const [alerts, setAlerts] = useState([])

  useEffect(() => {
    const token = getToken()
    if (!token) return

    const ws = new WebSocket(`ws://localhost:8000/ws/live?token=${token}`)

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        const id = Date.now()
        setAlerts(prev => [...prev, { id, ...data }])
        setTimeout(() => setAlerts(prev => prev.filter(a => a.id !== id)), 8000)
      } catch {}
    }

    return () => ws.close()
  }, [])

  if (!alerts.length) return null

  return (
    <div className="alerts-container">
      {alerts.map(alert => {
        const isAnomaly = alert.anomaly_detected
        const title = `${isAnomaly ? '⚠ Anomaly' : '📡 Live'} — ${(alert.metric ?? '').toUpperCase()}`
        let body
        if (alert.insight) {
          body = alert.insight
        } else if (isAnomaly) {
          body = 'Anomaly detected — AI insight unavailable (Ollama starting up)'
        } else {
          body = formatValue(alert.metric, alert.value)
        }

        return (
          <div
            key={alert.id}
            className={`alert-toast${isAnomaly ? ' anomaly' : ''}`}
            onClick={() => setAlerts(prev => prev.filter(a => a.id !== alert.id))}
          >
            <div className="alert-title">{title}</div>
            <div style={{ fontSize: '0.82rem', opacity: 0.9, wordBreak: 'break-word' }}>{body}</div>
          </div>
        )
      })}
    </div>
  )
}
