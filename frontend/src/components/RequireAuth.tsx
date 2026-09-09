/**
 * Route guard. Renders the app only for a signed-in visitor.
 */

import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '../lib/authContextValue'

export function RequireAuth() {
  const { status } = useAuth()
  const location = useLocation()

  // The loading branch is load-bearing. The access token is held in memory
  // only, so a hard refresh always begins anonymous while the refresh cookie
  // is exchanged. A guard that redirected on `status !== 'authenticated'`
  // would bounce the user to /login on every F5 despite a valid session.
  if (status === 'loading') {
    return (
      <div
        className="flex h-dvh items-center justify-center text-sm text-[var(--fg-subtle)]"
        role="status"
        aria-live="polite"
      >
        Signing in…
      </div>
    )
  }

  if (status === 'anonymous') {
    // `state.from` lets the login page send them back where they were headed.
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return <Outlet />
}
