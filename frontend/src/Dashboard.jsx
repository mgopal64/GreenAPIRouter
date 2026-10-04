import { useEffect, useRef, useState } from 'react'
import { complete, pickModel, route } from './api.js'
import { BoltIcon, Bubbles, DropIcon, RouteDiagram, TankScene, UsageTank, Waves } from './art.jsx'
import { StickerLayer, useRipples } from './Stickers.jsx'

const SAMPLES = [
  { label: 'Grocery list', text: 'Make me a grocery list for tacos' },
  // Short but heavily constrained, so the picker sends it to the large model (~0.87 vs the 0.70 cutoff).
  { label: 'Haiku with rules', text: 'Write a haiku about autumn rain that mentions a bicycle, uses no adjectives, and ends with a question.' },
  { label: 'Detailed essay', text: 'Write a 500-word essay in iambic pentameter, with no letter e, comparing Kant and Hume, citing three sources, as a JSON object with keys intro, body, conclusion.' },
  { label: 'Summarize', text: 'Summarize this in one sentence: the city council met on Tuesday to discuss the new park budget.' },
]

const MODELS = [
  { id: 'gpt-4.1-mini', size: 'Small model', level: 0.3 },
  { id: 'gpt-5-mini', size: 'Large model', level: 0.85 },
]

// Draggable / poppable stickers. Hero ones sit in the gaps around the copy and art;
// "gutter" ones only show on wide screens, beside the cards.
const HERO_STICKERS = [
  { art: 'drop', tilt: -12, delay: 0.4, style: { left: '1%', top: '30%' } },
  { art: 'pin', tilt: 10, delay: 0.7, style: { right: '4%', top: '8%' } },
  { art: 'bolt', tilt: 14, delay: 1.0, style: { left: '47%', top: '10%' }, className: 'hide-sm' },
  { art: 'cloud', tilt: -6, delay: 1.3, style: { left: '44%', top: '66%' }, className: 'hide-sm' },
  { art: 'leaf', tilt: 18, delay: 1.6, style: { right: '3%', top: '76%' } },
  { art: 'chip', tilt: -10, delay: 1.9, style: { left: '58%', top: '70%' }, className: 'hide-sm' },
]
const GUTTER_STICKERS = [
  { art: 'wave', tilt: -8, style: { left: '6%', top: '120px' }, className: 'gutter' },
  { art: 'label', tilt: 7, style: { right: '5%', top: '240px' }, className: 'gutter' },
  { art: 'drop', tilt: 12, style: { left: '9%', top: '560px' }, className: 'gutter' },
  { art: 'bolt', tilt: -14, style: { right: '9%', top: '700px' }, className: 'gutter' },
  { art: 'leaf', tilt: -20, style: { left: '5%', top: '940px' }, className: 'gutter' },
]

const REGION_LABELS = { westus: 'West US', northcentralus: 'North Central US' }
const regionName = (id) => REGION_LABELS[id] || id

// Per-call savings are tiny; scaled to a million calls they're readable (input is per-call kWh, kg or L).
const perMillion = (x) => {
  const v = x * 1_000_000
  return v >= 100 ? Math.round(v).toLocaleString() : v.toFixed(1)
}

// Where the grid numbers came from (scoring.grid_at's fallback cascade), worded for the page.
const SOURCE_LABELS = {
  live: 'live EIA grid data',
  recent: 'EIA grid data from the last 6 hours',
  yesterday: "EIA grid data from this hour yesterday",
  typical: 'typical EIA values for this hour',
  static: 'static estimates (no live grid data yet)',
}
function sourceNote(distribution) {
  const sources = [...new Set(distribution.map((r) => r.grid_source))]
  return sources.map((s) => SOURCE_LABELS[s] || s).join(' + ')
}

// Whole-number percentages that always sum to 100 (largest-remainder rounding), so 37.6% + 62.4% shows 38% + 62%.
function percents(shares) {
  const raw = shares.map((s) => s * 100)
  const out = raw.map(Math.floor)
  const order = raw.map((v, i) => [v - Math.floor(v), i]).sort((a, b) => b[0] - a[0])
  const missing = 100 - out.reduce((a, b) => a + b, 0)
  for (let k = 0; k < missing; k++) out[order[k % order.length][1]]++
  return out
}

