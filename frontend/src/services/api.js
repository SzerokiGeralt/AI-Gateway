import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default api

/**
 * Stream chat completions via SSE.
 * The backend sends: data: {text chunk}\n\n  and  data: [DONE]\n\n
 */
export async function streamChat(messages, onChunk, onDone, onError) {
  const token = localStorage.getItem('token')

  let response
  try {
    response = await fetch('/api/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ messages }),
    })
  } catch (err) {
    onError('Nie można połączyć się z serwerem.')
    return
  }

  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
      return
    }
    if (response.status === 429) {
      onError('Przekroczono limit zapytań. Spróbuj za chwilę.')
      return
    }
    let detail = `Błąd HTTP ${response.status}`
    try {
      const body = await response.json()
      detail = body.detail || detail
    } catch (_) {}
    onError(detail)
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEventLines = []

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() // keep incomplete trailing line

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          currentEventLines.push(line.slice(6))
        } else if (line === '' && currentEventLines.length > 0) {
          const content = currentEventLines.join('\n')
          currentEventLines = []
          if (content === '[DONE]') {
            onDone()
            return
          }
          onChunk(content)
        }
      }
    }
  } catch (err) {
    onError('Przerwano połączenie podczas strumieniowania.')
    return
  }

  onDone()
}
