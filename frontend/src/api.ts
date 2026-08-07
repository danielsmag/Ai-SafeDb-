export type Decision = 'allow' | 'block' | null
export type CallStatus = 'ok' | 'blocked' | 'error'

export interface Identity {
  username: string
  created_at: string
}

export interface Session {
  id: string
  mcp_session_id: string
  server_name: string
  client_name: string | null
  client_version: string | null
  created_at: string
  last_seen_at: string
  closed_at: string | null
}

export interface HistoryCall {
  id: string
  session_id: string
  mcp_session_id: string
  api_key_id: string
  api_key_name: string
  server_name: string
  tool_name: string
  original_arguments: Record<string, unknown>
  original_sql: string[]
  executed_sql: string[]
  expanded_stars: boolean
  dropped_columns: string[]
  hashed_columns: string[]
  masked_fields: string[]
  removed_fields: string[]
  call_decision: Decision
  result_decision: Decision
  status: CallStatus
  error: string | null
  duration_ms: number
  created_at: string
}

export interface HistoryPage {
  items: HistoryCall[]
  total: number
}

export class ApiError extends Error {
  public readonly status: number

  constructor(
    status: number,
    message: string,
  ) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: 'same-origin',
  })
  if (!response.ok) {
    let message = 'Request failed'
    try {
      const payload = (await response.json()) as { detail?: string }
      message = payload.detail ?? message
    } catch {
      message = response.statusText || message
    }
    throw new ApiError(response.status, message)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function login(username: string, password: string): Promise<Identity> {
  return request<Identity>('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
}

export function logout(): Promise<void> {
  return request<void>('/api/logout', { method: 'POST' })
}

export function getIdentity(): Promise<Identity> {
  return request<Identity>('/api/me')
}

export function getSessions(): Promise<{ sessions: Session[] }> {
  return request<{ sessions: Session[] }>('/api/sessions')
}

export interface HistoryFilters {
  limit: number
  offset: number
  server?: string
  sessionId?: string
}

export function getHistory(filters: HistoryFilters): Promise<HistoryPage> {
  const query = new URLSearchParams({
    limit: String(filters.limit),
    offset: String(filters.offset),
  })
  if (filters.server) query.set('server', filters.server)
  if (filters.sessionId) query.set('session_id', filters.sessionId)
  return request<HistoryPage>(`/api/history?${query}`)
}
