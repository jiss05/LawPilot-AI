import { useState } from 'react'
import AuthLayout from '../components/AuthLayout.jsx'
import { postAuth } from '../services/auth.js'

function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSignedIn, setIsSignedIn] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setIsSubmitting(true)

    try {
      const result = await postAuth('login', { email, password })
      window.localStorage.setItem('access_token', result.access_token)
      setIsSignedIn(true)
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to sign in. Please try again.',
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <AuthLayout page="login">
      <div className="form-heading">
        <span className="eyebrow">WELCOME BACK</span>
        <h2>Sign in to your account</h2>
        <p>Enter your details to continue to LawPilot.</p>
      </div>

      {isSignedIn ? (
        <div className="notice notice-success" role="status">
          You’re signed in successfully.
        </div>
      ) : (
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
            <span>Password</span>
            <input
              type="password"
              name="password"
              autoComplete="current-password"
              placeholder="Enter your password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>

          {error && <div className="notice notice-error" role="alert">{error}</div>}

          <button className="auth-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Signing in…' : 'Sign in'}
            {!isSubmitting && <span aria-hidden="true">→</span>}
          </button>
        </form>
      )}
    </AuthLayout>
  )
}

export default LoginPage
