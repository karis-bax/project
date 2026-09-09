/**
 * The auth context object and its hook.
 *
 * Split from AuthContext.tsx so that file exports only components, which is
 * what React Fast Refresh needs to reload reliably.
 */

import { createContext, useContext } from 'react'

import type { UserRead } from './types'

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

export interface AuthValue {
  status: AuthStatus
  user: UserRead | null
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthValue | null>(null)

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (value === null) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}
