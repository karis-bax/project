/**
 * Login, logout, and the single-flight refresh.
 */

import { api, ApiError } from './api'
import { emitUnauthorized, setAccessToken } from './authStorage'
import type { TokenPairResponse, UserRead } from './types'

export async function login(email: string, password: string): Promise<UserRead> {
  const pair = await api.post<TokenPairResponse>('/auth/login', { email, password })
  setAccessToken(pair.access_token)
  return api.get<UserRead>('/auth/me')
}

export async function logout(): Promise<void> {
  try {
    await api.post<{ revoked: boolean }>('/auth/logout', {})
  } catch {
    // A failed logout must still clear the client: the user asked to leave.
  }
  setAccessToken(null)
}

export async function fetchMe(): Promise<UserRead> {
  return api.get<UserRead>('/auth/me')
}

/**
 * In-flight refresh, shared by every caller.
 *
 * This is a correctness requirement, not an optimisation. The budget page
 * fires several queries at once, so when the access token expires they all
 * 401 in the same tick. Refresh tokens ROTATE and are single-use, so N
 * concurrent refreshes would present an already-rotated token N-1 times —
 * which the server reads as token theft and responds to by revoking the whole
 * family. Without this, an ordinary burst of requests logs the user out.
 */
let inFlight: Promise<string | null> | null = null

export function refreshAccessToken(): Promise<string | null> {
  if (inFlight === null) {
    inFlight = doRefresh().finally(() => {
      inFlight = null
    })
  }
  return inFlight
}

async function doRefresh(): Promise<string | null> {
  try {
    // The refresh token travels in an httpOnly cookie, so there is nothing to
    // send in the body from the web client.
    const pair = await api.post<TokenPairResponse>('/auth/refresh', {})
    setAccessToken(pair.access_token)
    return pair.access_token
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      emitUnauthorized()
      return null
    }
    // A network blip is not a logout; let the caller surface it.
    throw error
  }
}
