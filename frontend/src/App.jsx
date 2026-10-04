import { useState } from 'react'
import Dashboard from './Dashboard.jsx'
import Demo from './Demo.jsx'
import Impact from './Impact.jsx'
import { BrandMark } from './art.jsx'
import { DEFAULT_SETTINGS } from './Controls.jsx'

export default function App() {
  const [page, setPage] = useState('dashboard')
  // Picker and routing settings, shared by both pages so they always agree.
  const [settings, setSettings] = useState(DEFAULT_SETTINGS)
  const update = (changes) => setSettings((s) => ({ ...s, ...changes }))
  const go = (next) => {
    setPage(next)
    window.scrollTo(0, 0)
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            {/* The logo + name is the way home (the Dashboard), like most sites. */}
            <a
              href="/"
              className="brand-link"
              aria-current={page === 'dashboard' ? 'page' : undefined}
              onClick={(e) => {
                e.preventDefault()
                go('dashboard')
              }}
            >
              <BrandMark />
              <span className="brand-name">Green Router</span>
            </a>
            <span className="tag">Azure · 2 regions</span>
          </div>
          <nav aria-label="Main">
            <button type="button" className={page === 'impact' ? 'nav active' : 'nav'} aria-current={page === 'impact' ? 'page' : undefined} onClick={() => go('impact')}>
              Grid & impact
            </button>
            <button type="button" className={page === 'demo' ? 'nav active' : 'nav'} aria-current={page === 'demo' ? 'page' : undefined} onClick={() => go('demo')}>
              Live demo
            </button>
          </nav>
        </div>
      </header>
      <main>
        {page === 'dashboard' && <Dashboard settings={settings} update={update} />}
        {page === 'impact' && <Impact />}
        {page === 'demo' && <Demo settings={settings} update={update} />}
      </main>
    </div>
  )
}