import { useState } from 'react'
import AuthLayout from '../components/AuthLayout.jsx'
import { postAuth } from '../services/auth.js'

function RegisterPage() {
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('CLIENT')
  const [professionalId, setProfessionalId] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setIsSubmitting(true)

    try {
      const result = await postAuth('register', {
        display_name: displayName,
        email,
        password,
        requested_role: role,
        professional_id: role === 'CLIENT' ? null : professionalId.trim(),
      })
      const registeredEmail = result.email || email
      window.location.assign(
        `/verify-email?email=${encodeURIComponent(registeredEmail)}`,
      )
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to create your account. Please try again.',
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <AuthLayout page="register">
      <div className="form-heading">
        <span className="eyebrow">GET STARTED</span>
        <h2>Create your account</h2>
        <p>Set up your LawPilot account in just a few steps.</p>
      </div>

      <form className="auth-form" onSubmit={handleSubmit}>
          <label className="field">
            <span>Full name</span>
            <input
              type="text"
              name="display_name"
              autoComplete="name"
              placeholder="Your full name"
              minLength={2}
              maxLength={150}
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              required
            />
          </label>

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
            <span>I am registering as</span>
            <select
              name="requested_role"
              value={role}
              onChange={(event) => setRole(event.target.value)}
            >
              <option value="CLIENT">Client</option>
              <option value="LAWYER">Lawyer</option>
              <option value="JUDGE">Judge</option>
            </select>
          </label>

          {role !== 'CLIENT' && (
            <label className="field">
              <span>Professional ID</span>
              <input
                type="text"
                name="professional_id"
                placeholder={role === 'LAWYER' ? 'LAWYER12345' : 'JUDGE12345'}
                maxLength={11}
                value={professionalId}
                onChange={(event) => setProfessionalId(event.target.value)}
                required
              />
            </label>
          )}

          <label className="field">
            <span>Password</span>
            <input
              type="password"
              name="password"
              autoComplete="new-password"
              placeholder="At least 8 characters"
              minLength={8}
              maxLength={128}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>

          {error && <div className="notice notice-error" role="alert">{error}</div>}

          <button className="auth-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Creating account…' : 'Create account'}
            {!isSubmitting && <span aria-hidden="true">→</span>}
          </button>
      </form>
    </AuthLayout>
  )
}

export default RegisterPage
