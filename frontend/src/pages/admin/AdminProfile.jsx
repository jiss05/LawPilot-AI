
import { useEffect, useState } from 'react'
import {
  UserRound,
  Mail,
  ShieldCheck,
  CalendarDays,
  CheckCircle,
  XCircle,
  LockKeyhole,
  Eye,
  EyeOff,
} from 'lucide-react'

import api from '../../services/api'
import './AdminProfile.css'

function AdminProfile() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  const [showCurrentPassword, setShowCurrentPassword] = useState(false)
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)

  const [passwordLoading, setPasswordLoading] = useState(false)
  const [passwordError, setPasswordError] = useState('')
  const [passwordSuccess, setPasswordSuccess] = useState('')

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

    return new Date(date).toLocaleDateString(
      'en-IN',
      {
        day: 'numeric',
        month: 'long',
        year: 'numeric',
      }
    )
  }

  const handlePasswordChange = async (event) => {
    event.preventDefault()

    setPasswordError('')
    setPasswordSuccess('')

    if (newPassword.length < 8) {
      setPasswordError(
        'New password must be at least 8 characters long.'
      )
      return
    }

    if (newPassword !== confirmPassword) {
      setPasswordError(
        'New password and confirmation do not match.'
      )
      return
    }

    if (currentPassword === newPassword) {
      setPasswordError(
        'New password must be different from current password.'
      )
      return
    }

    setPasswordLoading(true)

    try {
      const response = await api.post(
        '/users/me/change-password',
        {
          current_password: currentPassword,
          new_password: newPassword,
          confirm_password: confirmPassword,
        }
      )

      setPasswordSuccess(
        response.data.message || 'Password changed successfully.'
      )

      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      setPasswordError(
        err.response?.data?.detail ||
        'Unable to change password. Please try again.'
      )
    } finally {
      setPasswordLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="admin-profile-page">
        <p className="admin-profile-loading">
          Loading profile...
        </p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="admin-profile-page">
        <div className="admin-profile-error">
          {error}
        </div>
      </div>
    )
  }

  if (!user) {
    return null
  }

  return (
    <div className="admin-profile-page">
      <div className="admin-profile-heading">
        <div>
          <h1>My Profile</h1>
          <p>View your account information and manage security.</p>
        </div>
      </div>

      {/* Profile Information */}
      <div className="admin-profile-card">
        <div className="admin-profile-header">
          <div className="admin-profile-avatar">
            <UserRound size={32} />
          </div>

          <div className="admin-profile-identity">
            <h2>{user.display_name}</h2>
            <p>{user.email}</p>

            <span className="admin-profile-role">
              <ShieldCheck size={14} />
              Administrator
            </span>
          </div>
        </div>

        <div className="admin-profile-divider" />

        <div className="admin-profile-details">
          <div className="admin-profile-detail">
            <div className="admin-profile-detail-icon">
              <UserRound size={18} />
            </div>

            <div>
              <span>Full Name</span>
              <p>{user.display_name || 'Not available'}</p>
            </div>
          </div>

          <div className="admin-profile-detail">
            <div className="admin-profile-detail-icon">
              <Mail size={18} />
            </div>

            <div>
              <span>Email Address</span>
              <p>{user.email || 'Not available'}</p>
            </div>
          </div>

          <div className="admin-profile-detail">
            <div className="admin-profile-detail-icon">
              <ShieldCheck size={18} />
            </div>

            <div>
              <span>Account Role</span>
              <p>{user.role || 'Not available'}</p>
            </div>
          </div>

          <div className="admin-profile-detail">
            <div className="admin-profile-detail-icon">
              <CalendarDays size={18} />
            </div>

            <div>
              <span>Account Created</span>
              <p>{formatDate(user.created_at)}</p>
            </div>
          </div>

          <div className="admin-profile-detail">
            <div className="admin-profile-detail-icon">
              {user.is_active ? (
                <CheckCircle size={18} />
              ) : (
                <XCircle size={18} />
              )}
            </div>

            <div>
              <span>Account Status</span>
              <p>{user.is_active ? 'Active' : 'Inactive'}</p>
            </div>
          </div>

          <div className="admin-profile-detail">
            <div className="admin-profile-detail-icon">
              {user.email_verified ? (
                <CheckCircle size={18} />
              ) : (
                <XCircle size={18} />
              )}
            </div>

            <div>
              <span>Email Verification</span>
              <p>
                {user.email_verified
                  ? 'Verified'
                  : 'Not Verified'}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Change Password */}
      <div className="admin-profile-card admin-password-card">
        <div className="admin-password-heading">
          <div className="admin-password-heading-icon">
            <LockKeyhole size={21} />
          </div>

          <div>
            <h2>Change Password</h2>
            <p>
              Update your password to keep your account secure.
            </p>
          </div>
        </div>

        {passwordError && (
          <div className="admin-password-message error">
            {passwordError}
          </div>
        )}

        {passwordSuccess && (
          <div className="admin-password-message success">
            {passwordSuccess}
          </div>
        )}

        <form
          className="admin-password-form"
          onSubmit={handlePasswordChange}
        >
          <div className="admin-password-field">
            <label htmlFor="current-password">
              Current Password
            </label>

            <div className="admin-password-input-wrapper">
              <input
                id="current-password"
                type={showCurrentPassword ? 'text' : 'password'}
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="Enter current password"
                required
                autoComplete="current-password"
              />

              <button
                type="button"
                className="admin-password-toggle"
                onClick={() =>
                  setShowCurrentPassword(!showCurrentPassword)
                }
                aria-label={
                  showCurrentPassword
                    ? 'Hide current password'
                    : 'Show current password'
                }
              >
                {showCurrentPassword ? (
                  <EyeOff size={18} />
                ) : (
                  <Eye size={18} />
                )}
              </button>
            </div>
          </div>

          <div className="admin-password-field">
            <label htmlFor="new-password">
              New Password
            </label>

            <div className="admin-password-input-wrapper">
              <input
                id="new-password"
                type={showNewPassword ? 'text' : 'password'}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Enter new password"
                minLength={8}
                maxLength={128}
                required
                autoComplete="new-password"
              />

              <button
                type="button"
                className="admin-password-toggle"
                onClick={() =>
                  setShowNewPassword(!showNewPassword)
                }
                aria-label={
                  showNewPassword
                    ? 'Hide new password'
                    : 'Show new password'
                }
              >
                {showNewPassword ? (
                  <EyeOff size={18} />
                ) : (
                  <Eye size={18} />
                )}
              </button>
            </div>

            <span className="admin-password-hint">
              Minimum 8 characters.
            </span>
          </div>

          <div className="admin-password-field">
            <label htmlFor="confirm-password">
              Confirm New Password
            </label>

            <div className="admin-password-input-wrapper">
              <input
                id="confirm-password"
                type={showConfirmPassword ? 'text' : 'password'}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Confirm new password"
                required
                autoComplete="new-password"
              />

              <button
                type="button"
                className="admin-password-toggle"
                onClick={() =>
                  setShowConfirmPassword(!showConfirmPassword)
                }
                aria-label={
                  showConfirmPassword
                    ? 'Hide confirmation password'
                    : 'Show confirmation password'
                }
              >
                {showConfirmPassword ? (
                  <EyeOff size={18} />
                ) : (
                  <Eye size={18} />
                )}
              </button>
            </div>
          </div>

          <button
            type="submit"
            className="admin-password-submit"
            disabled={passwordLoading}
          >
            {passwordLoading
              ? 'Changing Password...'
              : 'Change Password'}
          </button>
        </form>
      </div>
    </div>
  )
}

export default AdminProfile
