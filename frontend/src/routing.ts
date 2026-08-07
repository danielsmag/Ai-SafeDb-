export type AppRoute = '/login' | '/history'

export function currentRoute(): AppRoute {
  return window.location.hash === '#/history' ? '/history' : '/login'
}

export function navigateTo(route: AppRoute): void {
  const nextHash = `#${route}`
  if (window.location.hash === nextHash) {
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    return
  }
  window.location.hash = nextHash
}
