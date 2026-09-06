export type Session = { authenticated: boolean; saved_at: string | null }
export type Profile = { user_name: string; user_id: string; products: string[]; exchanges: string[] }
export type Credentials = { api_key: string; api_secret: string; request_token: string }
export type Timeframe = '5minute' | '15minute' | '60minute' | '4hour'
export type ScanParameters = { short_ema: number; long_ema: number; timeframe: Timeframe; lookback_days: number; max_stocks: number }
export type Signal = {
  rank: number; ticker: string; company: string; timeframe: Timeframe; crossover_type: 'Bullish' | 'Bearish'
  crossover_at: string; crossover_date: string; crossover_time: string
  close: number; short_ema: number; long_ema: number
}
export type ScanResult = {
  parameters: ScanParameters; generated_at: string; candle_cutoff: string; lookback_start: string
  stocks_selected: number; stocks_mapped: number; stocks_scanned: number; stocks_analyzed: number
  signals_found: number; bullish_signals: number; bearish_signals: number
  warnings: { ticker: string | null; message: string }[]; signals: Signal[]
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function request<T>(path: string, options: RequestInit = {}, timeout = 30000): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-Kite-Client': 'local-web', ...options.headers },
      signal: AbortSignal.timeout(timeout),
    })
  } catch {
    if (path.startsWith('/signals/')) throw new ApiError(0, 'The scan connection was interrupted or timed out. The backend may still be scanning; wait before retrying. Check that FastAPI is running.')
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
  signals: (parameters: ScanParameters) => request<ScanResult>(`/signals/ema?${new URLSearchParams(Object.entries(parameters).map(([key, value]) => [key, String(value)]))}`, {}, 20 * 60 * 1000),
}
