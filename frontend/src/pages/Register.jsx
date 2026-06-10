import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { register, login } from '../api'

export default function Register() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await register(email, password)
      await login(email, password)
      navigate('/setup')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>Create account</h1>
        <p>Start tracking your Garmin health data</p>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoFocus />
          </div>
          <div className="form-group">
            <label>
              Password{' '}
              <span style={{ color: 'var(--text-muted)' }}>(min 6 chars)</span>
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              minLength={6}
            />
          </div>
          <button className="btn" type="submit" disabled={loading}>
            {loading ? 'Creating account…' : 'Create account'}
          </button>
          {error && <p className="error-msg">{error}</p>}
        </form>
        <div className="auth-footer">
          Already have an account? <Link to="/login" className="link">Sign in</Link>
        </div>
      </div>
    </div>
  )
}
