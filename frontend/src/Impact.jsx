import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { getRegions, getReplay, getSummary } from './api.js'
import { BoltIcon, Bubbles, DropIcon, Waves } from './art.jsx'

const REGION_LABELS = { westus: 'West US', northcentralus: 'North Central US' }
const regionName = (id) => REGION_LABELS[id] || id
const REGION_COLORS = { westus: '#2a6e75', northcentralus: '#b5651d' }
const colorFor = (id) => REGION_COLORS[id] || '#4e6461'
const FUEL = { NG: { label: 'Gas', color: '#b5651d' }, COL: { label: 'Coal', color: '#3d3d3a' }, NUC: { label: 'Nuclear', color: '#7a4fa0' } }
const SEAWATER = ['Diablo Canyon', 'Moss Landing'] // once-through ocean cooling: zero freshwater stress
const isSeawater = (name) => SEAWATER.some((k) => name?.includes(k))
const PACIFIC = 'America/Los_Angeles'

// Short readable number: 3 significant figures, even for tiny values (e.g. 0.0000421).
const SIG = new Intl.NumberFormat('en-US', { maximumSignificantDigits: 3 })
const sig = (x) => (x == null ? '—' : SIG.format(x))

// Poll an endpoint on an interval; keeps the last good data if a refresh fails.
function usePolling(fetcher, ms, deps = []) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const d = await fetcher()
        if (alive) { setData(d); setError('') }
      } catch (e) {
        if (alive) setError(e.message)
      }
    }
    load()
    const t = setInterval(load, ms)
    return () => { alive = false; clearInterval(t) }
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- caller controls refetch via deps
  }, deps)
  return [data, error]
}

/* ---------- 1. Savings counters (/summary) ---------- */

function Kpi({ value, unit, label, pct, Icon }) {
  return (
    <div className="kpi">
      <span className="kpi-value mono">{value}<span className="kpi-unit"> {unit}</span></span>
      <span className="kpi-label">{Icon && <Icon />} {label}</span>
      {pct != null && <span className="kpi-pct mono">{pct >= 0 ? `${pct}% less` : `${-pct}% more`} than naive</span>}
    </div>
  )
}

function Savings() {
  const [hours, setHours] = useState(24)
  const [s, error] = usePolling(() => getSummary(hours), 10_000, [hours])
  return (
    <section className="card" aria-labelledby="sav-h">
      <div className="card-head impact-head">
        <div>
          <span className="step">LIVE TOTALS</span>
          <h2 id="sav-h">Savings from real calls</h2>
          <p className="muted small">Every live call is logged with its real token counts and compared to naive routing (large model, nearest region). Updates every 10 s.</p>
        </div>
        <div className="chips" role="group" aria-label="Time window">
          {[[24, '24 h'], [168, '7 days']].map(([h, label]) => (
            <button key={h} type="button" className={hours === h ? 'chip active' : 'chip'} aria-pressed={hours === h} onClick={() => setHours(h)}>{label}</button>
          ))}
        </div>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {s && s.calls === 0 && <p className="muted">No live calls in this window yet. Send one from Step 3 on the home page and watch these update.</p>}
      {s && s.calls > 0 && (
        <>
          <div className="kpis">
            <Kpi value={s.calls.toLocaleString()} unit="calls" label="routed" />
            <Kpi value={sig(s.saved.co2_g)} unit="g" label="CO₂ saved" pct={s.pct_saved.co2_g} Icon={BoltIcon} />
            <Kpi value={sig(s.saved.water_stress_ml)} unit="mL" label="water impact saved" pct={s.pct_saved.water_stress_ml} Icon={DropIcon} />
            <Kpi value={sig(s.saved.energy_wh)} unit="Wh" label="energy saved" pct={s.pct_saved.energy_wh} Icon={BoltIcon} />
            <Kpi value={sig(s.saved.water_ml)} unit="mL" label="water saved" pct={s.pct_saved.water_ml} Icon={DropIcon} />
            <Kpi value={sig(s.saved.cost_usd * 100)} unit="¢" label="cost saved" pct={s.pct_saved.cost_usd} />
          </div>
          <p className="muted small mono">
            By model: {Object.entries(s.calls_by_model).map(([m, n]) => `${m} ${n}`).join(' · ')}
            {'  |  '}By region: {Object.entries(s.calls_by_region).map(([r, n]) => `${regionName(r)} ${n}`).join(' · ')}
          </p>
        </>
      )}
    </section>
  )
}

