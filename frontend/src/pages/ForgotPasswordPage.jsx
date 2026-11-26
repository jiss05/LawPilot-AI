
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import AuthLayout from '../components/AuthLayout.jsx'
import { postAuth } from '../services/auth.js'

function ForgotPasswordPage() {
  const navigate = useNavigate()

  const [email, setEmail] = useState(
    new URLSearchParams(window.location.search).get('email') || '',
  )
  const [otp, setOtp] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  const [step, setStep] = useState('email')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleRequestOTP(event) {
    event.preventDefault()
    setError('')
    setMessage('')
    setIsSubmitting(true)

    try {
      const result = await postAuth('forgot-password', { email })
      setMessage(result.message)
      setStep('otp')
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to request a reset code. Please try again.',
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleResetPassword(event) {
    event.preventDefault()
    setError('')
    setMessage('')

    if (newPassword !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setIsSubmitting(true)

    try {
      const result = await postAuth('reset-password', {
        email,
        otp,
        new_password: newPassword,
        confirm_password: confirmPassword,
      })

      setMessage(result.message)
      setStep('success')
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to reset your password. Please try again.',
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <AuthLayout page="login">
      <div className="form-heading">
        <span className="eyebrow">PASSWORD RECOVERY</span>

        <h2>
          {step === 'email' && 'Forgot your password?'}
          {step === 'otp' && 'Reset your password'}
          {step === 'success' && 'Password reset complete'}
        </h2>

        <p>
          {step === 'email' &&
            'Enter your registered email address to receive a password reset code.'}

          {step === 'otp' &&
            'Enter the 6-digit code sent to your email and choose a new password.'}

          {step === 'success' &&
            'Your password has been updated successfully. You can now sign in.'}
        </p>
      </div>

      {step === 'email' && (
        <form className="auth-form" onSubmit={handleRequestOTP}>
          <label className="field">
            <span>Email address</span>
            <input
              type="email"
              name="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>

          {error && (
            <div className="notice notice-error" role="alert">
              {error}
            </div>
          )}

          {message && (
            <div className="notice notice-success" role="status">
              {message}
            </div>
          )}

          <button
            className="auth-submit"
            type="submit"
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Sending code...' : 'Send reset code'}
            {!isSubmitting && <span aria-hidden="true">→</span>}
          </button>
        </form>
      )}

      {step === 'otp' && (
        <form className="auth-form" onSubmit={handleResetPassword}>
          <label className="field">
            <span>Email address</span>
            <input
              type="email"
              value={email}
              readOnly
            />
          </label>

          <label className="field">
            <span>Reset code</span>
            <input
              className="otp-input"
              type="text"
              name="otp"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              placeholder="000000"
              value={otp}
              onChange={(event) =>
                setOtp(event.target.value.replace(/\D/g, '').slice(0, 6))
              }
              required
            />
          </label>

          <label className="field">
            <span>New password</span>
            <input
              type="password"
              name="newPassword"
              autoComplete="new-password"
              placeholder="Enter your new password"
              minLength={8}
              maxLength={128}
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              required
            />
          </label>

          <label className="field">
            <span>Confirm new password</span>
            <input
              type="password"
              name="confirmPassword"
              autoComplete="new-password"
              placeholder="Confirm your new password"
              minLength={8}
              maxLength={128}
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              required
            />
          </label>

          {error && (
            <div className="notice notice-error" role="alert">
              {error}
            </div>
          )}

          <button
            className="auth-submit"
            type="submit"
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Resetting password...' : 'Reset password'}
            {!isSubmitting && <span aria-hidden="true">→</span>}
          </button>
        </form>
      )}

      {step === 'success' && (
        <div className="notice notice-success" role="status">
          <strong>Password updated</strong>
          <span>{message}</span>

          <button
            className="auth-submit"
            type="button"
            onClick={() => navigate('/login')}
          >
            Return to sign in
            <span aria-hidden="true">→</span>
          </button>
        </div>
      )}

      {step !== 'success' && (
        <div className="resend-code">
          <Link to="/login">Back to sign in</Link>
        </div>
      )}
    </AuthLayout>
  )
}

export default ForgotPasswordPage
