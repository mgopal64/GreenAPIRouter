import { useState } from 'react'
import Dashboard from './Dashboard.jsx'
import Demo from './Demo.jsx'
import { BrandMark } from './art.jsx'
import { DEFAULT_SETTINGS } from './Controls.jsx'

export default function App() {
  const [page, setPage] = useState('dashboard')
  // Picker and routing settings, shared by both pages so they always agree.
  const [settings, setSettings] = useState(DEFAULT_SETTINGS)
  const update = (changes) => setSettings((s) => ({ ...s, ...changes }))

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <BrandMark />
            <span className="brand-name">Green Router</span>
            <span className="tag">Azure · 2 regions</span>
          </div>
          <nav aria-label="Main">
            <button type="button" className={page === 'dashboard' ? 'nav active' : 'nav'} aria-current={page === 'dashboard' ? 'page' : undefined} onClick={() => setPage('dashboard')}>
              Dashboard
            </button>
            <button type="button" className={page === 'demo' ? 'nav active' : 'nav'} aria-current={page === 'demo' ? 'page' : undefined} onClick={() => setPage('demo')}>
              Live demo
            </button>
          </nav>
        </div>
      </header>
      <main>{page === 'dashboard' ? <Dashboard settings={settings} update={update} /> : <Demo settings={settings} update={update} />}</main>
    </div>
  )
}
