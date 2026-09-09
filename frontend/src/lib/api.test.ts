// @vitest-environment jsdom
import { beforeEach, expect, test, vi } from 'vitest'

import { api } from './api'
import { setAccessToken } from './authStorage'

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

test('attaches the Authorization header when a token is present', async () => {
  setAccessToken('env_at_abc')
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(jsonResponse({ ok: true }))

  await api.get('/accounts')

  const init = fetchMock.mock.calls[0][1] as RequestInit
  expect((init.headers as Record<string, string>).Authorization).toBe(
    'Bearer env_at_abc',
  )
  expect(init.credentials).toBe('include')
})

test('omits Authorization when there is no token', async () => {
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(jsonResponse({ ok: true }))

  await api.get('/health')

  const init = fetchMock.mock.calls[0][1] as RequestInit
  expect((init.headers as Record<string, string>).Authorization).toBeUndefined()
})

test('a 401 refreshes once and retries the original request', async () => {
  setAccessToken('env_at_stale')
  const seen: string[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input)
    seen.push(url)
    if (url.endsWith('/auth/refresh')) {
      return jsonResponse({
        access_token: 'env_at_new',
        refresh_token: 'env_rt_new',
        token_type: 'bearer',
        expires_in: 900,
      })
    }
    const auth = (init?.headers as Record<string, string> | undefined)?.Authorization
    if (auth === 'Bearer env_at_new') return jsonResponse({ items: [] })
    return jsonResponse({ detail: 'Not authenticated.' }, 401)
  })

  const result = await api.get<{ items: unknown[] }>('/transactions')

  expect(result).toEqual({ items: [] })
  expect(seen.filter((u) => u.endsWith('/auth/refresh'))).toHaveLength(1)
  expect(seen.filter((u) => u.endsWith('/transactions'))).toHaveLength(2)
})

test('does not retry a second time when the refreshed token is also rejected', async () => {
  setAccessToken('env_at_stale')
  let dataCalls = 0
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = String(input)
    if (url.endsWith('/auth/refresh')) {
      return jsonResponse({
        access_token: 'env_at_also_bad',
        refresh_token: 'env_rt_x',
        token_type: 'bearer',
        expires_in: 900,
      })
    }
    dataCalls += 1
    return jsonResponse({ detail: 'Not authenticated.' }, 401)
  })

  await expect(api.get('/transactions')).rejects.toMatchObject({ status: 401 })
  expect(dataCalls).toBe(2) // original + exactly one retry, never a loop
})

test('a 401 from the login route does not trigger a refresh', async () => {
  const seen: string[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    seen.push(String(input))
    return jsonResponse({ detail: 'Invalid email or password.' }, 401)
  })

  await expect(api.post('/auth/login', {})).rejects.toMatchObject({ status: 401 })
  expect(seen.some((u) => u.endsWith('/auth/refresh'))).toBe(false)
})
