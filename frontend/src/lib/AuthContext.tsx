/**
 * Who is signed in, and the boot sequence that decides it.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'

import * as authClient from './authClient'
import { AuthContext, type AuthStatus } from './authContextValue'
import { onUnauthorized } from './authStorage'
import type { UserRead } from './types'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUser] = useState<UserRead | null>(null)
  const queryClient = useQueryClient()

  // Boot: the access token lives only in memory, so a page load starts with
  // nothing. Try to exchange the refresh cookie for a session before deciding
  // the visitor is anonymous — otherwise every hard refresh bounces a
  // perfectly valid session to /login.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const token = await authClient.refreshAccessToken()
        if (cancelled) return
        if (token === null) {
          setStatus('anonymous')
          return
        }
        const me = await authClient.fetchMe()
        if (cancelled) return
        setUser(me)
        setStatus('authenticated')
      } catch {
        if (!cancelled) setStatus('anonymous')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // A refresh failure mid-session reaches the router through here, which is
  // how api.ts stays free of any React dependency.
  useEffect(
    () =>
      onUnauthorized(() => {
        setUser(null)
        setStatus('anonymous')
        queryClient.clear()
      }),
    [queryClient],
  )

  const signIn = useCallback(
    async (email: string, password: string) => {
      const me = await authClient.login(email, password)
      setUser(me)
      setStatus('authenticated')
    },
    [],
  )

  const signOut = useCallback(async () => {
    await authClient.logout()
    setUser(null)
    setStatus('anonymous')
    // clear(), not invalidateQueries(): invalidated data stays in the cache
    // while it refetches, so on a shared machine the next person to sign in
    // would see the previous user's balances and payees flash in the sidebar
    // before their own data arrives.
    queryClient.clear()
  }, [queryClient])

  const value = useMemo(
    () => ({ status, user, signIn, signOut }),
    [status, user, signIn, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
