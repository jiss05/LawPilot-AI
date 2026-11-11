function AuthLayout({ children, page }) {
  const isRegister = page === 'register'
  const isVerify = page === 'verify'

  return (
    <main className="auth-page">
      <section className="auth-showcase" aria-label="About LawPilot">
        <a className="brand" href="/login" aria-label="LawPilot home">
          <span className="brand-mark" aria-hidden="true">L</span>
          <span>LawPilot</span>
        </a>

        <div className="showcase-copy">
          <span className="eyebrow">LEGAL WORK, MADE CLEARER</span>
          <h1>Move forward with confidence.</h1>
          <p>
            A thoughtful workspace for your legal journey. Keep your matters
            organized and take the next step with clarity.
          </p>
        </div>

        <div className="showcase-note">
          <span className="note-icon" aria-hidden="true">§</span>
          <p>Clarity for every step of the legal process.</p>
        </div>
        <span className="showcase-orbit orbit-one" aria-hidden="true" />
        <span className="showcase-orbit orbit-two" aria-hidden="true" />
      </section>

      <section className="auth-content">
        <div className="auth-topline">
          <span>
            {isRegister
              ? 'Already have an account?'
              : isVerify
                ? 'Already verified?'
                : 'New to LawPilot?'}
          </span>
          <a href={isRegister || isVerify ? '/login' : '/register'}>
            {isRegister || isVerify ? 'Sign in' : 'Create account'}
          </a>
        </div>
        <div className="auth-form-wrap">{children}</div>
        <p className="auth-legal">
          By continuing, you agree to use LawPilot responsibly and protect the
          confidentiality of your legal information.
        </p>
      </section>
    </main>
  )
}

export default AuthLayout
