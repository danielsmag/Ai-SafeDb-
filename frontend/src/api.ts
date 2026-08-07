export type Decision = 'allow' | 'block' | null
export type CallStatus = 'ok' | 'blocked' | 'error'

export interface Identity {
  name: string
  key_prefix: string
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

const API_KEY_STORAGE = 'aisafedb.apiKey'

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

export function getApiKey(): string | null {
  return sessionStorage.getItem(API_KEY_STORAGE)
}

export function setApiKey(value: string): void {
  sessionStorage.setItem(API_KEY_STORAGE, value)
}

export function clearApiKey(): void {
  sessionStorage.removeItem(API_KEY_STORAGE)
}

async function request<T>(path: string, apiKey?: string): Promise<T> {
  const key = apiKey ?? getApiKey()
  const response = await fetch(path, {
    headers: key ? { Authorization: `Bearer ${key}` } : {},
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
  return (await response.json()) as T
}

export function getIdentity(apiKey?: string): Promise<Identity> {
  return request<Identity>('/api/me', apiKey)
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
