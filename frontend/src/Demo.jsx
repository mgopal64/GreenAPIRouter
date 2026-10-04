import { useState } from 'react'
import { pickModels, route } from './api.js'
import { BoltIcon, Bubbles, DropIcon, Waves } from './art.jsx'
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

// Green pill for savings, red for increases (shown honestly, not hidden).
function Change({ pct, label, Icon, kind }) {
  const worse = pct < 0
  return (
    <span className={`badge ${kind}${worse ? ' worse' : ''}`}>
      <Icon /> <strong className="mono">{Math.abs(pct)}%</strong> {worse ? 'more' : 'less'} {label}
    </span>
  )
}

// Does the picker's choice match the hand label? Medium can go either way.
const matches = (r) => r.label === 'medium' || (r.label === 'simple') === (r.pick.recommended_model !== r.pick.default_model)

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
            <p className="lede">{DEMO_PROMPTS.length} hand-labeled prompts, sent two ways. Estimates from the router; no live model calls.</p>
          </div>
        </div>
        <Waves />
      </section>
      <div className="surface" onPointerDown={surfaceRipple}>
        {surfaceRipples}
      <div className="container">
      <section className="card demo-settings" aria-labelledby="settings-h">
        <div className="card-head">
          <span className="step">STEP 1</span>
          <h2 id="settings-h">Choose settings</h2>
          <p className="muted small">Shared with the Dashboard: change them on either page.</p>
        </div>
        <PreferenceControls settings={settings} update={update} />
        <WeightSlider settings={settings} update={update} />
        <div className="demo-actions">
          {stale && <span className="stale-note small">Settings changed — run again</span>}
          <button type="button" className="btn" onClick={run} disabled={running}>
            {running ? 'Running…' : rows.length ? `Run again` : `Run ${DEMO_PROMPTS.length} prompts`}
          </button>
        </div>
      </section>

      {error && <p className="error" role="alert">{error}</p>}

      {rows.length > 0 && (
        <>
          <section className="card results" aria-labelledby="results-h" aria-live="polite">
            <div className="card-head">
              <span className="step">STEP 2</span>
              <h2 id="results-h">
                {smallCount} of {rows.length} prompts went to the smaller model
              </h2>
              <p className="muted">
                Naive setup: every prompt → gpt-5-mini in {REGION_LABELS[routing.naive_baseline.region] || routing.naive_baseline.region}.
              </p>
            </div>

            <p className="kpi-caption">If you sent 1 million prompts like these, right-sizing the model would save:</p>
            <div className="kpis">
              <div className="kpi"><span className="kpi-value mono">{perMillion(rows, (r) => r.pick.estimated_savings.energy_wh)} kWh</span><span className="kpi-label">energy</span></div>
              <div className="kpi"><span className="kpi-value mono">{perMillion(rows, (r) => r.pick.estimated_savings.co2_g)} kg</span><span className="kpi-label">CO₂</span></div>
              <div className="kpi"><span className="kpi-value mono">{perMillion(rows, (r) => r.pick.estimated_savings.water_ml)} L</span><span className="kpi-label">water</span></div>
            </div>

            <div className="routing-line">
              <span>On top of that, routing across regions gives:</span>
              <Change pct={routing.savings.pct_co2} label="CO₂" Icon={BoltIcon} kind="carbon" />
              <Change pct={routing.savings.pct_water_stress} label="water impact" Icon={DropIcon} kind="water" />
            </div>
          </section>

          <section className="card" aria-labelledby="agree-h">
            <div className="card-head">
              <h2 id="agree-h">Did the picker agree with the hand labels?</h2>
              <p className="muted small">
                Hand labels are judgment calls, not ground truth.{total('medium') > 0 && ' Medium prompts can reasonably go either way.'}
              </p>
            </div>
            {/* Only show the label groups that exist in demo.js */}
            <ul className="agree-list">
              {total('simple') > 0 && (
                <li><strong className="mono">{count('simple', isSmall)} of {total('simple')}</strong> simple prompts → small model {count('simple', isSmall) === total('simple') && '✓'}</li>
              )}
              {total('medium') > 0 && (
                <li><strong className="mono">{count('medium', isSmall)} of {total('medium')}</strong> medium prompts → small model</li>
              )}
              {total('complex') > 0 && (
                <li><strong className="mono">{count('complex', (r) => !isSmall(r))} of {total('complex')}</strong> complex prompts → large model {count('complex', (r) => !isSmall(r)) === total('complex') && '✓'}</li>
              )}
            </ul>
          </section>

          <section className="card" aria-labelledby="table-h">
            <div className="card-head">
              <h2 id="table-h">Every prompt</h2>
              <p className="muted small">
                {ranWith && `Green Router at ${PREFERENCE_LABELS[ranWith.quality]}, carbon ${ranWith.carbon}% / water ${100 - ranWith.carbon}%. `}
                Rows marked ⚠ are where the picker disagreed with the hand label.
              </p>
            </div>
            <div className="table-wrap">
              <table className="demo-table">
                <thead>
                  <tr><th scope="col">Prompt</th><th scope="col">Label</th><th scope="col">Model</th><th scope="col">Region</th></tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.text} className={matches(r) ? undefined : 'mismatch'}>
                      <td>{!matches(r) && <span className="warn" title="Differs from the hand label">⚠ </span>}{r.text}</td>
                      <td><span className={`label-tag ${r.label}`}>{LABEL_TEXT[r.label]}</span></td>
                      <td>
                        <span className={isSmall(r) ? 'model-chip small' : 'model-chip large'}>{isSmall(r) ? 'Small' : 'Large'}</span>
                        <span className="mono muted model-id">{r.pick.recommended_model}</span>
                      </td>
                      <td>{REGION_LABELS[r.region] || r.region}</td>
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
