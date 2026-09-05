export type Session = { authenticated: boolean; saved_at: string | null }
export type Profile = { user_name: string; user_id: string; products: string[]; exchanges: string[] }
export type Credentials = { api_key: string; api_secret: string; request_token: string }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Kite-Client': 'local-web', ...options.headers },
      signal: AbortSignal.timeout(30000),
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the backend. Make sure FastAPI is running on port 8000, then try again.')
  }
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, data?.detail || 'The request could not be completed. Please try again.')
  if (!data) throw new ApiError(502, 'The backend returned an unexpected response. Please try again.')
  return data as T
}

export const api = {
  session: () => request<Session>('/session'),
  login: (credentials: Credentials) => request<Session>('/login', { method: 'POST', body: JSON.stringify(credentials) }),
  profile: () => request<Profile>('/profile'),
  logout: () => request<Session>('/logout', { method: 'POST' }),
}
