import { useState } from 'react'
import { pickModels, route } from './api.js'
import { Bubbles, Waves } from './art.jsx'
import { StickerLayer, useRipples } from './Stickers.jsx'
import { PREFERENCE_LABELS, PreferenceControls, WeightSlider, weightsFor } from './Controls.jsx'
import { DEMO_PROMPTS } from './demo.js'

const HERO_STICKERS = [
  { art: 'cloud', tilt: 8, delay: 0.4, style: { right: '8%', top: '18%' } },
  { art: 'drop', tilt: -10, delay: 0.8, style: { right: '24%', top: '52%' }, className: 'hide-sm' },
  { art: 'bolt', tilt: 12, delay: 1.2, style: { right: '3%', top: '58%' }, className: 'hide-sm' },
]

const REGION_LABELS = { westus: 'West US', northcentralus: 'North Central US' }

const LABEL_TEXT = { simple: 'Simple', medium: 'Medium', complex: 'Complex' }

// Average per-call savings scaled to 1M calls of this prompt mix (input is per-call Wh / g / mL).
const perMillion = (rows, f) => {
  const avg = rows.reduce((a, r) => a + f(r), 0) / rows.length
  const v = avg * 1000 // x 1,000,000 calls, / 1,000 to go Wh -> kWh, g -> kg, mL -> L
  return v >= 100 ? Math.round(v).toLocaleString() : v.toFixed(1)
}

// Spread rows across regions in proportion to the routed shares, interleaved (not all of one region first).
function assignRegions(n, distribution) {
  const regions = distribution.map((d) => ({ region: d.region, share: d.share, used: 0 }))
  return Array.from({ length: n }, (_, i) => {
    const next = regions.reduce((best, r) => (r.share * (i + 1) - r.used > best.share * (i + 1) - best.used ? r : best))
    next.used += 1
    return next.region
  })
}

