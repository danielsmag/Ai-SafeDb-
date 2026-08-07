import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { getApiKey } from './api'
import { HistoryPage } from './pages/HistoryPage'
import { LoginPage } from './pages/LoginPage'
import { currentRoute, navigateTo, type AppRoute } from './routing'

function App(): ReactNode {
  const [route, setRoute] = useState<AppRoute>(currentRoute)

  useEffect(() => {
    const handleRoute = (): void => setRoute(currentRoute())
    window.addEventListener('hashchange', handleRoute)
    if (route === '/history' && !getApiKey()) navigateTo('/login')
    if (route === '/login' && getApiKey()) navigateTo('/history')
    return () => window.removeEventListener('hashchange', handleRoute)
  }, [route])

  if (route === '/history' && getApiKey()) return <HistoryPage />
  return <LoginPage />
}

export default App
