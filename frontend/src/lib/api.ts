/**
 * A single typed fetch wrapper.
 *
 * - Sends/receives JSON.
 * - Throws a typed `ApiError` carrying the HTTP status and the FastAPI `detail`.
 * - Reads the base URL from `import.meta.env.VITE_API_URL`, defaulting to `/api`
 *   (which the Vite dev server proxies to the backend).
 */

const BASE_URL = import.meta.env.VITE_API_URL ?? '/api'

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

function extractDetail(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    // FastAPI validation errors carry a structured detail array.
    return JSON.stringify(detail)
  }
  return fallback
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // FormData bodies must not carry an explicit JSON content-type; the browser
  // sets the multipart boundary itself.
  const isFormData = init?.body instanceof FormData
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      ...(init?.headers ?? {}),
    },
  })

  if (!response.ok) {
    let detail = response.statusText
    try {
      detail = extractDetail(await response.json(), detail)
    } catch {
      // Non-JSON error body; keep the status text.
    }
    throw new ApiError(response.status, detail)
  }

  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T
  }
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PATCH',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PUT',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  postForm: <T>(path: string, form: FormData) =>
    request<T>(path, { method: 'POST', body: form }),
}
