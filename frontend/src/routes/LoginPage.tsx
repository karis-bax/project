/**
 * Sign-in form.
 */

import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { ApiError } from '../lib/api'
import { useAuth } from '../lib/authContextValue'

interface LocationState {
  from?: { pathname: string }
}

export function LoginPage() {
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setPending(true)
    try {
      await signIn(email, password)
      const from = (location.state as LocationState | null)?.from?.pathname
      navigate(from ?? '/', { replace: true })
    } catch (err) {
      // The server deliberately returns one message for every credential
      // failure; show it verbatim rather than inventing a more specific one.
      setError(
        err instanceof ApiError ? err.detail : 'Could not sign in. Try again.',
      )
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="flex h-dvh items-center justify-center bg-[var(--bg)] px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-lg border border-[var(--border)] bg-[var(--panel)] p-6"
      >
        <h1 className="text-lg font-medium text-[var(--fg)]">Envelope</h1>
        <p className="mt-1 text-sm text-[var(--fg-subtle)]">Sign in to continue.</p>

        <label className="mt-5 block text-sm text-[var(--fg-subtle)]" htmlFor="email">
          Email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--fg)]"
        />

        <label className="mt-4 block text-sm text-[var(--fg-subtle)]" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--fg)]"
        />

        {error !== null && (
          <p role="alert" className="mt-4 text-sm text-[var(--danger,#b91c1c)]">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={pending}
          className="mt-5 w-full rounded bg-[var(--accent,#2563eb)] px-3 py-2 text-sm font-medium text-white disabled:opacity-60"
        >
          {pending ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
