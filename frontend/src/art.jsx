// Hand-built SVG illustrations for the water + power theme. All decorative art is aria-hidden.
import { useId } from 'react'

const BOLT = 'M13 2 4 14h7l-1 8 9-12h-7z'
const DROP = 'M12 2.5c4.2 5.2 6.5 8.9 6.5 11.7a6.5 6.5 0 0 1-13 0c0-2.8 2.3-6.5 6.5-11.7z'

// [left %, size px, delay s, duration s]
const BUBBLES = [
  [6, 10, 0, 9], [14, 6, 2.4, 7], [22, 14, 4.1, 11], [31, 7, 1.2, 8], [40, 9, 5.5, 10],
  [49, 5, 3.0, 7], [58, 12, 0.8, 12], [66, 7, 6.2, 9], [74, 10, 2.0, 10], [82, 6, 4.8, 8],
  [90, 13, 1.5, 11], [96, 7, 3.6, 9],
]

export function Bubbles() {
  return (
    <div className="bubbles" aria-hidden="true">
      {BUBBLES.map(([left, size, delay, dur], i) => (
        <span key={i} style={{ left: `${left}%`, width: size, height: size, animationDelay: `${delay}s`, animationDuration: `${dur}s` }} />
      ))}
    </div>
  )
}

// Wavy bottom edge of the dark hero; fills with the page background so the hero "pours" into it.
export function Waves() {
  return (
    <svg className="waves" viewBox="0 0 1440 90" preserveAspectRatio="none" aria-hidden="true">
      <path className="wave back" d="M-60 40 C 180 10, 360 70, 540 40 S 900 10, 1080 40 S 1360 70, 1500 40 V90 H-60 Z" />
      <path className="wave front" d="M0 58 C 200 30, 400 86, 600 58 S 1000 30, 1200 58 S 1380 80, 1440 58 V90 H0 Z" />
    </svg>
  )
}

function ServerIcon({ x, y }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <rect width="26" height="12" rx="3" fill="#35858e" />
      <rect y="15" width="26" height="12" rx="3" fill="#35858e" />
      <circle cx="6" cy="6" r="2" fill="#c2d099" />
      <circle cx="6" cy="21" r="2" fill="#c2d099" />
      <path d="M12 6h9M12 21h9" stroke="#9fd3d6" strokeWidth="2" strokeLinecap="round" />
    </g>
  )
}

// lead: true = best combined carbon/water score, so it gets the most calls (glowing border);
// false = gets fewer (slightly faded); undefined = even split.
// bestCarbon / bestWater: this region has the lower value on that metric (shown in bold), so the card
// explains *why* it gets more or less traffic.
function RegionCard({ y, region, lead, standby, bestCarbon, bestWater, delay }) {
  const pct = region?.pct == null ? '…' : `${region.pct}%`
  return (
    <g className="pop" style={{ animationDelay: delay }}>
      <g className={lead === undefined ? 'dg-region' : lead ? 'dg-region lead' : 'dg-region minor'}>
      {/* Both regions get traffic (the split is the point), so the busier one is highlighted, not the other erased. */}
      <rect x="430" y={y} width="164" height="102" rx="16" fill="#f3f6e7" className="dg-card" />
      <title>Carbon: grams of CO₂ per kWh on this region's grid. Water: liters per kWh, weighted by how stressed the local watershed is.</title>
      <ServerIcon x={444} y={y + 14} />
      <text x="480" y={y + 26} className="dg-name">{region?.name ?? 'Azure region'}</text>
      <text x="480" y={y + 52} className="dg-share">{pct}<tspan className="dg-unit" dx="4">{standby ? '· standby' : 'of calls'}</tspan></text>
      <text x="480" y={y + 71} className={bestCarbon ? 'dg-meta best' : 'dg-meta'}>{region?.carbon == null ? '' : `${region.carbon} g CO₂/kWh`}</text>
      <text x="480" y={y + 88} className={bestWater ? 'dg-meta best' : 'dg-meta'}>{region?.water == null ? '' : `${region.water.toFixed(2)} L water/kWh`}</text>
      </g>
    </g>
  )
}

