// Backend base URL. VITE_* variables are bundled into the public site, so never put secrets in them.
const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

const ERRORS = {
  401: 'Wrong demo key.',
  413: 'That request is too large.',
  422: 'Please check your input.',
  429: 'Too many requests. Wait a minute and try again.',
  502: 'The model call failed. Try again.',
  503: 'Live calls are turned off on the server.',
}

async function post(path, body, headers = {}) {
  let res
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify(body),
    })
  } catch {
    throw new Error("Can't reach the server. Is the backend running?")
  }
  if (!res.ok) throw new Error(ERRORS[res.status] || `Request failed (${res.status}).`)
  return res.json()
}

export const pickModel = (prompt) => post('/pick-model', { prompt })

export const route = (weights, numCalls = 1000) =>
  post('/route', { provider: 'azure', num_calls: numCalls, weights })

// The demo key is typed in by the presenter and only kept in memory, never stored or bundled.
export const complete = (prompt, weights, demoKey) =>
  post('/complete', { prompt, weights }, { 'X-Demo-Token': demoKey })
