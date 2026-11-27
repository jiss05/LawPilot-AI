import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { LoaderCircle } from 'lucide-react'
import api from '../services/api'

const HOME_BY_ROLE = {
  ADMIN: '/admin',
  CLIENT: '/client',
  LAWYER: '/lawyer',
  JUDGE: '/judge',
}

/**
 * Only render a workspace for users whose role matches it (SCRUM-28:
 * "Users access the correct role-specific workspace"). Anyone else is sent
 * to their own workspace; signed-out users go to the login page.
 * The backend enforces the same rules on every API call.
 */
function RequireRole({ role, children }) {
  const hasToken = Boolean(localStorage.getItem('access_token'))
  const [state, setState] = useState({ loading: hasToken, userRole: null })

  useEffect(() => {
    if (!hasToken) return undefined
    let active = true

    api
      .get('/users/me')
      .then((response) => {
        if (active) setState({ loading: false, userRole: response.data?.role || null })
      })
      .catch(() => {
        if (active) setState({ loading: false, userRole: null })
      })

    return () => {
      active = false
    }
  }, [hasToken])

  if (!hasToken) return <Navigate to="/login" replace />

  if (state.loading) {
    return (
      <div className="route-guard-loading">
        <LoaderCircle size={22} className="assistant-spinner" />
        <span>Loading your workspace...</span>
      </div>
    )
  }

  if (!state.userRole) return <Navigate to="/login" replace />

  if (state.userRole !== role) {
    return <Navigate to={HOME_BY_ROLE[state.userRole] || '/login'} replace />
  }

  return children
}

export default RequireRole