// chosen: true = picked (lit, checkmark), false = rejected (crossed out), undefined = no pick yet.
function ModelChip({ y, id, chosen }) {
  const state = chosen === undefined ? '' : chosen ? ' chosen' : ' rejected'
  return (
    <g className={`dg-chip${state}`}>
      <rect x="241" y={y} width="108" height="26" rx="13" />
      <text x="295" y={y + 17.5} textAnchor="middle">{chosen ? `✓ ${id}` : id}</text>
      {chosen === false && <line x1="256" y1={y + 13} x2="334" y2={y + 13} className="dg-strike" />}
    </g>
  )
}

// Pulses of "power" along a branch: busier branches get denser, faster pulses; an unused one gets none.
function Current({ d, share }) {
  if (share != null && share <= 0) return null
  const s = share ?? 0.5
  const gap = Math.round(12 + (1 - s) * 40)
  return (
    <path className="current" d={d} fill="none" stroke="#e6eec9" strokeWidth="3" strokeLinecap="round"
      strokeDasharray={`6 ${gap}`}
      style={{ '--loop': `${-(6 + gap) * 4}px`, animationDuration: `0.4s, ${(2.8 - s * 1.8).toFixed(2)}s` }} />
  )
}

// Hero: what the product does, with live data. A prompt goes to Green Router, which picks ONE model
// ("right model") and splits calls across Azure regions ("right place"). Never one region: the split is the point,
// so each branch carries power in proportion to its share (thickness, pulse rate) and the main region is highlighted.
// regions: [{ name, share (0..1), pct (whole %), carbon (gCO2/kWh) }] west-to-east; model: recommended model id.
export function RouteDiagram({ model, models = ['gpt-4.1-mini', 'gpt-5-mini'], regions, className = '' }) {
  const list = regions ?? [] // null until /route answers
  const [top, bottom] = list
  const width = (r) => (r?.share == null ? 6 : 4 + r.share * 14)
  // A region getting no traffic (shown as 0%) is still connected: draw its route dashed, as "standby".
  // Any visible share, even 1%, keeps the normal pipe so the picture never contradicts the number.
  const standby = (r) => r?.pct === 0
  // The region with the lower value on a metric (none if tied or data missing).
  const best = (key) => {
    if (list.length < 2 || list.some((r) => r[key] == null)) return null
    const sorted = [...list].sort((a, b) => a[key] - b[key])
    return sorted[0][key] < sorted[1][key] ? sorted[0] : null
  }
  const leadShare = Math.max(...list.map((r) => r.share))
  const evenSplit = list.length < 2 || list.filter((x) => x.share === leadShare).length > 1
  const isLead = (r) => (evenSplit || !r ? undefined : r.share === leadShare)
  const branchTop = 'M365 150 C 400 150, 398 70, 430 70'
  const branchBottom = 'M365 150 C 400 150, 398 230, 430 230'
  return (
    <svg className={className} viewBox="0 0 600 290" role="img"
      aria-label={`Your prompt goes to Green Router, which picks ${model ?? 'a model'} and splits calls across ${list.map((r) => `${r.name} ${r.pct}%`).join(' and ') || 'Azure regions'}`}>
      {/* Pipes: drawn in, then pulses flow along them. */}
      <path className="grow" d="M160 150 H 225" fill="none" stroke="#7da78c" strokeWidth="8" strokeLinecap="round" />
      {[[branchTop, top], [branchBottom, bottom]].map(([d, r]) =>
        standby(r) ? (
          <g key={d}>
            <path className="dg-standby" d={d} fill="none" stroke="#a7c3b0" strokeWidth="3" strokeLinecap="round" strokeDasharray="2 9" />
            {/* connector dot where the route meets the card, so it reads as attached, not broken */}
            <circle cx="430" cy={d === branchTop ? 70 : 230} r="4.5" fill="#a7c3b0" />
          </g>
        ) : (
          <path key={d} className="grow delay dg-branch" d={d} fill="none" stroke="#7da78c" style={{ strokeWidth: width(r) }} strokeLinecap="round" />
        ),
      )}
      <Current d="M160 150 H 225" share={1} />
      <Current d={branchTop} share={standby(top) ? 0 : top?.share} />
      <Current d={branchBottom} share={standby(bottom) ? 0 : bottom?.share} />

      {/* Your prompt */}
      <g className="pop" style={{ animationDelay: '0.2s' }}>
        <rect x="8" y="104" width="152" height="92" rx="16" fill="#f3f6e7" />
        <path d="M30 194 l-6 16 20-16z" fill="#f3f6e7" />
        <text x="24" y="130" className="dg-name">Your prompt</text>
        <rect x="24" y="142" width="116" height="7" rx="3.5" fill="#b9c6a8" />
        <rect x="24" y="156" width="96" height="7" rx="3.5" fill="#b9c6a8" />
        <rect x="24" y="170" width="70" height="7" rx="3.5" fill="#b9c6a8" />
      </g>

      {/* Green Router: both models listed, the chosen one lit */}
      <g className="pop" style={{ animationDelay: '0.6s' }}>
        <rect x="225" y="84" width="140" height="134" rx="18" fill="#23626a" stroke="#e6eec9" strokeWidth="2" />
        <g transform="translate(283 93)">
          <path d={DROP} fill="#9fd3d6" />
          <path d={BOLT} fill="#23626a" transform="translate(6.2 7.4) scale(0.5)" />
        </g>
        <text x="295" y="132" textAnchor="middle" className="dg-router">Green Router</text>
        {models.map((id, i) => <ModelChip key={id} y={146 + i * 32} id={id} chosen={model ? id === model : undefined} />)}
      </g>

      {/* Cards are 102 tall and centred on the route ends (y=70 and y=230). */}
      <RegionCard y={19} region={top} lead={isLead(top)} standby={standby(top)} delay="1.3s"
        bestCarbon={best('carbon') === top} bestWater={best('water') === top} />
      <RegionCard y={179} region={bottom} lead={isLead(bottom)} standby={standby(bottom)} delay="1.6s"
        bestCarbon={best('carbon') === bottom} bestWater={best('water') === bottom} />
    </svg>
  )
}

