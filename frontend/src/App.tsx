import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError, getIdentity, type Identity } from './api'
import { AdminPage } from './pages/AdminPage'
import { HistoryPage } from './pages/HistoryPage'
import { LoginPage } from './pages/LoginPage'
import {
  currentRoute,
  currentSurface,
  navigateTo,
  type AppRoute,
} from './routing'

function App(): ReactNode {
  const [route, setRoute] = useState<AppRoute>(currentRoute)
  const [surface, setSurface] = useState(currentSurface)
  const [authStatus, setAuthStatus] = useState<
    'loading' | 'authenticated' | 'anonymous'
  >('loading')
  const [identity, setIdentity] = useState<Identity | null>(null)

  useEffect(() => {
    const handleRoute = (): void => {
      setRoute(currentRoute())
      setSurface(currentSurface())
    }
    window.addEventListener('popstate', handleRoute)
    return () => window.removeEventListener('popstate', handleRoute)
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
  }, [route, surface])

  useEffect(() => {
    if (authStatus === 'loading') return
    const isProtected: boolean = route !== '/login'
    if (isProtected && authStatus === 'anonymous') navigateTo('/login')
    if (route === '/login' && authStatus === 'authenticated') {
      navigateTo(surface === 'manager' ? '/admin' : '/history')
    }
    if (
      surface === 'manager' &&
      route === '/admin' &&
      authStatus === 'authenticated' &&
      !identity?.is_admin
    ) {
      navigateTo('/login')
    }
  }, [authStatus, route, identity, surface])

  if (authStatus === 'loading') return null

  if (authStatus === 'authenticated') {
    if (surface === 'manager' && route === '/admin' && identity?.is_admin) {
      return <AdminPage />
    }
    if (surface === 'client' && route === '/history') {
      return <HistoryPage />
    }
  }

  return <LoginPage />
}

export default App
