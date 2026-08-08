export type UiSurface = 'client' | 'manager'
export type ClientRoute = '/login' | '/history'
export type ManagerRoute = '/login' | '/admin'
export type AppRoute = ClientRoute | ManagerRoute

export const CLIENT_UI_BASE: string = '/ui/client'
export const MANAGER_UI_BASE: string = '/ui/manager'

export function currentSurface(): UiSurface {
  if (window.location.pathname.startsWith(MANAGER_UI_BASE)) {
    return 'manager'
  }
  return 'client'
}

export function uiBase(): string {
  return currentSurface() === 'manager' ? MANAGER_UI_BASE : CLIENT_UI_BASE
}

export function currentRoute(): AppRoute {
  const base: string = uiBase()
  const path: string = window.location.pathname
  if (!path.startsWith(base)) {
    return '/login'
  }
  const suffix: string = path.slice(base.length).replace(/\/$/, '') || '/login'
  if (suffix === '/history') return '/history'
  if (suffix === '/admin') return '/admin'
  return '/login'
}

export function navigateTo(route: AppRoute): void {
  const nextPath: string = `${uiBase()}${route}`
  if (window.location.pathname === nextPath) {
    window.dispatchEvent(new PopStateEvent('popstate'))
    return
  }
  window.history.pushState(null, '', nextPath)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

export function navigateToManager(route: ManagerRoute): void {
  const nextPath: string = `${MANAGER_UI_BASE}${route}`
  window.location.assign(nextPath)
}

export function navigateToClient(route: ClientRoute): void {
  const nextPath: string = `${CLIENT_UI_BASE}${route}`
  window.location.assign(nextPath)
}
