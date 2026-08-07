import {
  ArrowDown,
  ArrowUp,
  Calendar,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Database,
  Eye,
  EyeOff,
  FileText,
  Key,
  LogOut,
  Plus,
  RefreshCw,
  Search,
  Settings,
  Shield,
  ShieldCheck,
  User,
  Users,
  Wrench,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  adminCreateUser,
  adminGetHistory,
  adminGetHistoryFacets,
  adminListPolicies,
  adminListSessions,
  adminListUsers,
  adminUpdateUser,
  ApiError,
  getIdentity,
  logout,
  type AdminHistoryFilters,
  type AdminUser,
  type HistoryCall,
  type HistoryFacets,
  type Identity,
  type PolicySummary,
  type Session,
} from '../api'
import { navigateTo } from '../routing'

type TabId = 'users' | 'policies' | 'requests'
type SortColumn =
  | 'created_at'
  | 'server_name'
  | 'tool_name'
  | 'status'
  | 'duration_ms'
  | 'api_key_name'
  | 'username'
type SortOrder = 'asc' | 'desc'
type TimeWindowId = 'all' | '1h' | '6h' | '24h' | '7d' | '30d' | 'custom'

interface TimeWindowOption {
  id: TimeWindowId
  label: string
  hours: number | null
}

const TIME_WINDOWS: TimeWindowOption[] = [
  { id: 'all', label: 'Any time', hours: null },
  { id: '1h', label: 'Last hour', hours: 1 },
  { id: '6h', label: 'Last 6 hours', hours: 6 },
  { id: '24h', label: 'Last 24 hours', hours: 24 },
  { id: '7d', label: 'Last 7 days', hours: 24 * 7 },
  { id: '30d', label: 'Last 30 days', hours: 24 * 30 },
  { id: 'custom', label: 'Custom range', hours: null },
]

const PAGE_SIZE: number = 25

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value))
}

function shortId(value: string): string {
  return value.slice(0, 8)
}

function transformationCount(call: HistoryCall): number {
  return (
    Number(call.expanded_stars) +
    call.dropped_columns.length +
    call.hashed_columns.length +
    call.masked_fields.length +
    call.removed_fields.length
  )
}

function StatusBadge({ status }: { status: HistoryCall['status'] }): ReactNode {
  return (
    <span className={`status-badge status-${status}`}>
      <span />
      {status}
    </span>
  )
}

function DecisionBadge({
  label,
  decision,
}: {
  label: string
  decision: HistoryCall['call_decision']
}): ReactNode {
  if (!decision) return null
  return (
    <span className={`decision-badge decision-${decision}`}>
      {label}: {decision}
    </span>
  )
}

function SqlPanel({
  title,
  statements,
  empty,
}: {
  title: string
  statements: string[]
  empty: string
}): ReactNode {
  return (
    <section className="sql-panel">
      <header>
        <span>{title}</span>
        {statements.length > 0 && (
          <span>
            {statements.length} statement{statements.length === 1 ? '' : 's'}
          </span>
        )}
      </header>
      {statements.length ? (
        statements.map((statement, index) => (
          <pre key={`${title}-${index}`}>
            <code>{statement}</code>
          </pre>
        ))
      ) : (
        <p className="sql-empty">{empty}</p>
      )}
    </section>
  )
}

