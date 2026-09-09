/**
 * Auth state for the app. Holds the signed-in user and the sign-in/out actions;
 * the tokens themselves live in SecureStore and never enter React state.
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import { api, setSessionLostHandler } from './api'
import { clearTokens, getAccessToken, storeTokens } from './tokens'
import type { TokenPairResponse, UserRead } from './types'

interface AuthValue {
  user: UserRead | null
  /** True until the stored token has been checked on cold start. */
  loading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserRead | null>(null)
  const [loading, setLoading] = useState(true)

  const signOut = useCallback(async () => {
    try {
      await api.post('/api/auth/logout')
    } catch {
      // Already invalid server-side, or offline. Local state still clears.
    }
    await clearTokens()
    setUser(null)
  }, [])

  // A failed refresh deep in a query must drop us back to the login screen.
  useEffect(() => {
    setSessionLostHandler(() => setUser(null))
  }, [])

  // Cold start: if a token survives in SecureStore, resume the session.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        if (!(await getAccessToken())) return
        const me = await api.get<UserRead>('/api/auth/me')
        if (!cancelled) setUser(me)
      } catch {
        await clearTokens()
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    const pair = await api.post<TokenPairResponse>(
      '/api/auth/login',
      { email, password },
      { skipAuth: true },
    )
    await storeTokens(pair.access_token, pair.refresh_token)
    setUser(await api.get<UserRead>('/api/auth/me'))
  }, [])

  const value = useMemo(
    () => ({ user, loading, signIn, signOut }),
    [user, loading, signIn, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
