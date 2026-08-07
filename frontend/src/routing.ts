export type AppRoute = '/login' | '/history' | '/admin'

export function currentRoute(): AppRoute {
  const hash: string = window.location.hash
  if (hash === '#/history') return '/history'
  if (hash === '#/admin') return '/admin'
  return '/login'
}

export function navigateTo(route: AppRoute): void {
  const nextHash: string = `#${route}`
  if (window.location.hash === nextHash) {
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    return
  }
  window.location.hash = nextHash
}