// Positive = saved; negative = routing made it worse (shown honestly, not hidden).
function Badge({ value, label, Icon, kind }) {
  if (value == null) return null
  const worse = value < 0
  return (
    <span className={`badge ${kind}${worse ? ' worse' : ''}`}>
      <Icon />
      <strong className="mono">{Math.abs(value)}%</strong> {worse ? 'more' : 'less'} {label}
    </span>
  )
}

// Each region is a reservoir; its water level is the share of traffic it gets.
function Reservoirs({ distribution }) {
  const west = [...distribution].sort((a, b) => a.lon - b.lon)
  const pct = percents(west.map((r) => r.share))
  return (
    <div className="reservoirs" role="img" aria-label={west.map((r, i) => `${regionName(r.region)}: ${pct[i]}% of calls`).join(', ')}>
      <TankScene shares={west.map((r) => r.share)} />
      <div className="tank-labels">
        {west.map((r, i) => (
          <div key={r.region} className="tank-col">
            <span className="tank-pct mono">{pct[i]}%</span>
            <span className="tank-label">{regionName(r.region)}</span>
            <span className="tank-meta mono">{r.grid_carbon_gco2_kwh} g CO₂/kWh · water stress {r.site_stress.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function heroRegions(distribution) {
  const west = [...distribution].sort((a, b) => a.lon - b.lon)
  const pct = percents(west.map((r) => r.share))
  return west.map((r, i) => ({ name: regionName(r.region), share: r.share, pct: pct[i], carbon: r.grid_carbon_gco2_kwh }))
}

const CostIcon = () => <span className="cost-icon" aria-hidden="true">$</span>

// Short, readable number for tiny per-call values (3 significant figures).
const sig = (x) => (x === 0 ? '0' : Number(x.toPrecision(3)).toString())

// Real impact of one live call, from Azure's actual token counts (accounting.py), vs the naive setup.
function LiveImpact({ impact }) {
  const { actual, pct_saved: pct } = impact
  return (
    <div className="live-impact">
      <p className="small">
        <strong>This call vs. naive</strong>{' '}
        <span className="muted">({impact.baseline_deployment} in {regionName(impact.baseline_region)}, same tokens)</span>
      </p>
      <p className="badges">
        <Badge value={pct.energy_wh} label="energy" Icon={BoltIcon} kind="carbon" />
        <Badge value={pct.co2_g} label="CO₂" Icon={BoltIcon} kind="carbon" />
        <Badge value={pct.water_stress_ml} label="water impact" Icon={DropIcon} kind="water" />
        <Badge value={pct.cost_usd} label="cost" Icon={CostIcon} kind="neutral" />
      </p>
      <p className="muted small mono">
        Used {sig(actual.energy_wh)} Wh · {sig(actual.co2_g)} g CO₂ · {sig(actual.water_ml)} mL water · ${sig(actual.cost_usd)}
        {' '}— from real token counts, {impact.grid_source === 'static' ? 'static grid estimates' : `${impact.grid_source} EIA grid data`}.
      </p>
    </div>
  )
}

export default function Dashboard() {
  const [prompt, setPrompt] = useState(SAMPLES[0].text)
  const [pick, setPick] = useState(null)
  const [pickError, setPickError] = useState('')
  const [picking, setPicking] = useState(false)

  const [carbon, setCarbon] = useState(70)
  const [routing, setRouting] = useState(null)
  const [routeError, setRouteError] = useState('')

  const [showLive, setShowLive] = useState(false)
  const [demoKey, setDemoKey] = useState('')
  const [live, setLive] = useState(null)
  const [liveError, setLiveError] = useState('')
  const [sending, setSending] = useState(false)

  const [heroRipple, heroRipples] = useRipples()
  const [surfaceRipple, surfaceRipples] = useRipples()

  // The prompt whose answer is on screen. If the textbox no longer matches it, the result is marked out of date.
  const [pickedText, setPickedText] = useState(null)
  // The prompt most recently sent; a slow reply to an older click can't overwrite a newer one.
  const latest = useRef(null)

  async function optimize(text) {
    if (!text.trim()) return
    latest.current = text
    setPicking(true)
    setPickError('')
    try {
      const result = await pickModel(text)
      if (latest.current === text) {
        setPick(result)
        setPickedText(text)
      }
    } catch (e) {
      if (latest.current === text) setPickError(e.message)
    } finally {
      if (latest.current === text) setPicking(false)
    }
  }

  // Pick for the starting sample once on load; after that the picker only runs on Optimize, Enter or a sample chip.
  useEffect(() => {
    optimize(SAMPLES[0].text)
  }, [])

  const stale = pick && pickedText !== null && prompt.trim() !== pickedText.trim()

  // Re-route when the slider settles (debounced so dragging doesn't hit the rate limit).
  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        setRouteError('')
        setRouting(await route({ carbon: carbon / 100, water: (100 - carbon) / 100 }))
      } catch (e) {
        setRouteError(e.message)
      }
    }, 300)
    return () => clearTimeout(t)
  }, [carbon])

  async function sendLive() {
    setSending(true)
    setLiveError('')
    setLive(null)
    try {
      setLive(await complete(prompt, { carbon: carbon / 100, water: (100 - carbon) / 100 }, demoKey))
    } catch (e) {
      setLiveError(e.message)
    } finally {
      setSending(false)
    }
  }

  return (
    <>
      <section className="hero-dark" onPointerDown={heroRipple}>
        <Bubbles />
        {heroRipples}
        <StickerLayer stickers={HERO_STICKERS} />
        <div className="hero-inner">
          <div className="hero-copy">
            <p className="eyebrow">Green AI router · Azure</p>
            <h1 className="display">
              <span className="line">Same answers.</span>
              <br />
              <em className="line">Smaller footprint.</em>
            </h1>
            <p className="lede">Every prompt gets the most efficient model that can answer it, routed to cleaner grids.</p>
            <a href="#optimize" className="btn-cta">Start optimizing</a>
            <p className="hint mono">Drag the stickers · click one to pop it · click the water</p>
          </div>
          <RouteDiagram
            className="hero-art"
            model={pick?.recommended_model}
            regions={routing && heroRegions(routing.distribution)}
          />
        </div>
        <Waves />
      </section>

      <div className="surface" onPointerDown={surfaceRipple}>
        {surfaceRipples}
        <StickerLayer stickers={GUTTER_STICKERS} />
        <div className="flow">
          <section id="optimize" className="card" aria-labelledby="opt-h">
            <div className="card-head">
              <span className="step">STEP 1</span>
              <h2 id="opt-h">Optimize model</h2>
            </div>
            <form
              className="stack"
              onSubmit={(e) => {
                e.preventDefault()
                optimize(prompt)
              }}
            >
              <label htmlFor="prompt" className="sr-only">Your prompt</label>
              <textarea
                id="prompt"
                rows={3}
                maxLength={4000}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => {
                  // Enter runs the picker; Shift+Enter still adds a new line.
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    optimize(prompt)
                  }
                }}
                placeholder="Type your own prompt…"
              />
              <div className="chips">
                {SAMPLES.map((s) => (
                  <button
                    key={s.label}
                    type="button"
                    className={prompt === s.text ? 'chip active' : 'chip'}
                    aria-pressed={prompt === s.text}
                    onClick={() => {
                      setPrompt(s.text)
                      optimize(s.text)
                    }}
                  >
                    {s.label}
                  </button>
                ))}
                <button type="submit" className="btn push-right" disabled={picking || !prompt.trim()}>
                  Optimize
                </button>
              </div>
            </form>
            {pickError && <p className="error" role="alert">{pickError}</p>}
            {pick && (
              <>
                {stale && <p className="stale-note small">Prompt changed — press Optimize to update.</p>}
                <div className={stale ? 'models stale' : picking ? 'models busy' : 'models'} aria-live="polite" aria-busy={picking}>
                  {MODELS.map(({ id, size, level }) => {
                    const chosen = pick.recommended_model === id
                    return (
                      <div key={id} className={chosen ? 'model chosen' : 'model'}>
                        {chosen && <span className="model-tag">Recommended</span>}
                        <UsageTank level={level} />
                        <span className="mono">{id}</span>
                        <span className="muted small">{size}</span>
                      </div>
                    )
                  })}
                </div>
                {pick.recommended_model !== pick.default_model ? (
                  <div className={stale ? 'result stale' : 'result'}>
                    <span className="badge carbon">
                      <BoltIcon /> at 1M calls, saves <strong className="mono">{perMillion(pick.estimated_savings.energy_wh / 1000)} kWh</strong> · <strong className="mono">{perMillion(pick.estimated_savings.co2_g / 1000)} kg</strong> CO₂ · <strong className="mono">{perMillion(pick.estimated_savings.water_ml / 1000)} L</strong> water
                    </span>
                    {pick.token_estimate && (
                      <p className="muted small token-note">
                        Estimated from ~{pick.token_estimate.prompt_tokens} prompt tokens + ~{pick.token_estimate.completion_tokens} answer tokens
                        ({pick.estimated_savings.energy_wh} Wh per call). Live calls use Azure's real token counts.
                      </p>
                    )}
                  </div>
                ) : (
                  <p className={stale ? 'result muted stale' : 'result muted'}>This prompt needs the larger model.</p>
                )}
              </>
            )}
          </section>

          <section className="card" aria-labelledby="route-h">
            <div className="card-head">
              <span className="step">STEP 2</span>
              <h2 id="route-h">Route across regions</h2>
            </div>
            <div className="slider-row">
              <span className="carbon slider-end"><BoltIcon /> Carbon {carbon}%</span>
              <label htmlFor="weight" className="sr-only">Carbon versus water priority</label>
              <input id="weight" type="range" min="0" max="100" step="5" value={carbon} onChange={(e) => setCarbon(Number(e.target.value))} aria-valuetext={`Carbon ${carbon}%, water ${100 - carbon}%`} />
              <span className="water slider-end">Water {100 - carbon}% <DropIcon /></span>
            </div>
            {routeError && <p className="error" role="alert">{routeError}</p>}
            {routing && (
              <>
                <Reservoirs distribution={routing.distribution} />
                <p className="result badges">
                  <Badge value={routing.savings.pct_co2} label="CO₂" Icon={BoltIcon} kind="carbon" />
                  <Badge value={routing.savings.pct_water_stress} label="water impact" Icon={DropIcon} kind="water" />
                  <span className="muted small">vs. sending everything to {regionName(routing.naive_baseline.region)}</span>
                </p>
                <p className="muted small source-note">
                  Water impact = liters used × how stressed the local watershed is (0–1). Based on {sourceNote(routing.distribution)}.
                </p>
              </>
            )}
          </section>

          {!showLive ? (
            <button type="button" className="btn secondary center" onClick={() => setShowLive(true)}>
              Send it live
            </button>
          ) : (
            <section className="card" aria-labelledby="live-h">
              <div className="card-head">
                <span className="step">STEP 3</span>
                <h2 id="live-h">Send it live</h2>
                <p className="muted small">Sends the prompt above to the real model. Needs the demo key.</p>
              </div>
              <form
                className="live-form"
                onSubmit={(e) => {
                  e.preventDefault()
                  sendLive()
                }}
              >
                <label htmlFor="key" className="sr-only">Demo key</label>
                <input id="key" type="password" autoComplete="off" value={demoKey} onChange={(e) => setDemoKey(e.target.value)} placeholder="Demo key" />
                <button type="submit" className="btn" disabled={sending || !demoKey || !prompt.trim()}>
                  {sending ? 'Sending…' : 'Send to Azure'}
                </button>
              </form>
              {liveError && <p className="error" role="alert">{liveError}</p>}
              {live && (
                <>
                  <p className="muted small mono">{live.deployment} · {regionName(live.region)} · {live.prompt_tokens} in / {live.completion_tokens} out</p>
                  {/* Plain text only: React escapes this, so model output can never inject HTML. */}
                  <p className="answer">{live.output || '(empty response)'}</p>
                  {live.impact && <LiveImpact impact={live.impact} />}
                </>
              )}
            </section>
          )}
        </div>
      </div>
    </>
  )
}