// How much water + power one call draws: a tank filled to `level` (0..1) with a bolt on it.
export function UsageTank({ level = 0.5, size = 84 }) {
  const clip = useId()
  const waterY = 14 + 72 * (1 - level)
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden="true">
      <defs>
        <clipPath id={clip}><rect x="26" y="14" width="48" height="72" rx="10" /></clipPath>
      </defs>
      <rect x="26" y="14" width="48" height="72" rx="10" fill="#f3f6e7" />
      <g clipPath={`url(#${clip})`}>
        <rect x="20" y={waterY} width="60" height="80" fill="#9fd3d6" />
        <path d={`M20 ${waterY} q 7.5 -5 15 0 t 15 0 t 15 0 t 15 0`} fill="#9fd3d6" />
      </g>
      <rect x="26" y="14" width="48" height="72" rx="10" fill="none" stroke="#2a6e75" strokeWidth="3" />
      <rect x="40" y="8" width="20" height="7" rx="3" fill="#2a6e75" />
      <path d={BOLT} fill="#c2d099" stroke="#4e5e2a" strokeWidth="1" strokeLinejoin="round" transform="translate(38 36) scale(1.05)" />
    </svg>
  )
}

export function BrandMark({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d={DROP} fill="#9fd3d6" />
      <path d={BOLT} fill="#23626a" transform="translate(6.2 7.4) scale(0.5)" />
    </svg>
  )
}

export function BoltIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={BOLT} />
    </svg>
  )
}

export function DropIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3c4 5 6 8.5 6 11a6 6 0 0 1-12 0c0-2.5 2-6 6-11z" />
    </svg>
  )
}

