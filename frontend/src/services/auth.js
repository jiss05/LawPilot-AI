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

export async function postAuth(endpoint, payload) {
  let response

  try {
    response = await fetch(`${API_BASE_URL}/api/v1/auth/${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  } catch {
    throw new Error('Could not reach the server. Check your connection and try again.')
  }

  const result = await response.json()

  if (!response.ok) {
    throw new Error(
      getErrorMessage(result.detail) || 'Something went wrong. Please try again.',
    )
  }

  return result
}
