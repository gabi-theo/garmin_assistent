const BASE = 'http://localhost:8000'

export const getToken = () => localStorage.getItem('token')
export const setToken = (t) => localStorage.setItem('token', t)
export const clearToken = () => localStorage.removeItem('token')

function authHeaders() {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${getToken()}`,
  }
}

async function req(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { ...authHeaders(), ...opts.headers },
    ...opts,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || res.statusText)
  }
  return res.json()
}

export const register = (email, password) =>
  req('/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) })

export const login = async (email, password) => {
  const data = await req('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  setToken(data.access_token)
  return data
}

export const logout = () =>
  req('/auth/logout', { method: 'POST' }).finally(clearToken)

export const saveGarmin = (username, password) =>
  req('/auth/garmin', { method: 'POST', body: JSON.stringify({ username, password }) })

export const getMetrics = (metric, days = 7, bucket = '1 day') =>
  req(`/metrics/${metric}?days=${days}&bucket=${encodeURIComponent(bucket)}`)

export const getInsights = (limit = 20) =>
  req(`/insights/latest?limit=${limit}`)

export const getHealthStatus = () =>
  req('/health/status')

export const triggerPoll = () =>
  req('/health/poll', { method: 'POST' })

export async function* streamChat(metric, question) {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ metric, question }),
  })
  if (!res.ok) throw new Error('Chat request failed')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6)
        if (data === '[DONE]') return
        yield data
      }
    }
  }
}
