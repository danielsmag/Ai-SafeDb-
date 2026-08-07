export type Decision = 'allow' | 'block' | null
export type CallStatus = 'ok' | 'blocked' | 'error'

export interface Identity {
  username: string
  is_admin: boolean
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
  user_id: string | null
  username: string | null
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
  const query: URLSearchParams = new URLSearchParams({
    limit: String(filters.limit),
    offset: String(filters.offset),
  })
  if (filters.server) query.set('server', filters.server)
  if (filters.sessionId) query.set('session_id', filters.sessionId)
  return request<HistoryPage>(`/api/history?${query}`)
}

export interface AdminUser {
  id: string
  username: string
  is_admin: boolean
  created_at: string
  disabled_at: string | null
}

export interface CreateUserPayload {
  username: string
  password: string
  is_admin: boolean
}

export interface UpdateUserPayload {
  password?: string
  is_admin?: boolean
  disabled?: boolean
}

export interface PolicySummary {
  name: string
  type: string
  dialect: string
  read_only: boolean
  denied_keywords: string[]
  tables_count: number
  pii_rules_count: number
}

export interface ApiKeyFacet {
  id: string
  name: string
}

export interface HistoryFacets {
  servers: string[]
  tools: string[]
  api_keys: ApiKeyFacet[]
  statuses: string[]
}

export interface AdminHistoryFilters {
  limit: number
  offset: number
  server?: string
  sessionId?: string
  userId?: string
  toolNames?: string[]
  statuses?: string[]
  apiKeyIds?: string[]
  since?: string
  until?: string
  sortBy?: string
  sortOrder?: 'asc' | 'desc'
}

export function adminListUsers(): Promise<{ users: AdminUser[] }> {
  return request<{ users: AdminUser[] }>('/api/admin/users')
}

export function adminCreateUser(payload: CreateUserPayload): Promise<AdminUser> {
  return request<AdminUser>('/api/admin/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function adminUpdateUser(
  userId: string,
  payload: UpdateUserPayload,
): Promise<AdminUser> {
  return request<AdminUser>(`/api/admin/users/${userId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function adminListPolicies(): Promise<{ policies: PolicySummary[] }> {
  return request<{ policies: PolicySummary[] }>('/api/admin/policies')
}

export function adminListSessions(): Promise<{ sessions: Session[] }> {
  return request<{ sessions: Session[] }>('/api/admin/sessions')
}

export function adminGetHistory(filters: AdminHistoryFilters): Promise<HistoryPage> {
  const query: URLSearchParams = new URLSearchParams({
    limit: String(filters.limit),
    offset: String(filters.offset),
  })
  if (filters.server) query.set('server', filters.server)
  if (filters.sessionId) query.set('session_id', filters.sessionId)
  if (filters.userId) query.set('user_id', filters.userId)
  for (const tool of filters.toolNames ?? []) query.append('tool_name', tool)
  for (const status of filters.statuses ?? []) query.append('status', status)
  for (const keyId of filters.apiKeyIds ?? []) query.append('api_key_id', keyId)
  if (filters.since) query.set('since', filters.since)
  if (filters.until) query.set('until', filters.until)
  if (filters.sortBy) query.set('sort_by', filters.sortBy)
  if (filters.sortOrder) query.set('sort_order', filters.sortOrder)
  return request<HistoryPage>(`/api/admin/history?${query}`)
}

export function adminGetHistoryFacets(): Promise<HistoryFacets> {
  return request<HistoryFacets>('/api/admin/history/facets')
}
