import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import {
  ArrowRight,
  Eye,
  EyeOff,
  LockKeyhole,
  ShieldCheck,
  UserRound,
} from 'lucide-react'
import { ApiError, login } from '../api'
import { navigateTo } from '../routing'

export function LoginPage(): ReactNode {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    const normalizedUsername = username.trim()
    if (!normalizedUsername || !password) {
      setError('Enter your username and password.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      await login(normalizedUsername, password)
      navigateTo('/history')
    } catch (caught: unknown) {
      const message =
        caught instanceof ApiError && caught.status === 401
          ? 'Username or password is incorrect.'
          : 'Gateway unavailable. Check the service and try again.'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="login-shell">
      <div className="login-grid" aria-hidden="true" />
      <section className="login-card">
        <div className="brand-mark">
          <ShieldCheck size={20} strokeWidth={1.8} />
        </div>
        <div className="login-heading">
          <p className="eyebrow">AISafeDB Gateway</p>
          <h1>Security activity</h1>
          <p>
            Authenticate to review request transformations, policy decisions,
            and session activity.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          <label htmlFor="username">Username</label>
          <div className={`key-input ${error ? 'input-error' : ''}`}>
            <UserRound size={17} aria-hidden="true" />
            <input
              id="username"
              type="text"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="admin"
              autoComplete="username"
              autoFocus
            />
          </div>
          <label htmlFor="password">Password</label>
          <div className={`key-input ${error ? 'input-error' : ''}`}>
            <LockKeyhole size={17} aria-hidden="true" />
            <input
              id="password"
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="••••••••••••"
              autoComplete="current-password"
            />
            <button
              type="button"
              onClick={() => setShowPassword((value) => !value)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
            </button>
          </div>
          {error && <p className="form-error">{error}</p>}
          <button type="submit" className="primary-button" disabled={loading}>
            <span>{loading ? 'Verifying…' : 'Continue'}</span>
            {!loading && <ArrowRight size={17} />}
          </button>
        </form>

        <div className="security-note">
          <span className="status-dot" />
          Session protected by an HttpOnly cookie
        </div>
      </section>
      <footer className="login-footer">Protected gateway console</footer>
    </main>
  )
}