/* ---------- 2. 24-hour replay chart (/replay) ---------- */

const METRICS = {
  carbon: { key: 'gco2_per_kwh', label: 'Grid carbon', unit: 'g CO₂/kWh', Icon: BoltIcon },
  water: { key: 'stress_weighted_l_per_kwh', label: 'Water impact', unit: 'stress-weighted L/kWh', Icon: DropIcon },
}

function ReplayChart() {
  const [metric, setMetric] = useState('carbon')
  const [data, error] = usePolling(() => getReplay(24), 30 * 60_000)

  const chart = useMemo(() => {
    if (!data?.points?.length) return null
    const m = METRICS[metric].key
    const times = [...new Set(data.points.map((p) => p.ts))].sort()
    const regions = [...new Set(data.points.map((p) => p.region))]
    const series = regions.map((r) => ({
      region: r,
      values: times.map((t) => data.points.find((p) => p.ts === t && p.region === r)?.[m] ?? null),
    }))
    const all = series.flatMap((s) => s.values).filter((v) => v != null)
    const lo = Math.min(...all), hi = Math.max(...all), pad = (hi - lo) * 0.12 || 1
    const winners = Object.fromEntries(data.winners.map((w) => [w.ts, w[metric]]))

    // Biggest gap where West US wins: the solar story for the callout.
    let callout = null
    if (metric === 'carbon') {
      times.forEach((t, i) => {
        const w = series.find((s) => s.region === 'westus')?.values[i]
        const n = series.find((s) => s.region === 'northcentralus')?.values[i]
        if (w != null && n != null && n - w > (callout?.gap ?? 0)) callout = { i, gap: n - w, w, n }
      })
    }
    return { times, series, lo: lo - pad, hi: hi + pad, winners, callout }
  }, [data, metric])

  const W = 720, H = 280, L0 = 56, R0 = 16, T0 = 18, B0 = 40
  const x = (i) => L0 + (i / Math.max(chart?.times.length - 1, 1)) * (W - L0 - R0)
  const y = (v) => T0 + (1 - (v - chart.lo) / (chart.hi - chart.lo)) * (H - T0 - B0)
  const hourLabel = (ts) => new Date(ts).toLocaleTimeString('en-US', { hour: 'numeric', timeZone: PACIFIC })
  const dayLabel = (ts) => new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: PACIFIC })
  const { Icon } = METRICS[metric]

  return (
    <section className="card" aria-labelledby="replay-h">
      <div className="card-head impact-head">
        <div>
          <span className="step">24-HOUR REPLAY</span>
          <h2 id="replay-h">Where calls go, hour by hour</h2>
          <p className="muted small">Shaded band = the region the router picks that hour. Times are Pacific. Latest reported day from EIA (about a day behind real time).</p>
        </div>
        <div className="chips" role="group" aria-label="Metric">
          {Object.entries(METRICS).map(([k, v]) => (
            <button key={k} type="button" className={metric === k ? 'chip active' : 'chip'} aria-pressed={metric === k} onClick={() => setMetric(k)}>{v.label}</button>
          ))}
        </div>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {data && !chart && <p className="muted">No grid data yet. Run the EIA ingest job.</p>}
      {chart && (
        <>
          <svg className="replay" viewBox={`0 0 ${W} ${H}`} role="img"
            aria-label={`${METRICS[metric].label} by hour for ${chart.series.map((s) => regionName(s.region)).join(' and ')}`}>
            {chart.times.map((t, i) => {
              const step = (W - L0 - R0) / Math.max(chart.times.length - 1, 1)
              const winner = chart.winners[t]
              return winner && (
                <rect key={t} x={x(i) - step / 2} y={T0} width={step} height={H - T0 - B0}
                  fill={colorFor(winner)} opacity="0.1" />
              )
            })}
            {[0, 0.5, 1].map((f) => {
              const v = chart.lo + f * (chart.hi - chart.lo)
              return (
                <g key={f}>
                  <line x1={L0} x2={W - R0} y1={y(v)} y2={y(v)} stroke="#dce3cc" />
                  <text x={L0 - 8} y={y(v) + 4} textAnchor="end" className="axis">{sig(v)}</text>
                </g>
              )
            })}
            {chart.times.map((t, i) => (i % 3 === 0 ? (
              <text key={t} x={x(i)} y={H - B0 + 18} textAnchor="middle" className="axis">{hourLabel(t)}</text>
            ) : null))}
            <text x={L0} y={H - 6} className="axis">{dayLabel(chart.times[0])} – {dayLabel(chart.times.at(-1))}</text>
            {chart.series.map((s) => (
              <polyline key={s.region} fill="none" stroke={colorFor(s.region)} strokeWidth="3" strokeLinejoin="round"
                points={s.values.map((v, i) => (v == null ? null : `${x(i)},${y(v)}`)).filter(Boolean).join(' ')} />
            ))}
            {chart.callout && (
              <g>
                <line x1={x(chart.callout.i)} x2={x(chart.callout.i)} y1={y(chart.callout.n)} y2={y(chart.callout.w)} stroke="#1c3a3d" strokeDasharray="4 3" />
                <text x={Math.min(x(chart.callout.i) + 8, W - 200)} y={y(chart.callout.w) + 18} className="callout">
                  {hourLabel(chart.times[chart.callout.i])}: West US {Math.round(chart.callout.gap)} g/kWh cleaner
                </text>
              </g>
            )}
          </svg>
          <p className="legend small">
            <Icon /> {METRICS[metric].unit}
            {chart.series.map((s) => (
              <span key={s.region} className="legend-item"><i style={{ background: colorFor(s.region) }} /> {regionName(s.region)}</span>
            ))}
          </p>
        </>
      )}
    </section>
  )
}

