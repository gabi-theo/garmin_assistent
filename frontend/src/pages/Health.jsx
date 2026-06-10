import { useEffect, useState, useCallback } from 'react'
import { getHealthStatus, triggerPoll } from '../api'

function StatusDot({ ok }) {
  return (
    <span style={{
      display: 'inline-block',
      width: 10,
      height: 10,
      borderRadius: '50%',
      background: ok ? 'var(--success)' : 'var(--danger)',
      marginRight: '0.5rem',
      flexShrink: 0,
    }} />
  )
}

function ServiceCard({ title, status, children }) {
  const ok = status === 'connected' || status === true
  return (
    <div className="card" style={{ marginBottom: '1rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '0.75rem' }}>
        <StatusDot ok={ok} />
        <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>{title}</span>
        <span style={{
          marginLeft: 'auto',
          fontSize: '0.78rem',
          fontWeight: 600,
          color: ok ? 'var(--success)' : 'var(--danger)',
          textTransform: 'uppercase',
        }}>
          {ok ? 'OK' : 'Error'}
        </span>
      </div>
      {children}
    </div>
  )
}

function Row({ label, value, valueColor }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '0.4rem' }}>
      <span style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span style={{ color: valueColor || 'var(--text)', fontFamily: 'monospace' }}>{value ?? '—'}</span>
    </div>
  )
}

export default function Health() {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [lastRefresh, setLastRefresh] = useState(null)
  const [polling, setPolling] = useState(false)
  const [pollResult, setPollResult] = useState(null)

  const refresh = useCallback(() => {
    setLoading(true)
    getHealthStatus()
      .then(data => {
        setStatus(data)
        setLastRefresh(new Date().toLocaleTimeString())
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  async function handlePoll() {
    setPolling(true)
    setPollResult(null)
    try {
      const res = await triggerPoll()
      setPollResult(res)
      setTimeout(refresh, 500)
    } catch (err) {
      setPollResult({ ok: false, error: err.message })
    } finally {
      setPolling(false)
    }
  }

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 15000)
    return () => clearInterval(interval)
  }, [refresh])

  const g = status?.garmin

  return (
    <>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1>System Health</h1>
          <p>Live status of backend services and Garmin connection</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          {lastRefresh && (
            <span style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>
              Updated {lastRefresh}
            </span>
          )}
          <button
            className="btn"
            style={{ width: 'auto', padding: '0.5rem 1.25rem', fontSize: '0.85rem', background: 'var(--accent-dim)' }}
            onClick={handlePoll}
            disabled={polling || !status?.garmin?.configured}
            title={!status?.garmin?.configured ? 'Configure Garmin credentials first' : ''}
          >
            {polling ? 'Polling…' : '⚡ Poll Now'}
          </button>
          <button
            className="btn"
            style={{ width: 'auto', padding: '0.5rem 1.25rem', fontSize: '0.85rem' }}
            onClick={refresh}
            disabled={loading}
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {pollResult && (
        <div style={{
          marginBottom: '1rem',
          padding: '0.75rem 1rem',
          borderRadius: 8,
          border: `1px solid ${pollResult.ok ? 'rgba(72,187,120,0.3)' : 'rgba(245,101,101,0.3)'}`,
          background: pollResult.ok ? 'rgba(72,187,120,0.08)' : 'rgba(245,101,101,0.08)',
          fontSize: '0.875rem',
          color: pollResult.ok ? 'var(--success)' : 'var(--danger)',
        }}>
          {pollResult.ok
            ? `✓ Poll complete — ${pollResult.published} metrics published to Kafka`
            : `✗ Poll failed — ${pollResult.error}`}
        </div>
      )}

      {loading && !status ? (
        <div className="loading">Checking services…</div>
      ) : status ? (
        <div style={{ maxWidth: 560 }}>

          {/* Database */}
          <ServiceCard title="PostgreSQL / TimescaleDB" status={status.database}>
            <Row label="Status" value={status.database} valueColor={status.database === 'connected' ? 'var(--success)' : 'var(--danger)'} />
          </ServiceCard>

          {/* Redis */}
          <ServiceCard title="Redis" status={status.redis}>
            <Row label="Status" value={status.redis} valueColor={status.redis === 'connected' ? 'var(--success)' : 'var(--danger)'} />
          </ServiceCard>

          {/* Garmin */}
          <ServiceCard title="Garmin Connect" status={g?.configured && g?.running}>
            <Row label="Credentials" value={g?.configured ? 'Configured' : 'Not configured'} valueColor={g?.configured ? 'var(--success)' : 'var(--warn)'} />
            {g?.account && <Row label="Account" value={g.account} />}
            <Row
              label="Poller"
              value={!g?.configured ? 'N/A' : g?.running ? 'Running' : g?.crashed ? 'Crashed' : 'Stopped'}
              valueColor={g?.running ? 'var(--success)' : g?.configured ? 'var(--danger)' : 'var(--text-muted)'}
            />
            {g?.last_poll_at && (
              <Row label="Last poll" value={new Date(g.last_poll_at).toLocaleString()} />
            )}
            {g?.metrics_count != null && g?.last_poll_at && (
              <Row label="Metrics published" value={`${g.metrics_count} metrics`} />
            )}
            {g?.error_count > 0 && (
              <Row label="Error count" value={g.error_count} valueColor="var(--danger)" />
            )}
            {g?.last_error && (
              <div style={{
                marginTop: '0.75rem',
                padding: '0.6rem 0.75rem',
                background: 'rgba(245,101,101,0.08)',
                border: '1px solid rgba(245,101,101,0.2)',
                borderRadius: 8,
                fontSize: '0.8rem',
                color: 'var(--danger)',
                wordBreak: 'break-word',
              }}>
                {g.last_error}
              </div>
            )}
            {g?.configured && !g?.running && !g?.crashed && (
              <p style={{ marginTop: '0.75rem', fontSize: '0.82rem', color: 'var(--text-muted)' }}>
                Poller not running. Go to <a href="/setup" style={{ color: 'var(--accent)' }}>Garmin Setup</a> to reconnect.
              </p>
            )}
          </ServiceCard>

        </div>
      ) : (
        <div className="empty">Could not fetch status.</div>
      )}
    </>
  )
}
