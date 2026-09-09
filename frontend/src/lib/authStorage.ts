/**
 * Where the web client keeps its tokens, and how the rest of the app learns
 * that the session ended.
 *
 * The access token lives in a module-scoped variable, NOT localStorage. The
 * honest trade-off: in-memory storage buys little against XSS on its own — an
 * attacker with script execution can just call the API from the page. What it
 * changes is *persistence*: a token in localStorage survives the tab and can be
 * exfiltrated to be replayed later from anywhere. In memory, it dies with the
 * page.
 *
 * The refresh token is deliberately NOT stored here. The native client keeps it
 * in expo-secure-store; the web client relies on the server setting it as an
 * httpOnly cookie, so script cannot read it at all.
 *
 * React-free on purpose, so api.ts can use it without importing React.
 */

let accessToken: string | null = null

type Listener = () => void
const unauthorizedListeners = new Set<Listener>()

export function getAccessToken(): string | null {
  return accessToken
}

export function setAccessToken(token: string | null): void {
  accessToken = token
}

/** Subscribe to "the session is over". Returns an unsubscribe function. */
export function onUnauthorized(listener: Listener): () => void {
  unauthorizedListeners.add(listener)
  return () => {
    unauthorizedListeners.delete(listener)
  }
}

/** Called when a refresh has failed and the user must log in again. */
export function emitUnauthorized(): void {
  accessToken = null
  for (const listener of unauthorizedListeners) listener()
}