export default function Demo({ settings, update }) {
  const [rows, setRows] = useState([])
  const [routing, setRouting] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  // Settings used for the results on screen; if the controls change afterwards, the results are out of date.
  const [ranWith, setRanWith] = useState(null)
  const [heroRipple, heroRipples] = useRipples()
  const [surfaceRipple, surfaceRipples] = useRipples()

  // Estimates only: uses the free /pick-model/batch and /route endpoints, never live model calls.
  async function run() {
    setRunning(true)
    setError('')
    setRows([])
    const used = { ...settings }
    setRanWith(used)
    try {
      const [routed, picked] = await Promise.all([
        route(weightsFor(used.carbon), DEMO_PROMPTS.length),
        pickModels(DEMO_PROMPTS.map((p) => p.text), used.quality / 100, used.cleanWhitespace),
      ])
      const regions = assignRegions(DEMO_PROMPTS.length, routed.distribution)
      setRouting(routed)
      setRows(DEMO_PROMPTS.map((p, i) => ({ ...p, pick: picked.results[i], region: regions[i] })))
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  const stale =
    ranWith !== null && !running &&
    (ranWith.quality !== settings.quality || ranWith.cleanWhitespace !== settings.cleanWhitespace || ranWith.carbon !== settings.carbon)
  // How often the picker agreed with the hand labels: simple -> small model, complex -> large model.
  const isSmall = (r) => r.pick.recommended_model !== r.pick.default_model
  const count = (label, test) => rows.filter((r) => r.label === label && test(r)).length
  const total = (label) => rows.filter((r) => r.label === label).length
  const smallCount = rows.filter(isSmall).length

  return (
    <>
      <section className="hero-dark small" onPointerDown={heroRipple}>
        <Bubbles />
        {heroRipples}
        <StickerLayer stickers={HERO_STICKERS} />
        <div className="hero-inner">
          <div className="hero-copy">
            <p className="eyebrow">Live demo</p>
            <h1 className="display">Same prompts. <em>Different footprint.</em></h1>
            <p className="lede">42 hand-labeled prompts, sent two ways. Estimates from the router; no live model calls.</p>
          </div>
        </div>
        <Waves />
      </section>
      <div className="surface" onPointerDown={surfaceRipple}>
        {surfaceRipples}
      <div className="container">
      <section className="card demo-settings" aria-label="Settings">
        <PreferenceControls settings={settings} update={update} />
        <WeightSlider settings={settings} update={update} />
        <p className="muted small">Shared with the Dashboard: change them on either page.</p>
      </section>

      <div className="demo-head">
        <div className="demo-actions">
          {stale && <span className="stale-note small">Settings changed — run again</span>}
          <span className="mono muted small" aria-live="polite">{rows.length ? `${rows.length} prompts scored` : `${DEMO_PROMPTS.length} prompts`}</span>
          <button type="button" className="btn" onClick={run} disabled={running}>
            {running ? 'Running…' : rows.length ? 'Run again' : 'Run demo'}
          </button>
        </div>
      </div>

      {error && <p className="error" role="alert">{error}</p>}

      {rows.length > 0 && (
        <>
          <section className="banner" aria-label="Projected savings at 1M calls of this prompt mix">
            <div><div className="small">Energy saved at 1M calls</div><div className="mono big">{perMillion(rows, (r) => r.pick.estimated_savings.energy_wh)} kWh</div></div>
            <div><div className="small">CO₂ saved at 1M calls</div><div className="mono big">{perMillion(rows, (r) => r.pick.estimated_savings.co2_g)} kg</div></div>
            <div><div className="small">Water saved at 1M calls</div><div className="mono big">{perMillion(rows, (r) => r.pick.estimated_savings.water_ml)} L</div></div>
          </section>
          <p className="muted small">
            {smallCount} of {rows.length} prompts went to the small model. Plus regional routing:{' '}
            {routing.savings.pct_co2 >= 0 ? `${routing.savings.pct_co2}% less` : `${-routing.savings.pct_co2}% more`} CO₂ and{' '}
            {routing.savings.pct_water_stress >= 0 ? `${routing.savings.pct_water_stress}% less` : `${-routing.savings.pct_water_stress}% more`} water impact than sending everything to{' '}
            {REGION_LABELS[routing.naive_baseline.region] || routing.naive_baseline.region}.
          </p>

          <section className="card agreement" aria-label="Agreement with hand labels">
            <div className="card-head">
              <h2>Picker vs. hand labels</h2>
              <p className="muted small">Hand labels are judgment calls, not ground truth. Medium prompts can reasonably go either way.</p>
            </div>
            <div className="agree-grid">
              <div><span className="mono big">{count('simple', isSmall)}/{total('simple')}</span><span className="small">simple → small model</span></div>
              <div><span className="mono big">{count('medium', isSmall)}/{total('medium')}</span><span className="small">medium → small model</span></div>
              <div><span className="mono big">{count('complex', (r) => !isSmall(r))}/{total('complex')}</span><span className="small">complex → large model</span></div>
            </div>
          </section>

          <section className="card featured" aria-labelledby="green-h">
            <div className="card-head">
              <h2 id="green-h">Every prompt, both ways</h2>
              <p className="muted small">
                Naive: every call → gpt-5-mini in {REGION_LABELS[routing.naive_baseline.region] || routing.naive_baseline.region}.
                {ranWith && ` Green Router at ${PREFERENCE_LABELS[ranWith.quality]}, carbon ${ranWith.carbon}% / water ${100 - ranWith.carbon}%.`}
              </p>
            </div>
            <div className="table-wrap">
              <table className="demo-table">
                <thead>
                  <tr><th scope="col">Prompt</th><th scope="col">Label</th><th scope="col">Naive</th><th scope="col">Green Router</th></tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.text}>
                      <td>{r.text}</td>
                      <td><span className={`label-tag ${r.label}`}>{LABEL_TEXT[r.label]}</span></td>
                      <td className="mono muted small">gpt-5-mini</td>
                      <td className={isSmall(r) ? 'mono small carbon' : 'mono small'}>
                        {r.pick.recommended_model}<br />
                        <span className="muted">{REGION_LABELS[r.region] || r.region}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
      </div>
      </div>
    </>
  )
}