function DetailDrawer({
  call,
  session,
  onClose,
}: {
  call: HistoryCall
  session?: Session
  onClose: () => void
}): ReactNode {
  const transforms: Array<[string, string[]]> = [
    ['Dropped columns', call.dropped_columns],
    ['Hashed columns', call.hashed_columns],
    ['Masked fields', call.masked_fields],
    ['Removed fields', call.removed_fields],
  ]

  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside
        className="detail-drawer"
        onMouseDown={(event) => event.stopPropagation()}
        aria-label="Tool call details"
      >
        <header className="drawer-header">
          <div>
            <p className="eyebrow">Request detail</p>
            <h2>{call.tool_name}</h2>
            <p>
              {call.server_name} · {formatDate(call.created_at)}
            </p>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close detail">
            <X size={19} />
          </button>
        </header>

        <div className="drawer-body">
          <div className="detail-summary">
            <StatusBadge status={call.status} />
            <DecisionBadge label="Call" decision={call.call_decision} />
            <DecisionBadge label="Result" decision={call.result_decision} />
            <span className="duration">
              <Clock3 size={14} />
              {call.duration_ms.toFixed(1)} ms
            </span>
          </div>

          <div className="session-strip">
            <Database size={16} />
            <div>
              <span>Session {shortId(call.session_id)}</span>
              <small>
                {session?.client_name ?? 'Unknown client'}
                {session?.client_version ? ` ${session.client_version}` : ''}
                {' · '}
                {call.mcp_session_id}
              </small>
            </div>
          </div>

          <div className="sql-grid">
            <SqlPanel
              title="Original request"
              statements={call.original_sql}
              empty="No SQL statement detected in original arguments."
            />
            <SqlPanel
              title="Executed after protection"
              statements={call.executed_sql}
              empty="No SQL rewrite was required."
            />
          </div>

          <section className="detail-section">
            <h3>Applied protections</h3>
            <div className="transform-list">
              {call.expanded_stars && (
                <div>
                  <span>Expanded selection</span>
                  <strong>SELECT *</strong>
                </div>
              )}
              {transforms.map(([label, values]) =>
                values.length ? (
                  <div key={label}>
                    <span>{label}</span>
                    <strong>{values.join(', ')}</strong>
                  </div>
                ) : null,
              )}
              {transformationCount(call) === 0 && (
                <p className="muted">No PII transformations applied.</p>
              )}
            </div>
          </section>

          <section className="detail-section">
            <h3>Original arguments</h3>
            <pre className="arguments-json">
              <code>{JSON.stringify(call.original_arguments, null, 2)}</code>
            </pre>
          </section>

          {call.error && (
            <section className="error-panel">
              <h3>Failure detail</h3>
              <p>{call.error}</p>
            </section>
          )}
        </div>
      </aside>
    </div>
  )
}

function SortIcon({
  column,
  current,
  order,
}: {
  column: SortColumn
  current: SortColumn
  order: SortOrder
}): ReactNode {
  if (column !== current) {
    return <ArrowDown size={12} className="sort-icon inactive" />
  }
  return order === 'asc' ? (
    <ArrowUp size={12} className="sort-icon active" />
  ) : (
    <ArrowDown size={12} className="sort-icon active" />
  )
}

interface MultiSelectOption {
  value: string
  label: string
}