// Step 2 scene: one glass cylinder per region, fed from a shared intake pipe. Water level = share of calls.
// Depth comes from layering: floor shadow, base, back wall + rim, pipe, water (shaded like a cylinder,
// with a visible surface), front glass, front rim, then highlights. shares: 0..1 per tank, west-to-east.
export function TankScene({ shares }) {
  const raw = useId().replace(/:/g, '')
  const id = (n) => `${raw}-${n}`
  const W = 640, top = 82, bottom = 236, rx = 68, ry = 14
  const n = Math.max(shares.length, 1)
  const xs = shares.map((_, i) => ((i + 0.5) / n) * W)
  const pipeStart = 18
  const pipeEnd = (xs.at(-1) ?? W / 2) + 36
  const body = (x) => `M${x - rx} ${top} V${bottom} A${rx} ${ry} 0 0 0 ${x + rx} ${bottom} V${top}`
  return (
    <svg className="tank-scene" viewBox={`0 0 ${W} 272`} aria-hidden="true">
      <defs>
        <linearGradient id={id('glass')} x1="0" x2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="0.75" />
          <stop offset="0.16" stopColor="#fff" stopOpacity="0.22" />
          <stop offset="0.55" stopColor="#fff" stopOpacity="0.06" />
          <stop offset="0.86" stopColor="#fff" stopOpacity="0.28" />
          <stop offset="1" stopColor="#fff" stopOpacity="0.6" />
        </linearGradient>
        <linearGradient id={id('water')} x1="0" x2="1">
          <stop offset="0" stopColor="#1f5a60" />
          <stop offset="0.28" stopColor="#3f9198" />
          <stop offset="0.46" stopColor="#6cbcc0" />
          <stop offset="0.74" stopColor="#35858e" />
          <stop offset="1" stopColor="#1d4f55" />
        </linearGradient>
        <linearGradient id={id('depth')} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#0f2f33" stopOpacity="0" />
          <stop offset="1" stopColor="#0f2f33" stopOpacity="0.4" />
        </linearGradient>
        <linearGradient id={id('surface')} x1="0" x2="1">
          <stop offset="0" stopColor="#6fb9be" />
          <stop offset="0.45" stopColor="#c8eef0" />
          <stop offset="1" stopColor="#6fb9be" />
        </linearGradient>
        <linearGradient id={id('pipeH')} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#d3e5d6" />
          <stop offset="0.4" stopColor="#8db59a" />
          <stop offset="1" stopColor="#4f7a5f" />
        </linearGradient>
        <linearGradient id={id('pipeV')} x1="0" x2="1">
          <stop offset="0" stopColor="#4f7a5f" />
          <stop offset="0.38" stopColor="#d3e5d6" />
          <stop offset="1" stopColor="#5b876b" />
        </linearGradient>
        <linearGradient id={id('base')} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#e3ebd5" />
          <stop offset="1" stopColor="#b9c6a8" />
        </linearGradient>
        <filter id={id('soft')} x="-50%" y="-100%" width="200%" height="300%"><feGaussianBlur stdDeviation="6" /></filter>
        {/* userSpaceOnUse: straight lines have a zero-height box, so a percentage filter region would hide them */}
        <filter id={id('glow')} filterUnits="userSpaceOnUse" x="0" y="0" width={W} height="280"><feGaussianBlur stdDeviation="1.2" /></filter>
        {xs.map((x, i) => (
          <clipPath key={i} id={id(`in${i}`)}>
            <rect x={x - rx + 2.5} y={top} width={(rx - 2.5) * 2} height={bottom - top} />
            <ellipse cx={x} cy={bottom} rx={rx - 2.5} ry={ry - 2} />
          </clipPath>
        ))}
      </defs>

      {/* Intake pipe that every call comes through, with pulses of current */}
      <rect x={pipeStart} y="22" width={pipeEnd - pipeStart} height="16" rx="8" fill={`url(#${id('pipeH')})`} />
      <rect x={pipeStart - 6} y="16" width="10" height="28" rx="3" fill="#4f7a5f" />
      <line x1={pipeStart + 8} y1="30" x2={pipeEnd - 8} y2="30" className="pulse" stroke="#ffffff" strokeWidth="6" strokeLinecap="round" strokeDasharray="2 26" filter={`url(#${id('glow')})`} style={{ '--loop': '-112px' }} />
      <line x1={pipeStart + 8} y1="30" x2={pipeEnd - 8} y2="30" className="pulse" stroke="#f3f6e7" strokeWidth="3.5" strokeLinecap="round" strokeDasharray="2 26" style={{ '--loop': '-112px' }} />

      {xs.map((x, i) => {
        const share = shares[i] ?? 0
        // A small floor keeps tiny shares visible; a region with no traffic shows an empty tank.
        const level = share <= 0 ? 0 : Math.max(0.03, Math.min(1, share))
        const surfaceY = bottom - (bottom - top) * level
        return (
          <g key={i}>
            <ellipse cx={x} cy={bottom + 14} rx={rx + 18} ry="11" fill="rgba(28, 58, 61, 0.3)" filter={`url(#${id('soft')})`} />
            <ellipse cx={x} cy={bottom + 5} rx={rx + 8} ry={ry + 4} fill={`url(#${id('base')})`} />

            {/* back wall and back rim */}
            <path d={`${body(x)} A${rx} ${ry} 0 0 0 ${x - rx} ${top}`} fill="rgba(255, 255, 255, 0.45)" />
            <path d={`M${x - rx} ${top} A${rx} ${ry} 0 0 1 ${x + rx} ${top}`} fill="none" stroke="rgba(42, 110, 117, 0.35)" strokeWidth="2" />

            {/* feed pipe drops into the tank's mouth, behind the front rim */}
            <rect x={x - 7} y="34" width="14" height={top - 34 + 4} fill={`url(#${id('pipeV')})`} />
            <rect x={x - 11} y="18" width="22" height="24" rx="4" fill="#5b876b" />
            <line x1={x} y1="42" x2={x} y2={top} className="pulse" stroke="#f3f6e7" strokeWidth="3" strokeLinecap="round" strokeDasharray="2 18" filter={`url(#${id('glow')})`}
              style={{ '--loop': '-80px', animationDuration: `${(2.6 - share * 1.6).toFixed(2)}s`, opacity: share < 0.02 ? 0 : 1 }} />

            {/* water: shaded like a cylinder, slides to its new level (none at all for a 0% region) */}
            <g clipPath={`url(#${id(`in${i}`)})`} opacity={level === 0 ? 0 : 1} className="water-wrap">
              <g className="water" style={{ transform: `translateY(${surfaceY}px)` }}>
                <rect x={x - rx} y="0" width={rx * 2} height="200" fill={`url(#${id('water')})`} />
                <rect x={x - rx} y="0" width={rx * 2} height="200" fill={`url(#${id('depth')})`} />
                <ellipse cx={x} cy="0" rx={rx - 2.5} ry={ry - 2} fill={`url(#${id('surface')})`} />
                <ellipse className="shimmer" cx={x - 10} cy="-1" rx={rx * 0.45} ry="2.5" fill="#fff" />
              </g>
            </g>

            {/* front glass, outline, front rim */}
            <path d={body(x)} fill={`url(#${id('glass')})`} />
            <path d={body(x)} fill="none" stroke="rgba(42, 110, 117, 0.6)" strokeWidth="2.5" />
            <path d={`M${x - rx} ${top} A${rx} ${ry} 0 0 0 ${x + rx} ${top}`} fill="none" stroke="rgba(42, 110, 117, 0.7)" strokeWidth="2.5" />

            {/* highlights and measuring ticks */}
            <rect x={x - rx + 9} y={top + 12} width="7" height={bottom - top - 26} rx="3.5" fill="#fff" opacity="0.55" />
            <rect x={x + rx - 15} y={top + 18} width="3" height={bottom - top - 40} rx="1.5" fill="#fff" opacity="0.4" />
            {[0.25, 0.5, 0.75].map((t) => {
              const y = bottom - (bottom - top) * t
              return <line key={t} x1={x + rx - 12} y1={y} x2={x + rx - 3} y2={y} stroke="rgba(42, 110, 117, 0.45)" strokeWidth="1.5" />
            })}
          </g>
        )
      })}
    </svg>
  )
}
