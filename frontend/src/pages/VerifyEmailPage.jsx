import { useState } from 'react'
import AuthLayout from '../components/AuthLayout.jsx'
import { postAuth } from '../services/auth.js'

function VerifyEmailPage() {
  const [email, setEmail] = useState(
    new URLSearchParams(window.location.search).get('email') || '',
  )
  const [otp, setOtp] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isResending, setIsResending] = useState(false)
  const [isVerified, setIsVerified] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setMessage('')
    setIsSubmitting(true)

    try {
      const result = await postAuth('verify-email', { email, otp })
      setMessage(result.message)
      setIsVerified(true)
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to verify your email. Please try again.',
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  async function handleResend() {
    setError('')
    setMessage('')
    setIsResending(true)

    try {
      const result = await postAuth('resend-otp', { email })
      setMessage(result.message)
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to resend the code. Please try again.',
      )
    } finally {
      setIsResending(false)
    }
  }

  return (
    <AuthLayout page="verify">
      <div className="form-heading">
        <span className="eyebrow">ONE LAST STEP</span>
        <h2>{isVerified ? 'Email verified' : 'Check your email'}</h2>
        <p>
          {isVerified
            ? 'Your account is active and ready to use.'
            : 'Enter the 6-digit verification code we sent to your email.'}
        </p>
      </div>

      {isVerified ? (
        <div className="notice notice-success" role="status">
          <strong>Email verified</strong>
          <span>{message}</span>
          <a href="/login">Continue to sign in</a>
        </div>
      ) : (
        <>
          <form className="auth-form" onSubmit={handleSubmit}>
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

            <label className="field">
              <span>Verification code</span>
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

            {error && <div className="notice notice-error" role="alert">{error}</div>}
            {message && <div className="notice notice-success" role="status">{message}</div>}

            <button className="auth-submit" type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Verifying…' : 'Verify email'}
              {!isSubmitting && <span aria-hidden="true">→</span>}
            </button>
          </form>

          <div className="resend-code">
            <span>Didn’t receive a code?</span>
            <button
              type="button"
              onClick={handleResend}
              disabled={isResending || !email}
            >
              {isResending ? 'Sending…' : 'Resend code'}
            </button>
          </div>
        </>
      )}
    </AuthLayout>
  )
}

export default VerifyEmailPage
