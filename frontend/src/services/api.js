import axios from 'axios'

const api = axios.create({
  // Same setting as services/auth.js: set VITE_API_BASE_URL for any server
  // other than a local backend on port 8000.
  baseURL: `${(import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')}/api/v1`,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Automatically attach JWT token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')

  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }

  return config
})

// An expired or invalid session sends the user back to the login page
// instead of leaving the screen half-loaded (SCRUM-28 error states).
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    const url = error.config?.url || ''
    const isAuthCall = url.includes('/auth/')

    if (status === 401 && !isAuthCall) {
      localStorage.removeItem('access_token')
      if (window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
    }

    return Promise.reject(error)
  },
)

export default api
