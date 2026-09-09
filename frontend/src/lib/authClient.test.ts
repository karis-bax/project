// @vitest-environment jsdom
import { beforeEach, describe, expect, test, vi } from 'vitest'

import { refreshAccessToken } from './authClient'
import { getAccessToken, onUnauthorized, setAccessToken } from './authStorage'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  setAccessToken(null)
  vi.restoreAllMocks()
})

describe('single-flight refresh', () => {
  test('concurrent 401s trigger exactly one POST /auth/refresh', async () => {
    // Rotation makes refresh tokens single-use: N parallel refreshes would
    // present an already-rotated token N-1 times, which the server reads as
    // theft and answers by revoking the session. One request, or the user is
    // logged out by an ordinary burst.
    let calls = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      calls += 1
      await new Promise((r) => setTimeout(r, 5))
      return jsonResponse({
        access_token: 'env_at_fresh',
        refresh_token: 'env_rt_fresh',
        token_type: 'bearer',
        expires_in: 900,
      })
    })

    const results = await Promise.all([
      refreshAccessToken(),
      refreshAccessToken(),
      refreshAccessToken(),
      refreshAccessToken(),
    ])

    expect(calls).toBe(1)
    expect(results).toEqual([
      'env_at_fresh',
      'env_at_fresh',
      'env_at_fresh',
      'env_at_fresh',
    ])
    expect(getAccessToken()).toBe('env_at_fresh')
  })

  test('a later refresh starts a new request once the first settles', async () => {
    let calls = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
      calls += 1
      return jsonResponse({
        access_token: `env_at_${calls}`,
        refresh_token: 'env_rt_x',
        token_type: 'bearer',
        expires_in: 900,
      })
    })

    await refreshAccessToken()
    await refreshAccessToken()
    expect(calls).toBe(2)
  })

  test('a failed refresh clears the token and notifies subscribers', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ detail: 'Invalid or expired refresh token.' }, 401),
    )
    setAccessToken('env_at_stale')

    let notified = 0
    const stop = onUnauthorized(() => {
      notified += 1
    })

    expect(await refreshAccessToken()).toBeNull()
    expect(getAccessToken()).toBeNull()
    expect(notified).toBe(1)
    stop()
  })
})
