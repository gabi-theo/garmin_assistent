import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { saveGarmin } from '../api'

export default function GarminSetup() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setStatus(null)
    try {
      await saveGarmin(username, password)
      setStatus({ ok: true, msg: 'Credentials saved. Poller started!' })
      setTimeout(() => navigate('/'), 1500)
    } catch (err) {
      setStatus({ ok: false, msg: err.message })
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <div className="page-header">
        <h1>Garmin Setup</h1>
        <p>Connect your Garmin Connect account to start syncing biometric data.</p>
      </div>
      <div className="card" style={{ maxWidth: 480 }}>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Garmin Connect Email</label>
            <input
              type="email"
              value={username}
              onChange={e => setUsername(e.target.value)}
              required
              placeholder="you@example.com"
              autoFocus
            />
          </div>
          <div className="form-group">
            <label>Garmin Connect Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
          </div>
          <button className="btn" type="submit" disabled={loading}>
            {loading ? 'Saving…' : 'Save & Start Polling'}
          </button>
          {status && (
            <p
              className="error-msg"
              style={{ color: status.ok ? 'var(--success)' : 'var(--danger)' }}
            >
              {status.msg}
            </p>
          )}
        </form>
      </div>
    </>
  )
}
