const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
).replace(/\/+$/, '')

function getErrorMessage(detail) {
  if (typeof detail === 'string') {
    return detail
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => item.msg)
      .filter(Boolean)
      .join(' ')
  }

  return ''
}

const REQUEST_TIMEOUT_MS = 20000

export async function postAuth(endpoint, payload) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  let response

  try {
    response = await fetch(`${API_BASE_URL}/api/v1/auth/${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error('The server took too long to respond. Check that the backend and database are running.')
    }
    throw new Error('Could not reach the server. Check your connection and try again.')
  } finally {
    clearTimeout(timer)
  }

  // A crashed backend can return plain text ("Internal Server Error"), not JSON.
  let result = {}
  try {
    result = await response.json()
  } catch {
    result = {}
  }

  if (!response.ok) {
    throw new Error(
      getErrorMessage(result.detail) ||
        (response.status >= 500
          ? 'Server error. Check the backend terminal for details.'
          : 'Something went wrong. Please try again.'),
    )
  }

  return result
}