/* ---------- 3. Map (/regions + USGS watershed outlines) ---------- */

// USGS Watershed Boundary Dataset, HUC8 layer, as simplified GeoJSON.
const wbdUrl = (huc8) =>
  `https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/4/query?where=huc8%3D%27${huc8}%27&outFields=huc8,name&outSR=4326&maxAllowableOffset=0.003&f=geojson`

function RegionMap() {
  const [regions, error] = usePolling(getRegions, 5 * 60_000)
  const box = useRef(null)
  const map = useRef(null)
  const layer = useRef(null)

  useEffect(() => {
    map.current = L.map(box.current, { scrollWheelZoom: false }).setView([39, -100], 4)
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri · Watersheds: USGS WBD',
        maxZoom: 16,
    }).addTo(map.current)
    layer.current = L.layerGroup().addTo(map.current)
    return () => map.current.remove()
  }, [])

  useEffect(() => {
    if (!regions || !layer.current) return
    let alive = true
    layer.current.clearLayers()
    const bounds = []

    regions.forEach((r) => {
      // Watershed outline, shaded by this month's stress (0-1).
      if (r.huc8) {
        fetch(wbdUrl(r.huc8)).then((res) => res.json()).then((geo) => {
          if (!alive) return
          L.geoJSON(geo, {
            style: { color: colorFor(r.region), weight: 1.5, fillColor: '#a3261b', fillOpacity: 0.1 + 0.5 * r.site_stress },
          }).bindTooltip(`HUC8 ${r.huc8} · water stress ${r.site_stress.toFixed(2)}`).addTo(layer.current)
        }).catch(() => {}) // outline is a nice-to-have; markers still show
      }
      // Power plants that set this grid's indirect water stress.
      r.plants.forEach((p) => {
        const fuel = FUEL[p.fuel] || { label: p.fuel, color: '#4e6461' }
        const sea = isSeawater(p.name)
        L.circleMarker([p.lat, p.lon], { radius: 5 + Math.sqrt(p.capacity_mw) / 12, color: '#fff', weight: 1.5, fillColor: fuel.color, fillOpacity: sea ? 0.45 : 0.9 })
          .bindPopup(`<strong>${p.name}</strong><br>${fuel.label} · ${Math.round(p.capacity_mw).toLocaleString()} MW${sea ? '<br>Seawater-cooled: no freshwater stress' : ''}<br><span class="mono">HUC12 ${p.huc12 ?? '—'}</span>`)
          .addTo(layer.current)
        bounds.push([p.lat, p.lon])
      })
      // The data center region itself.
      L.circleMarker([r.lat, r.lon], { radius: 12, color: '#fff', weight: 3, fillColor: colorFor(r.region), fillOpacity: 1 })
        .bindPopup(
          `<strong>${regionName(r.region)}</strong><br>` +
          `${r.gco2_per_kwh} g CO₂/kWh <span class="muted">(${r.grid_source})</span><br>` +
          `Water: ${r.water_l_per_kwh} L/kWh · impact ${r.stress_weighted_l_per_kwh} L/kWh<br>` +
          `Watershed stress ${r.site_stress.toFixed(2)} (HUC8 ${r.huc8 ?? '—'})`,
        )
        .addTo(layer.current)
      bounds.push([r.lat, r.lon])
    })
    if (bounds.length) map.current.fitBounds(bounds, { padding: [30, 30] })
    return () => { alive = false }
  }, [regions])

  return (
    <section className="card" aria-labelledby="map-h">
      <div className="card-head">
        <span className="step">WHERE THE IMPACT HAPPENS</span>
        <h2 id="map-h">Regions, watersheds and power plants</h2>
        <p className="muted small">Large dots: data center regions. Shaded areas: their local watershed (darker = more stressed). Small dots: the biggest plants per fuel on each grid, which set indirect water stress. Faded plants are seawater-cooled.</p>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <div ref={box} className="map" role="region" aria-label="Map of regions, watersheds and power plants" />
      <p className="legend small">
        {Object.entries(REGION_COLORS).map(([r, c]) => <span key={r} className="legend-item"><i style={{ background: c }} /> {regionName(r)}</span>)}
        {Object.values(FUEL).map((f) => <span key={f.label} className="legend-item"><i className="dot" style={{ background: f.color }} /> {f.label}</span>)}
      </p>
    </section>
  )
}

