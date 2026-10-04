// Playful layer: die-cut stickers you can drag around or click to pop, and ripples when you click the "water".
// Purely decorative, so everything here is aria-hidden and never blocks the real controls.
import { useEffect, useRef, useState } from 'react'

const BOLT = 'M13 2 4 14h7l-1 8 9-12h-7z'

const ART = {
  drop: (
    <svg width="64" height="78" viewBox="0 0 64 78">
      <path d="M32 3c15 18 27 31 27 44a27 27 0 0 1-54 0C5 34 17 21 32 3z" fill="#9fd3d6" />
      <ellipse cx="21" cy="47" rx="6" ry="10" fill="#fff" opacity="0.55" transform="rotate(20 21 47)" />
    </svg>
  ),
  bolt: (
    <svg width="58" height="72" viewBox="3 1 17 22">
      <path d={BOLT} fill="#c2d099" stroke="#4e5e2a" strokeWidth="1" strokeLinejoin="round" />
    </svg>
  ),
  leaf: (
    <svg width="74" height="74" viewBox="0 0 100 100">
      <path d="M14 86C14 44 40 16 88 12c-2 46-30 74-74 74z" fill="#7da78c" />
      <path d="M14 86 64 36M40 60h18M40 60V44" stroke="#e6eec9" strokeWidth="4" strokeLinecap="round" fill="none" />
    </svg>
  ),
  cloud: (
    <svg width="104" height="66" viewBox="0 0 104 66">
      <path d="M26 62a22 22 0 0 1-3-43.8A26 26 0 0 1 72 14a22 22 0 0 1 8 48z" fill="#e6eec9" />
      <text x="50" y="47" textAnchor="middle" fontFamily="DM Sans, sans-serif" fontWeight="700" fontSize="24" fill="#2a6e75">CO₂</text>
    </svg>
  ),
  pin: (
    <svg width="58" height="76" viewBox="0 0 58 76">
      <path d="M29 74S4 44 4 28a25 25 0 0 1 50 0c0 16-25 46-25 46z" fill="#2a6e75" />
      <circle cx="29" cy="28" r="10" fill="#e6eec9" />
    </svg>
  ),
  chip: (
    <svg width="74" height="74" viewBox="0 0 74 74">
      {[22, 37, 52].map((p) => (
        <g key={p} stroke="#9fd3d6" strokeWidth="4" strokeLinecap="round">
          <path d={`M${p} 4v8M${p} 62v8M4 ${p}h8M62 ${p}h8`} />
        </g>
      ))}
      <rect x="12" y="12" width="50" height="50" rx="9" fill="#35858e" />
      <rect x="22" y="22" width="30" height="30" rx="5" fill="#23626a" />
      <path d={BOLT} fill="#c2d099" transform="translate(26 25) scale(1)" />
    </svg>
  ),
  wave: (
    <svg width="80" height="80" viewBox="0 0 80 80">
      <circle cx="40" cy="40" r="38" fill="#e6eec9" />
      <path d="M8 44c8-7 16-7 24 0s16 7 24 0 12-6 16-3v11a34 34 0 0 1-62 6z" fill="#35858e" />
      <path d="M10 33c8-7 16-7 24 0s16 7 24 0 10-5 14-3" stroke="#9fd3d6" strokeWidth="5" strokeLinecap="round" fill="none" />
    </svg>
  ),
  label: (
    <svg width="118" height="44" viewBox="0 0 118 44">
      <rect x="2" y="2" width="114" height="40" rx="20" fill="#2a6e75" />
      <text x="59" y="29" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontWeight="500" fontSize="16" fill="#e6eec9">green AI</text>
    </svg>
  ),
}

const PARTICLES = Array.from({ length: 10 }, (_, i) => {
  const a = (i / 10) * Math.PI * 2
  return { dx: `${Math.round(Math.cos(a) * 64)}px`, dy: `${Math.round(Math.sin(a) * 64)}px`, c: i % 2 ? '#9fd3d6' : '#c2d099' }
})

let topZ = 10

function Sticker({ art, tilt = 0, delay = 0, style, className = '' }) {
  const [pos, setPos] = useState({ x: 0, y: 0 })
  const [state, setState] = useState('idle') // idle | drag | popped
  const [respawned, setRespawned] = useState(false)
  const drag = useRef(null)
  const timer = useRef(null)
  useEffect(() => () => clearTimeout(timer.current), [])

  function down(e) {
    if (state === 'popped') return
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { sx: e.clientX, sy: e.clientY, ox: pos.x, oy: pos.y, moved: false }
  }

  function move(e) {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.sx
    const dy = e.clientY - d.sy
    // A few pixels of slack so a click doesn't count as a drag.
    if (!d.moved && Math.hypot(dx, dy) < 4) return
    if (!d.moved) {
      d.moved = true
      e.currentTarget.style.zIndex = ++topZ
      setState('drag')
    }
    setPos({ x: d.ox + dx, y: d.oy + dy })
  }

  function up() {
    const d = drag.current
    drag.current = null
    if (!d) return
    if (d.moved) return setState('idle')
    // Plain click: pop it, then let it grow back where it started.
    setState('popped')
    timer.current = setTimeout(() => {
      setPos({ x: 0, y: 0 })
      setRespawned(true)
      setState('idle')
    }, 2600)
  }

  function cancel() {
    if (drag.current) setState('idle')
    drag.current = null
  }

  return (
    <div
      className={`sticker ${state} ${className}`}
      style={{ ...style, '--x': `${pos.x}px`, '--y': `${pos.y}px`, '--r': `${tilt}deg`, '--d': respawned ? '0s' : `${delay}s` }}
      onPointerDown={down}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={cancel}
      aria-hidden="true"
    >
      <div className="sticker-art">{ART[art]}</div>
      {state === 'popped' && (
        <span className="burst">
          {PARTICLES.map((p, i) => (
            <span key={i} style={{ '--dx': p.dx, '--dy': p.dy, background: p.c }} />
          ))}
        </span>
      )}
    </div>
  )
}

// stickers: [{ art, tilt, delay, style, className }], positioned absolutely inside the nearest positioned parent.
export function StickerLayer({ stickers }) {
  return (
    <div className="sticker-layer">
      {stickers.map((s) => (
        <Sticker key={s.art + JSON.stringify(s.style)} {...s} />
      ))}
    </div>
  )
}

// Ripple rings wherever someone clicks empty space. Returns [onPointerDown handler, layer to render].
export function useRipples() {
  const [ripples, setRipples] = useState([])
  const nextId = useRef(0)

  function onPointerDown(e) {
    if (e.target.closest('button, a, input, textarea, label, .card, .banner, .sticker')) return
    const box = e.currentTarget.getBoundingClientRect()
    const id = nextId.current++
    setRipples((rs) => [...rs.slice(-6), { id, x: e.clientX - box.left, y: e.clientY - box.top }])
    setTimeout(() => setRipples((rs) => rs.filter((r) => r.id !== id)), 1400)
  }

  const layer = (
    <div className="ripples" aria-hidden="true">
      {ripples.map((r) => (
        <span key={r.id} style={{ left: r.x, top: r.y }}>
          <i />
          <i />
          <b />
        </span>
      ))}
    </div>
  )
  return [onPointerDown, layer]
}
