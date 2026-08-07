import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ArrowRight, Eye, EyeOff, KeyRound, ShieldCheck } from 'lucide-react'
import { ApiError, getIdentity, setApiKey } from '../api'
import { navigateTo } from '../routing'

export function LoginPage(): ReactNode {
  const [apiKey, setKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    const key = apiKey.trim()
    if (!key) {
      setError('Enter your API key.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      await getIdentity(key)
      setApiKey(key)
      navigateTo('/history')
    } catch (caught: unknown) {
      const message =
        caught instanceof ApiError && caught.status === 401
          ? 'API key is invalid or revoked.'
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
          <label htmlFor="api-key">API key</label>
          <div className={`key-input ${error ? 'input-error' : ''}`}>
            <KeyRound size={17} aria-hidden="true" />
            <input
              id="api-key"
              type={showKey ? 'text' : 'password'}
              value={apiKey}
              onChange={(event) => setKey(event.target.value)}
              placeholder="aisk_••••••••••••••••"
              autoComplete="current-password"
              autoFocus
            />
            <button
              type="button"
              onClick={() => setShowKey((value) => !value)}
              aria-label={showKey ? 'Hide API key' : 'Show API key'}
            >
              {showKey ? <EyeOff size={17} /> : <Eye size={17} />}
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
          Key retained only for this browser session
        </div>
      </section>
      <footer className="login-footer">Protected gateway console</footer>
    </main>
  )
}