/* ---------- 4. Assumptions ---------- */

function Assumptions() {
  return (
    <details className="card assumptions">
      <summary><span className="step">METHOD</span> <strong>Data sources and assumptions</strong></summary>
      <ul className="small">
        <li>Grid carbon and generation water: EIA-930 hourly fuel mix (about a day behind), lifecycle emission factors (IPCC AR5) and water factors (Macknick et al. 2012). In-region generation only; imports excluded.</li>
        <li>Watershed stress: USGS National Water Availability Assessment, consumption ÷ streamflow by month (2010–2020), at the region's local watershed. City water may be imported from elsewhere.</li>
        <li>Indirect water: weighted per fuel by the hourly mix, using each grid's largest plants (EIA-860). Seawater-cooled plants count as zero freshwater stress.</li>
        <li>Data center efficiency: Microsoft Americas FY25, PUE 1.16 and WUE 0.34 L/kWh.</li>
        <li>Energy per token: Jegham et al. 2025, "How Hungry is AI?". GPT-4.1 mini uses GPT-4o's value as an upper bound; reasoning tokens may overstate large-model energy.</li>
        <li>Region locations are approximate (Azure publishes region coordinates, not facility sites).</li>
      </ul>
    </details>
  )
}

export default function Impact() {
  return (
    <>
      <section className="hero-dark small">
        <Bubbles />
        <div className="hero-inner">
          <div className="hero-copy">
            <p className="eyebrow">Grid & impact</p>
            <h1 className="display"><span className="line">Real grids.</span><br /><em className="line">Real watersheds.</em></h1>
            <p className="lede">What the router sees, hour by hour, and what it has saved so far.</p>
          </div>
        </div>
        <Waves />
      </section>
      <div className="surface">
        <div className="container">
          <Savings />
          <ReplayChart />
          <RegionMap />
          <Assumptions />
        </div>
      </div>
    </>
  )
}