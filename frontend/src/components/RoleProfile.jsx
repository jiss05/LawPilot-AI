
import { useEffect, useState } from 'react'
import {
  UserRound,
  Mail,
  ShieldCheck,
  CalendarDays,
  CheckCircle,
  XCircle,
} from 'lucide-react'

import api from '../services/api'
import './RoleProfile.css'

function RoleProfile() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const fetchProfile = async () => {
      try {
        const response = await api.get('/users/me')
        setUser(response.data)
      } catch (err) {
        setError(
          err.response?.data?.detail ||
          'Unable to load profile information.'
        )
      } finally {
        setLoading(false)
      }
    }

    fetchProfile()
  }, [])

  const formatDate = (date) => {
    if (!date) return 'Not available'

    return new Date(date).toLocaleDateString('en-IN', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    })
  }

  if (loading) {
    return <div className="role-profile-page">Loading profile...</div>
  }

  if (error) {
    return <div className="role-profile-error">{error}</div>
  }

  if (!user) return null

  const displayName = user.display_name || user.full_name || 'User'

  return (
    <div className="role-profile-page">
      <div className="role-profile-heading">
        <h1>My Profile</h1>
        <p>View your account information.</p>
      </div>

      <div className="role-profile-card">
        <div className="role-profile-header">
          <div className="role-profile-avatar">
            <UserRound size={32} />
          </div>

          <div>
            <h2>{displayName}</h2>
            <p>{user.email}</p>
            <span className="role-profile-role">
              <ShieldCheck size={14} />
              {user.role}
            </span>
          </div>
        </div>

        <div className="role-profile-divider" />

        <div className="role-profile-details">
          <div className="role-profile-detail">
            <UserRound size={19} />
            <div>
              <span>Full Name</span>
              <p>{displayName}</p>
            </div>
          </div>

          <div className="role-profile-detail">
            <Mail size={19} />
            <div>
              <span>Email Address</span>
              <p>{user.email || 'Not available'}</p>
            </div>
          </div>

          <div className="role-profile-detail">
            <ShieldCheck size={19} />
            <div>
              <span>Account Role</span>
              <p>{user.role || 'Not available'}</p>
            </div>
          </div>

          <div className="role-profile-detail">
            <CalendarDays size={19} />
            <div>
              <span>Account Created</span>
              <p>{formatDate(user.created_at)}</p>
            </div>
          </div>

          <div className="role-profile-detail">
            {user.is_active ? (
              <CheckCircle size={19} />
            ) : (
              <XCircle size={19} />
            )}
            <div>
              <span>Account Status</span>
              <p>{user.is_active ? 'Active' : 'Inactive'}</p>
            </div>
          </div>

          <div className="role-profile-detail">
            {user.email_verified ? (
              <CheckCircle size={19} />
            ) : (
              <XCircle size={19} />
            )}
            <div>
              <span>Email Verification</span>
              <p>{user.email_verified ? 'Verified' : 'Not Verified'}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default RoleProfile
