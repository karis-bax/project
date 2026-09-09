// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'

import { RequireAuth } from './RequireAuth'
import { AuthProvider } from '../lib/AuthContext'
import { setAccessToken } from '../lib/authStorage'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderGuarded() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/budget/2026-05']}>
        <AuthProvider>
          <Routes>
            <Route path="login" element={<p>login page</p>} />
            <Route element={<RequireAuth />}>
              <Route path="budget/:month" element={<p>budget page</p>} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  setAccessToken(null)
  vi.restoreAllMocks()
})

test('shows a loading state instead of redirecting while auth resolves', async () => {
  // The access token is memory-only, so a hard refresh always starts
  // anonymous. Redirecting on `status !== authenticated` would bounce a valid
  // session to /login on every F5.
  let resolveRefresh: (r: Response) => void = () => {}
  vi.spyOn(globalThis, 'fetch').mockImplementation(
    () => new Promise<Response>((resolve) => { resolveRefresh = resolve }),
  )

  renderGuarded()

  expect(await screen.findByRole('status')).toBeTruthy()
  expect(screen.queryByText('login page')).toBeNull()
  expect(screen.queryByText('budget page')).toBeNull()

  resolveRefresh(jsonResponse({ detail: 'nope' }, 401))
  await waitFor(() => expect(screen.getByText('login page')).toBeTruthy())
})

test('redirects an anonymous visitor to the login page', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    jsonResponse({ detail: 'Invalid or expired refresh token.' }, 401),
  )
  renderGuarded()
  await waitFor(() => expect(screen.getByText('login page')).toBeTruthy())
})

test('renders the page when the refresh cookie yields a session', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = String(input)
    if (url.endsWith('/auth/refresh')) {
      return jsonResponse({
        access_token: 'env_at_ok',
        refresh_token: 'env_rt_ok',
        token_type: 'bearer',
        expires_in: 900,
      })
    }
    return jsonResponse({
      id: 1,
      email: 'owner@example.com',
      is_active: true,
      created_at: '2026-01-01T00:00:00',
    })
  })

  renderGuarded()
  await waitFor(() => expect(screen.getByText('budget page')).toBeTruthy())
})
