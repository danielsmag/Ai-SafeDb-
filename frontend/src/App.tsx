import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError, getIdentity, type Identity } from './api'
import { AdminPage } from './pages/AdminPage'
import { HistoryPage } from './pages/HistoryPage'
import { LoginPage } from './pages/LoginPage'
import { currentRoute, navigateTo, type AppRoute } from './routing'

function App(): ReactNode {
  const [route, setRoute] = useState<AppRoute>(currentRoute)
  const [authStatus, setAuthStatus] = useState<
    'loading' | 'authenticated' | 'anonymous'
  >('loading')
  const [identity, setIdentity] = useState<Identity | null>(null)

  useEffect(() => {
    const handleRoute = (): void => setRoute(currentRoute())
    window.addEventListener('hashchange', handleRoute)
    return () => window.removeEventListener('hashchange', handleRoute)
  }, [])

  useEffect(() => {
    setAuthStatus('loading')
    void getIdentity()
      .then((user: Identity) => {
        setIdentity(user)
        setAuthStatus('authenticated')
      })
      .catch((caught: unknown) => {
        if (caught instanceof ApiError && caught.status === 401) {
          setAuthStatus('anonymous')
          return
        }
        setAuthStatus('anonymous')
      })
  }, [route])

  useEffect(() => {
    if (authStatus === 'loading') return
    const isProtected: boolean = route === '/history' || route === '/admin'
    if (isProtected && authStatus === 'anonymous') navigateTo('/login')
    if (route === '/login' && authStatus === 'authenticated') navigateTo('/history')
    if (route === '/admin' && authStatus === 'authenticated' && !identity?.is_admin) {
      navigateTo('/history')
    }
  }, [authStatus, route, identity])

  if (authStatus === 'loading') return null
  if (authStatus === 'authenticated') {
    if (route === '/admin' && identity?.is_admin) return <AdminPage />
    if (route === '/history' || route === '/admin') return <HistoryPage />
  }
  return <LoginPage />
}

export default App