function MultiSelect({
  icon,
  placeholder,
  options,
  selected,
  onChange,
}: {
  icon: ReactNode
  placeholder: string
  options: MultiSelectOption[]
  selected: string[]
  onChange: (values: string[]) => void
}): ReactNode {
  const [open, setOpen] = useState<boolean>(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClickOutside(event: MouseEvent): void {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  function toggleValue(value: string): void {
    if (selected.includes(value)) {
      onChange(selected.filter((item) => item !== value))
    } else {
      onChange([...selected, value])
    }
  }

  const summary: string =
    selected.length === 0
      ? placeholder
      : selected.length === 1
        ? (options.find((option) => option.value === selected[0])?.label ??
          selected[0])
        : `${selected.length} selected`

  return (
    <div className="multi-select" ref={containerRef}>
      <button
        type="button"
        className={`select-field multi-select-trigger ${selected.length ? 'has-value' : ''}`}
        onClick={() => setOpen(!open)}
      >
        {icon}
        <span>{summary}</span>
        <ChevronDown size={14} className={open ? 'chevron-open' : ''} />
      </button>
      {open && (
        <div className="multi-select-panel">
          {selected.length > 0 && (
            <button
              type="button"
              className="multi-select-clear"
              onClick={() => onChange([])}
            >
              Clear all
            </button>
          )}
          {options.length === 0 && (
            <p className="multi-select-empty">No options available</p>
          )}
          {options.map((option) => (
            <label className="multi-select-option" key={option.value}>
              <input
                type="checkbox"
                checked={selected.includes(option.value)}
                onChange={() => toggleValue(option.value)}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

function UsersTab(): ReactNode {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState<boolean>(false)
  const [newUsername, setNewUsername] = useState<string>('')
  const [newPassword, setNewPassword] = useState<string>('')
  const [newIsAdmin, setNewIsAdmin] = useState<boolean>(false)
  const [showPassword, setShowPassword] = useState<boolean>(false)
  const [creating, setCreating] = useState<boolean>(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const loadUsers = useCallback(async (): Promise<void> => {
    setLoading(true)
    setError(null)
    try {
      const response = await adminListUsers()
      setUsers(response.users)
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : 'Failed to load users')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadUsers()
  }, [loadUsers])

  async function handleCreate(event: React.FormEvent): Promise<void> {
    event.preventDefault()
    setCreating(true)
    setCreateError(null)
    try {
      await adminCreateUser({
        username: newUsername,
        password: newPassword,
        is_admin: newIsAdmin,
      })
      setShowCreate(false)
      setNewUsername('')
      setNewPassword('')
      setNewIsAdmin(false)
      await loadUsers()
    } catch (caught: unknown) {
      setCreateError(caught instanceof Error ? caught.message : 'Failed to create user')
    } finally {
      setCreating(false)
    }
  }

  async function handleToggleDisabled(user: AdminUser): Promise<void> {
    try {
      await adminUpdateUser(user.id, { disabled: user.disabled_at === null })
      await loadUsers()
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : 'Failed to update user')
    }
  }

  async function handleToggleAdmin(user: AdminUser): Promise<void> {
    try {
      await adminUpdateUser(user.id, { is_admin: !user.is_admin })
      await loadUsers()
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : 'Failed to update user')
    }
  }

  return (
    <div className="admin-tab-content">
      <div className="tab-header">
        <h2>
          <Users size={20} /> Users
        </h2>
        <div className="tab-actions">
          <button className="secondary-button" onClick={() => void loadUsers()}>
            <RefreshCw size={15} className={loading ? 'spin' : ''} />
            Refresh
          </button>
          <button className="primary-button" onClick={() => setShowCreate(true)}>
            <Plus size={15} />
            Create User
          </button>
        </div>
      </div>

      {showCreate && (
        <div className="drawer-backdrop" onMouseDown={() => setShowCreate(false)}>
          <aside
            className="create-drawer"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header className="drawer-header">
              <div>
                <p className="eyebrow">New user</p>
                <h2>Create User</h2>
              </div>
              <button
                className="icon-button"
                onClick={() => setShowCreate(false)}
                aria-label="Close"
              >
                <X size={19} />
              </button>
            </header>
            <form className="drawer-body create-form" onSubmit={(e) => void handleCreate(e)}>
              <label className="form-field">
                <span>Username</span>
                <input
                  type="text"
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  required
                  minLength={1}
                  maxLength={64}
                  autoFocus
                />
              </label>
              <label className="form-field">
                <span>Password</span>
                <div className="password-input">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                    minLength={6}
                    maxLength={128}
                  />
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => setShowPassword(!showPassword)}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </label>
              <label className="form-checkbox">
                <input
                  type="checkbox"
                  checked={newIsAdmin}
                  onChange={(e) => setNewIsAdmin(e.target.checked)}
                />
                <span>Administrator</span>
              </label>
              {createError && <p className="form-error">{createError}</p>}
              <button className="primary-button" type="submit" disabled={creating}>
                {creating ? 'Creating...' : 'Create User'}
              </button>
            </form>
          </aside>
        </div>
      )}

      {error && (
        <div className="error-state">
          <p>{error}</p>
          <button onClick={() => void loadUsers()}>Try again</button>
        </div>
      )}

      <div className="table-card">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Username</th>
                <th>Role</th>
                <th>Created</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading
                ? Array.from({ length: 5 }).map((_, index) => (
                    <tr className="skeleton-row" key={index}>
                      {Array.from({ length: 5 }).map((__, cell) => (
                        <td key={cell}>
                          <span />
                        </td>
                      ))}
                    </tr>
                  ))
                : users.map((user) => (
                    <tr key={user.id}>
                      <td>
                        <strong>{user.username}</strong>
                        <small className="mono">{shortId(user.id)}</small>
                      </td>
                      <td>
                        {user.is_admin ? (
                          <span className="role-badge admin">
                            <Shield size={12} /> Admin
                          </span>
                        ) : (
                          <span className="role-badge user">
                            <User size={12} /> User
                          </span>
                        )}
                      </td>
                      <td className="nowrap">{formatDate(user.created_at)}</td>
                      <td>
                        {user.disabled_at ? (
                          <span className="status-badge status-blocked">
                            <span /> Disabled
                          </span>
                        ) : (
                          <span className="status-badge status-ok">
                            <span /> Active
                          </span>
                        )}
                      </td>
                      <td>
                        <div className="action-buttons">
                          <button
                            className="action-button"
                            onClick={() => void handleToggleAdmin(user)}
                            title={user.is_admin ? 'Remove admin' : 'Make admin'}
                          >
                            <Shield size={14} />
                          </button>
                          <button
                            className="action-button"
                            onClick={() => void handleToggleDisabled(user)}
                            title={user.disabled_at ? 'Enable' : 'Disable'}
                          >
                            {user.disabled_at ? <Check size={14} /> : <X size={14} />}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>

        {!loading && users.length === 0 && (
          <div className="empty-state">
            <Users size={26} />
            <h3>No users found</h3>
            <p>Create your first user to get started.</p>
          </div>
        )}
      </div>
    </div>
  )
}

function PoliciesTab(): ReactNode {
  const [policies, setPolicies] = useState<PolicySummary[]>([])
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  const loadPolicies = useCallback(async (): Promise<void> => {
    setLoading(true)
    setError(null)
    try {
      const response = await adminListPolicies()
      setPolicies(response.policies)
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : 'Failed to load policies')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadPolicies()
  }, [loadPolicies])

  return (
    <div className="admin-tab-content">
      <div className="tab-header">
        <h2>
          <FileText size={20} /> Policies
        </h2>
        <button className="secondary-button" onClick={() => void loadPolicies()}>
          <RefreshCw size={15} className={loading ? 'spin' : ''} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="error-state">
          <p>{error}</p>
          <button onClick={() => void loadPolicies()}>Try again</button>
        </div>
      )}

      <div className="table-card">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Dialect</th>
                <th>Read-Only</th>
                <th>Denied Keywords</th>
                <th>Tables</th>
                <th>PII Rules</th>
              </tr>
            </thead>
            <tbody>
              {loading
                ? Array.from({ length: 3 }).map((_, index) => (
                    <tr className="skeleton-row" key={index}>
                      {Array.from({ length: 7 }).map((__, cell) => (
                        <td key={cell}>
                          <span />
                        </td>
                      ))}
                    </tr>
                  ))
                : policies.map((policy) => (
                    <tr key={policy.name}>
                      <td>
                        <strong>{policy.name}</strong>
                      </td>
                      <td>
                        <span className="type-badge">{policy.type}</span>
                      </td>
                      <td>
                        <span className="dialect-badge">{policy.dialect}</span>
                      </td>
                      <td>
                        {policy.read_only ? (
                          <span className="status-badge status-ok">
                            <span /> Yes
                          </span>
                        ) : (
                          <span className="status-badge status-blocked">
                            <span /> No
                          </span>
                        )}
                      </td>
                      <td>
                        {policy.denied_keywords.length > 0 ? (
                          <span className="keyword-list">
                            {policy.denied_keywords.slice(0, 3).join(', ')}
                            {policy.denied_keywords.length > 3 && (
                              <span className="muted">
                                {' '}
                                +{policy.denied_keywords.length - 3} more
                              </span>
                            )}
                          </span>
                        ) : (
                          <span className="muted">None</span>
                        )}
                      </td>
                      <td className="mono">{policy.tables_count}</td>
                      <td className="mono">{policy.pii_rules_count}</td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>

        {!loading && policies.length === 0 && (
          <div className="empty-state">
            <FileText size={26} />
            <h3>No policies configured</h3>
            <p>Add YAML policy files to the policies directory.</p>
          </div>
        )}
      </div>
    </div>
  )
}

function timeWindowToSince(windowId: TimeWindowId): string | undefined {
  const option: TimeWindowOption | undefined = TIME_WINDOWS.find(
    (item) => item.id === windowId,
  )
  if (!option?.hours) return undefined
  return new Date(Date.now() - option.hours * 60 * 60 * 1000).toISOString()
}

function RequestsTab(): ReactNode {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [facets, setFacets] = useState<HistoryFacets | null>(null)
  const [calls, setCalls] = useState<HistoryCall[]>([])
  const [total, setTotal] = useState<number>(0)
  const [offset, setOffset] = useState<number>(0)
  const [server, setServer] = useState<string>('')
  const [sessionId, setSessionId] = useState<string>('')
  const [userId, setUserId] = useState<string>('')
  const [toolNames, setToolNames] = useState<string[]>([])
  const [statuses, setStatuses] = useState<string[]>([])
  const [apiKeyIds, setApiKeyIds] = useState<string[]>([])
  const [timeWindow, setTimeWindow] = useState<TimeWindowId>('all')
  const [customSince, setCustomSince] = useState<string>('')
  const [customUntil, setCustomUntil] = useState<string>('')
  const [search, setSearch] = useState<string>('')
  const [selected, setSelected] = useState<HistoryCall | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<SortColumn>('created_at')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')

  const handleError = useCallback((caught: unknown): void => {
    if (caught instanceof ApiError && caught.status === 401) {
      void logout().finally(() => navigateTo('/login'))
      return
    }
    setError(caught instanceof Error ? caught.message : 'Unable to load activity.')
  }, [])

  const since: string | undefined =
    timeWindow === 'custom'
      ? customSince
        ? new Date(customSince).toISOString()
        : undefined
      : timeWindowToSince(timeWindow)
  const until: string | undefined =
    timeWindow === 'custom' && customUntil
      ? new Date(customUntil).toISOString()
      : undefined

  const loadHistory = useCallback(async (): Promise<void> => {
    setLoading(true)
    setError(null)
    try {
      const filters: AdminHistoryFilters = {
        limit: PAGE_SIZE,
        offset,
        server: server || undefined,
        sessionId: sessionId || undefined,
        userId: userId || undefined,
        toolNames: toolNames.length ? toolNames : undefined,
        statuses: statuses.length ? statuses : undefined,
        apiKeyIds: apiKeyIds.length ? apiKeyIds : undefined,
        since,
        until,
        sortBy,
        sortOrder,
      }
      const page = await adminGetHistory(filters)
      setCalls(page.items)
      setTotal(page.total)
    } catch (caught: unknown) {
      handleError(caught)
    } finally {
      setLoading(false)
    }
  }, [
    handleError,
    offset,
    server,
    sessionId,
    userId,
    toolNames,
    statuses,
    apiKeyIds,
    since,
    until,
    sortBy,
    sortOrder,
  ])

  useEffect(() => {
    void Promise.all([adminListSessions(), adminListUsers(), adminGetHistoryFacets()])
      .then(([sessionsRes, usersRes, facetsRes]) => {
        setSessions(sessionsRes.sessions)
        setUsers(usersRes.users)
        setFacets(facetsRes)
      })
      .catch(handleError)
  }, [handleError])

  useEffect(() => {
    void loadHistory()
  }, [loadHistory])

  const filteredCalls = useMemo(() => {
    const term: string = search.trim().toLowerCase()
    if (!term) return calls
    return calls.filter((call) =>
      [
        call.tool_name,
        call.server_name,
        call.mcp_session_id,
        call.api_key_name,
        call.username ?? '',
        ...call.original_sql,
      ]
        .join(' ')
        .toLowerCase()
        .includes(term),
    )
  }, [calls, search])

  const sessionMap = useMemo(
    () => new Map(sessions.map((session) => [session.id, session])),
    [sessions],
  )
  const servers = useMemo(
    () =>
      facets?.servers.length
        ? facets.servers
        : [...new Set(sessions.map((session) => session.server_name))].sort(),
    [facets, sessions],
  )
  const toolOptions = useMemo<MultiSelectOption[]>(
    () => (facets?.tools ?? []).map((name) => ({ value: name, label: name })),
    [facets],
  )
  const statusOptions = useMemo<MultiSelectOption[]>(
    () =>
      (facets?.statuses ?? ['ok', 'blocked', 'error']).map((name) => ({
        value: name,
        label: name.charAt(0).toUpperCase() + name.slice(1),
      })),
    [facets],
  )
  const apiKeyOptions = useMemo<MultiSelectOption[]>(
    () =>
      (facets?.api_keys ?? []).map((key) => ({ value: key.id, label: key.name })),
    [facets],
  )
  const pageStart: number = total === 0 ? 0 : offset + 1
  const pageEnd: number = Math.min(offset + PAGE_SIZE, total)
  const activeFilterCount: number =
    (server ? 1 : 0) +
    (sessionId ? 1 : 0) +
    (userId ? 1 : 0) +
    toolNames.length +
    statuses.length +
    apiKeyIds.length +
    (timeWindow !== 'all' ? 1 : 0)

  function handleSort(column: SortColumn): void {
    if (sortBy === column) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(column)
      setSortOrder('desc')
    }
    setOffset(0)
  }

  function updateServer(value: string): void {
    setServer(value)
    setOffset(0)
  }

  function updateSession(value: string): void {
    setSessionId(value)
    setOffset(0)
  }

  function updateUser(value: string): void {
    setUserId(value)
    setOffset(0)
  }

  function updateToolNames(values: string[]): void {
    setToolNames(values)
    setOffset(0)
  }

  function updateStatuses(values: string[]): void {
    setStatuses(values)
    setOffset(0)
  }

  function updateApiKeyIds(values: string[]): void {
    setApiKeyIds(values)
    setOffset(0)
  }

  function updateTimeWindow(value: TimeWindowId): void {
    setTimeWindow(value)
    setOffset(0)
  }

  function clearAllFilters(): void {
    setServer('')
    setSessionId('')
    setUserId('')
    setToolNames([])
    setStatuses([])
    setApiKeyIds([])
    setTimeWindow('all')
    setCustomSince('')
    setCustomUntil('')
    setOffset(0)
  }

  return (
    <div className="admin-tab-content">
      <div className="tab-header">
        <h2>
          <Database size={20} /> All Requests
        </h2>
        <button className="secondary-button" onClick={() => void loadHistory()}>
          <RefreshCw size={15} className={loading ? 'spin' : ''} />
          Refresh
        </button>
      </div>

      <section className="filters filters-wrap">
        <div className="search-field">
          <Search size={16} />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search current results"
          />
        </div>
        <label className="select-field">
          <Settings size={15} />
          <select value={server} onChange={(event) => updateServer(event.target.value)}>
            <option value="">All servers</option>
            {servers.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </label>
        <MultiSelect
          icon={<Wrench size={15} />}
          placeholder="All tools"
          options={toolOptions}
          selected={toolNames}
          onChange={updateToolNames}
        />
        <MultiSelect
          icon={<Clock3 size={15} />}
          placeholder="All statuses"
          options={statusOptions}
          selected={statuses}
          onChange={updateStatuses}
        />
        <MultiSelect
          icon={<Key size={15} />}
          placeholder="All API keys"
          options={apiKeyOptions}
          selected={apiKeyIds}
          onChange={updateApiKeyIds}
        />
        <label className="select-field">
          <User size={15} />
          <select value={userId} onChange={(event) => updateUser(event.target.value)}>
            <option value="">All users</option>
            {users.map((user) => (
              <option key={user.id} value={user.id}>
                {user.username}
              </option>
            ))}
          </select>
        </label>
        <label className="select-field session-select">
          <Database size={15} />
          <select
            value={sessionId}
            onChange={(event) => updateSession(event.target.value)}
          >
            <option value="">All sessions</option>
            {sessions.map((session) => (
              <option key={session.id} value={session.id}>
                {shortId(session.id)} · {session.client_name ?? session.server_name}
              </option>
            ))}
          </select>
        </label>
        <label className="select-field">
          <Calendar size={15} />
          <select
            value={timeWindow}
            onChange={(event) => updateTimeWindow(event.target.value as TimeWindowId)}
          >
            {TIME_WINDOWS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        {timeWindow === 'custom' && (
          <>
            <label className="datetime-field">
              <span>From</span>
              <input
                type="datetime-local"
                value={customSince}
                onChange={(event) => {
                  setCustomSince(event.target.value)
                  setOffset(0)
                }}
              />
            </label>
            <label className="datetime-field">
              <span>To</span>
              <input
                type="datetime-local"
                value={customUntil}
                onChange={(event) => {
                  setCustomUntil(event.target.value)
                  setOffset(0)
                }}
              />
            </label>
          </>
        )}
        {activeFilterCount > 0 && (
          <button className="clear-filters-button" onClick={clearAllFilters}>
            <X size={13} />
            Clear filters ({activeFilterCount})
          </button>
        )}
      </section>

      <section className="table-card">
        <div className="table-meta">
          <span>{total.toLocaleString()} requests</span>
          <span>
            Sort by {sortBy} ({sortOrder})
          </span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th
                  className="sortable"
                  onClick={() => handleSort('status')}
                >
                  Status <SortIcon column="status" current={sortBy} order={sortOrder} />
                </th>
                <th
                  className="sortable"
                  onClick={() => handleSort('created_at')}
                >
                  Time{' '}
                  <SortIcon column="created_at" current={sortBy} order={sortOrder} />
                </th>
                <th
                  className="sortable"
                  onClick={() => handleSort('server_name')}
                >
                  Server{' '}
                  <SortIcon column="server_name" current={sortBy} order={sortOrder} />
                </th>
                <th
                  className="sortable"
                  onClick={() => handleSort('tool_name')}
                >
                  Tool <SortIcon column="tool_name" current={sortBy} order={sortOrder} />
                </th>
                <th
                  className="sortable"
                  onClick={() => handleSort('username')}
                >
                  User{' '}
                  <SortIcon column="username" current={sortBy} order={sortOrder} />
                </th>
                <th
                  className="sortable"
                  onClick={() => handleSort('api_key_name')}
                >
                  API Key{' '}
                  <SortIcon column="api_key_name" current={sortBy} order={sortOrder} />
                </th>
                <th>Protections</th>
                <th>Guard</th>
                <th
                  className="sortable"
                  onClick={() => handleSort('duration_ms')}
                >
                  Latency{' '}
                  <SortIcon column="duration_ms" current={sortBy} order={sortOrder} />
                </th>
              </tr>
            </thead>
            <tbody>
              {loading
                ? Array.from({ length: 6 }).map((_, index) => (
                    <tr className="skeleton-row" key={index}>
                      {Array.from({ length: 9 }).map((__, cell) => (
                        <td key={cell}>
                          <span />
                        </td>
                      ))}
                    </tr>
                  ))
                : filteredCalls.map((call) => {
                    const session = sessionMap.get(call.session_id)
                    const count: number = transformationCount(call)
                    return (
                      <tr key={call.id} onClick={() => setSelected(call)}>
                        <td>
                          <StatusBadge status={call.status} />
                        </td>
                        <td className="nowrap">{formatDate(call.created_at)}</td>
                        <td>{call.server_name}</td>
                        <td>
                          <strong>{call.tool_name}</strong>
                        </td>
                        <td>
                          <strong>{call.username ?? '—'}</strong>
                        </td>
                        <td>
                          <span className="mono">{call.api_key_name}</span>
                          <small>{session?.client_name ?? 'Unknown'}</small>
                        </td>
                        <td>
                          {count ? (
                            <span className="protection-count">{count} applied</span>
                          ) : (
                            <span className="muted">None</span>
                          )}
                        </td>
                        <td>
                          <div className="decision-stack">
                            <DecisionBadge label="C" decision={call.call_decision} />
                            <DecisionBadge label="R" decision={call.result_decision} />
                            {!call.call_decision && !call.result_decision && (
                              <span className="muted">—</span>
                            )}
                          </div>
                        </td>
                        <td className="mono">{call.duration_ms.toFixed(1)} ms</td>
                      </tr>
                    )
                  })}
            </tbody>
          </table>
        </div>

        {!loading && !error && filteredCalls.length === 0 && (
          <div className="empty-state">
            <Database size={26} />
            <h3>No requests found</h3>
            <p>Activity appears here after an MCP client calls a gateway tool.</p>
          </div>
        )}
        {error && (
          <div className="error-state">
            <p>{error}</p>
            <button onClick={() => void loadHistory()}>Try again</button>
          </div>
        )}

        <footer className="pagination">
          <span>
            {pageStart}–{pageEnd} of {total}
          </span>
          <div>
            <button
              className="icon-button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              aria-label="Previous page"
            >
              <ChevronLeft size={17} />
            </button>
            <button
              className="icon-button"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
              aria-label="Next page"
            >
              <ChevronRight size={17} />
            </button>
          </div>
        </footer>
      </section>

      {selected && (
        <DetailDrawer
          call={selected}
          session={sessionMap.get(selected.session_id)}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}

export function AdminPage(): ReactNode {
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [activeTab, setActiveTab] = useState<TabId>('users')

  useEffect(() => {
    void getIdentity()
      .then(setIdentity)
      .catch(() => navigateTo('/login'))
  }, [])

  async function signOut(): Promise<void> {
    try {
      await logout()
    } finally {
      navigateTo('/login')
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark small">
            <ShieldCheck size={17} />
          </div>
          <span>AISafeDB</span>
          <span className="environment admin-env">Admin</span>
        </div>
        <div className="account">
          <span className="account-label">
            <strong>{identity?.username ?? 'Loading'}</strong>
            <small>Administrator</small>
          </span>
          <button
            className="icon-button"
            onClick={() => void signOut()}
            aria-label="Sign out"
          >
            <LogOut size={17} />
          </button>
        </div>
      </header>

      <div className="content admin-content">
        <nav className="admin-tabs">
          <button
            className={`tab-button ${activeTab === 'users' ? 'active' : ''}`}
            onClick={() => setActiveTab('users')}
          >
            <Users size={16} />
            Users
          </button>
          <button
            className={`tab-button ${activeTab === 'policies' ? 'active' : ''}`}
            onClick={() => setActiveTab('policies')}
          >
            <FileText size={16} />
            Policies
          </button>
          <button
            className={`tab-button ${activeTab === 'requests' ? 'active' : ''}`}
            onClick={() => setActiveTab('requests')}
          >
            <Database size={16} />
            Requests
          </button>
          <div className="tab-spacer" />
          <button className="tab-button" onClick={() => navigateTo('/history')}>
            <ArrowDown size={16} style={{ transform: 'rotate(90deg)' }} />
            User View
          </button>
        </nav>

        {activeTab === 'users' && <UsersTab />}
        {activeTab === 'policies' && <PoliciesTab />}
        {activeTab === 'requests' && <RequestsTab />}
      </div>
    </main>
  )
}
