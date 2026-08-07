import {
  ChevronLeft,
  ChevronRight,
  Clock3,
  Database,
  Filter,
  LogOut,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  ApiError,
  getHistory,
  getIdentity,
  getSessions,
  logout,
  type HistoryCall,
  type Identity,
  type Session,
} from '../api'
import { navigateTo } from '../routing'

const PAGE_SIZE = 25

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
          <span>{statements.length} statement{statements.length === 1 ? '' : 's'}</span>
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
            <p>{call.server_name} · {formatDate(call.created_at)}</p>
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
            <span className="duration"><Clock3 size={14} />{call.duration_ms.toFixed(1)} ms</span>
          </div>

          <div className="session-strip">
            <Database size={16} />
            <div>
              <span>Session {shortId(call.session_id)}</span>
              <small>
                {session?.client_name ?? 'Unknown client'}
                {session?.client_version ? ` ${session.client_version}` : ''}
                {' · '}{call.mcp_session_id}
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
                <div><span>Expanded selection</span><strong>SELECT *</strong></div>
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

export function HistoryPage(): ReactNode {
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [calls, setCalls] = useState<HistoryCall[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [server, setServer] = useState('')
  const [sessionId, setSessionId] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<HistoryCall | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const handleError = useCallback(
    (caught: unknown): void => {
      if (caught instanceof ApiError && caught.status === 401) {
        void logout().finally(() => navigateTo('/login'))
        return
      }
      setError(caught instanceof Error ? caught.message : 'Unable to load activity.')
    },
    [],
  )

  const loadHistory = useCallback(async (): Promise<void> => {
    setLoading(true)
    setError(null)
    try {
      const page = await getHistory({
        limit: PAGE_SIZE,
        offset,
        server: server || undefined,
        sessionId: sessionId || undefined,
      })
      setCalls(page.items)
      setTotal(page.total)
    } catch (caught: unknown) {
      handleError(caught)
    } finally {
      setLoading(false)
    }
  }, [handleError, offset, server, sessionId])

  useEffect(() => {
    void Promise.all([getIdentity(), getSessions()])
      .then(([me, sessionPage]) => {
        setIdentity(me)
        setSessions(sessionPage.sessions)
      })
      .catch(handleError)
  }, [handleError])

  useEffect(() => {
    void loadHistory()
  }, [loadHistory])

  const filteredCalls = useMemo(() => {
    const term = search.trim().toLowerCase()
    if (!term) return calls
    return calls.filter((call) =>
      [call.tool_name, call.server_name, call.mcp_session_id, ...call.original_sql]
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
    () => [...new Set(sessions.map((session) => session.server_name))].sort(),
    [sessions],
  )
  const pageStart = total === 0 ? 0 : offset + 1
  const pageEnd = Math.min(offset + PAGE_SIZE, total)

  async function signOut(): Promise<void> {
    try {
      await logout()
    } finally {
      navigateTo('/login')
    }
  }

  function updateServer(value: string): void {
    setServer(value)
    setOffset(0)
  }

  function updateSession(value: string): void {
    setSessionId(value)
    setOffset(0)
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark small"><ShieldCheck size={17} /></div>
          <span>AISafeDB</span>
          <span className="environment">Gateway</span>
        </div>
        <div className="account">
          <span className="account-label">
            <strong>{identity?.username ?? 'Loading'}</strong>
            <small>Web console</small>
          </span>
          {identity?.is_admin && (
            <button
              className="icon-button"
              onClick={() => navigateTo('/admin')}
              aria-label="Admin panel"
              title="Admin"
            >
              <Settings size={17} />
            </button>
          )}
          <button
            className="icon-button"
            onClick={() => void signOut()}
            aria-label="Sign out"
          >
            <LogOut size={17} />
          </button>
        </div>
      </header>

      <div className="content">
        <section className="page-heading">
          <div>
            <p className="eyebrow">Audit trail</p>
            <h1>Request history</h1>
            <p>Tool activity, SQL transformations, and guard decisions.</p>
          </div>
          <button className="secondary-button" onClick={() => void loadHistory()}>
            <RefreshCw size={15} className={loading ? 'spin' : ''} />
            Refresh
          </button>
        </section>

        <section className="filters">
          <div className="search-field">
            <Search size={16} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search current results"
            />
          </div>
          <label className="select-field">
            <Filter size={15} />
            <select value={server} onChange={(event) => updateServer(event.target.value)}>
              <option value="">All servers</option>
              {servers.map((name) => <option key={name}>{name}</option>)}
            </select>
          </label>
          <label className="select-field session-select">
            <SlidersHorizontal size={15} />
            <select value={sessionId} onChange={(event) => updateSession(event.target.value)}>
              <option value="">All sessions</option>
              {sessions.map((session) => (
                <option key={session.id} value={session.id}>
                  {shortId(session.id)} · {session.client_name ?? session.server_name}
                </option>
              ))}
            </select>
          </label>
        </section>

        <section className="table-card">
          <div className="table-meta">
            <span>{total.toLocaleString()} requests</span>
            <span>Newest first</span>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Time</th>
                  <th>Server / tool</th>
                  <th>Session</th>
                  <th>Protections</th>
                  <th>Guard</th>
                  <th>Latency</th>
                </tr>
              </thead>
              <tbody>
                {loading
                  ? Array.from({ length: 6 }).map((_, index) => (
                      <tr className="skeleton-row" key={index}>
                        {Array.from({ length: 7 }).map((__, cell) => (
                          <td key={cell}><span /></td>
                        ))}
                      </tr>
                    ))
                  : filteredCalls.map((call) => {
                      const session = sessionMap.get(call.session_id)
                      const count = transformationCount(call)
                      return (
                        <tr key={call.id} onClick={() => setSelected(call)}>
                          <td><StatusBadge status={call.status} /></td>
                          <td className="nowrap">{formatDate(call.created_at)}</td>
                          <td>
                            <strong>{call.tool_name}</strong>
                            <small>{call.server_name}</small>
                          </td>
                          <td>
                            <span className="mono">{shortId(call.session_id)}</span>
                            <small>{session?.client_name ?? 'Unknown client'}</small>
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
            <span>{pageStart}–{pageEnd} of {total}</span>
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
      </div>

      {selected && (
        <DetailDrawer
          call={selected}
          session={sessionMap.get(selected.session_id)}
          onClose={() => setSelected(null)}
        />
      )}
    </main>
  )
}
