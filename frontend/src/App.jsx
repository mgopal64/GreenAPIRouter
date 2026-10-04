import { useState } from 'react'
import Dashboard from './Dashboard.jsx'
import Demo from './Demo.jsx'
import { BrandMark } from './art.jsx'

export default function App() {
  const [page, setPage] = useState('dashboard')

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
      <main>{page === 'dashboard' ? <Dashboard /> : <Demo />}</main>
    </div>
  )
}
