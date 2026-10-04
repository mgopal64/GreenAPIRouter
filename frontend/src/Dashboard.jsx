import { useEffect, useRef, useState } from 'react'
import { API_URL, complete, pickModel, route } from './api.js'
import { BoltIcon, Bubbles, DropIcon, RouteDiagram, TankScene, UsageTank, Waves } from './art.jsx'
import { StickerLayer, useRipples } from './Stickers.jsx'
import { PreferenceControls, WeightSlider, weightsFor } from './Controls.jsx'

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
  return west.map((r, i) => ({
    name: regionName(r.region), share: r.share, pct: pct[i],
    carbon: r.grid_carbon_gco2_kwh,
    water: r.stress_weighted_l_per_kwh, // liters per kWh weighted by watershed stress: what routing minimizes
  }))
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

// The MCP server's tools, in plain words (see mcp_server/server.py).
const MCP_TOOLS = [
  ['pick_model', 'lightest model for a prompt'],
  ['pick_models', 'the same for up to 50 prompts'],
  ['route_calls', 'split calls across greener regions'],
  ['savings_so_far', 'real savings from live calls'],
  ['region_snapshot', 'why a region is preferred now'],
  ['grid_replay', 'the best region, hour by hour'],
]

function AgentsCard() {
  const [copied, setCopied] = useState(false)
  const cmd = [
    'git clone https://github.com/mgopal64/GreenAPIRouter && cd GreenAPIRouter',
    'pip install -r mcp_server/requirements.txt',
    `claude mcp add green-router -e GREENROUTER_URL=${API_URL} -- python "$PWD/mcp_server/server.py"`,
  ].join('\n')
  async function copy() {
    try {
      await navigator.clipboard.writeText(cmd)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false) // clipboard blocked: the command is still selectable
    }
  }
  return (
    <section className="card" aria-labelledby="agents-h">
      <div className="card-head">
        <span className="step">FOR AI AGENTS</span>
        <h2 id="agents-h">Use Green Router as a tool</h2>
        <p className="muted small">
          An MCP server lets assistants like Claude ask Green Router before they call a model. It runs on your machine and is
          read-only, so it can't make paid calls.
        </p>
      </div>
      <ul className="tool-list">
        {MCP_TOOLS.map(([name, what]) => (
          <li key={name}>
            <span className="mono tool-name">{name}</span>
            <span className="muted">{what}</span>
          </li>
        ))}
      </ul>
      <div className="cmd">
        <pre className="mono">{cmd}</pre>
        <button type="button" className="btn secondary cmd-copy" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
      </div>
      <a className="small readme-link" href="https://github.com/mgopal64/GreenAPIRouter#mcp-server" target="_blank" rel="noreferrer">
        Full setup in the README →
      </a>
    </section>
  )
}

export default function Dashboard({ settings, update }) {
  const { quality, cleanWhitespace, carbon } = settings
  const [prompt, setPrompt] = useState(SAMPLES[0].text)
  const [pick, setPick] = useState(null)
  const [pickError, setPickError] = useState('')
  const [picking, setPicking] = useState(false)

  const [routing, setRouting] = useState(null)
  const [routeError, setRouteError] = useState('')

  const [showLive, setShowLive] = useState(false)
  const [demoKey, setDemoKey] = useState('')
  const [live, setLive] = useState(null)
  const [liveError, setLiveError] = useState('')
  const [sending, setSending] = useState(false)

  const [heroRipple, heroRipples] = useRipples()
  const [surfaceRipple, surfaceRipples] = useRipples()

  // The prompt + setting whose answer is on screen. If either changes, the result is marked out of date.
  const [picked, setPicked] = useState(null)
  // The request most recently sent; a slow reply to an older click can't overwrite a newer one.
  const latest = useRef(null)

  async function optimize(text) {
    if (!text.trim()) return
    const key = `${quality}|${cleanWhitespace}|${text}`
    latest.current = key
    setPicking(true)
    setPickError('')
    try {
      const result = await pickModel(text, quality / 100, cleanWhitespace)
      if (latest.current === key) {
        setPick(result)
        setPicked({ text, quality, cleanWhitespace })
      }
    } catch (e) {
      if (latest.current === key) setPickError(e.message)
    } finally {
      if (latest.current === key) setPicking(false)
    }
  }

  // Pick for the starting sample once on load; after that the picker only runs on Optimize, Enter or a sample chip.
  useEffect(() => {
    optimize(SAMPLES[0].text)
    // oxlint-disable-next-line react-hooks/exhaustive-deps -- intentionally runs once, on load
  }, [])

  const stale =
    pick && picked !== null &&
    (prompt.trim() !== picked.text.trim() || quality !== picked.quality || cleanWhitespace !== picked.cleanWhitespace)

  // Re-route when the slider settles (debounced so dragging doesn't hit the rate limit).
  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        setRouteError('')
        setRouting(await route(weightsFor(carbon)))
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
      setLive(await complete(prompt, weightsFor(carbon), demoKey, quality / 100, cleanWhitespace))
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
              <PreferenceControls settings={settings} update={update} />
            </form>
            {pickError && <p className="error" role="alert">{pickError}</p>}
            {pick && (
              <>
                {stale && <p className="stale-note small">Prompt or setting changed — press Optimize to update.</p>}
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
                  <p className={stale ? 'result muted stale' : 'result muted'}>{picked && picked.quality > 50 ? 'Large model chosen at this quality setting.' : 'This prompt needs the larger model.'}</p>
                )}
              </>
            )}
          </section>

          <section className="card" aria-labelledby="route-h">
            <div className="card-head">
              <span className="step">STEP 2</span>
              <h2 id="route-h">Route across regions</h2>
            </div>
            <WeightSlider settings={settings} update={update} />
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
          <AgentsCard />
        </div>
      </div>
    </>
  )
}
