/**
 * The single HTTP client. Every request to the API goes through `request()`.
 *
 * Two things here are load-bearing and easy to get wrong:
 *
 * 1. REFRESH IS SINGLE-FLIGHT. The backend rotates refresh tokens and treats a
 *    replayed one as theft — it revokes the whole family and logs you out. If
 *    three screens each hit a 401 and each POST /auth/refresh, two of them
 *    replay an already-rotated token and the user is signed out for no reason.
 *    `refreshInFlight` makes concurrent refreshes share one request.
 *
 * 2. NATIVE ASKS FOR BODY TRANSPORT. The backend hands web clients an httpOnly
 *    refresh cookie, which React Native has no useful way to hold. The
 *    `X-Envelope-Client: native` header selects body transport instead.
 */

import Constants from 'expo-constants'

import { clearTokens, getAccessToken, getRefreshToken, storeTokens } from './tokens'
import type { TokenPairResponse } from './types'

const BASE_URL: string =
  (Constants.expoConfig?.extra?.apiUrl as string | undefined) ??
  process.env.EXPO_PUBLIC_API_URL ??
  'http://localhost:8000'

export class ApiError extends Error {
  readonly status: number
  readonly detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** Called when refresh fails — the session is unrecoverable and the UI must sign out. */
let onSessionLost: () => void = () => {}
export function setSessionLostHandler(fn: () => void): void {
  onSessionLost = fn
}

let refreshInFlight: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight

  refreshInFlight = (async () => {
    try {
      const refresh = await getRefreshToken()
      if (!refresh) return null

      const res = await fetch(`${BASE_URL}/api/auth/refresh`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Envelope-Client': 'native',
        },
        body: JSON.stringify({ refresh_token: refresh }),
      })

      if (!res.ok) {
        await clearTokens()
        onSessionLost()
        return null
      }

      const pair = (await res.json()) as TokenPairResponse
      await storeTokens(pair.access_token, pair.refresh_token)
      return pair.access_token
    } catch {
      // A network failure is not proof the session is dead — don't sign out.
      return null
    } finally {
      refreshInFlight = null
    }
  })()

  return refreshInFlight
}

async function parseError(res: Response): Promise<ApiError> {
  let detail = res.statusText || 'Request failed'
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') detail = body.detail
  } catch {
    // Non-JSON error body; keep the status text.
  }
  return new ApiError(res.status, detail)
}

export async function request<T>(
  path: string,
  init: RequestInit & { skipAuth?: boolean } = {},
): Promise<T> {
  const { skipAuth, ...rest } = init

  const send = async (token: string | null): Promise<Response> => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-Envelope-Client': 'native',
      ...((rest.headers as Record<string, string> | undefined) ?? {}),
    }
    if (token) headers.Authorization = `Bearer ${token}`
    return fetch(`${BASE_URL}${path}`, { ...rest, headers })
  }

  let token = skipAuth ? null : await getAccessToken()
  let res = await send(token)

  if (res.status === 401 && !skipAuth) {
    const fresh = await refreshAccessToken()
    if (fresh) {
      res = await send(fresh)
    } else {
      throw await parseError(res)
    }
  }

  if (!res.ok) throw await parseError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown, opts: { skipAuth?: boolean } = {}) =>
    request<T>(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
      ...opts,
    }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

export { BASE_URL }
