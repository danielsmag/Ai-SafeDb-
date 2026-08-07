import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError, getIdentity } from './api'
import { HistoryPage } from './pages/HistoryPage'
import { LoginPage } from './pages/LoginPage'
import { currentRoute, navigateTo, type AppRoute } from './routing'

function App(): ReactNode {
  const [route, setRoute] = useState<AppRoute>(currentRoute)
  const [authStatus, setAuthStatus] = useState<
    'loading' | 'authenticated' | 'anonymous'
  >('loading')

  useEffect(() => {
    const handleRoute = (): void => setRoute(currentRoute())
    window.addEventListener('hashchange', handleRoute)
    return () => window.removeEventListener('hashchange', handleRoute)
  }, [])

  useEffect(() => {
    setAuthStatus('loading')
    void getIdentity()
      .then(() => setAuthStatus('authenticated'))
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
    if (route === '/history' && authStatus === 'anonymous') navigateTo('/login')
    if (route === '/login' && authStatus === 'authenticated') navigateTo('/history')
  }, [authStatus, route])

  if (authStatus === 'loading') return null
  if (route === '/history' && authStatus === 'authenticated') return <HistoryPage />
  return <LoginPage />
}

export default App
