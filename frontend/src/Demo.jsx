import { useState } from 'react'
import { pickModel, route } from './api.js'
import { Bubbles, Waves } from './art.jsx'
import { StickerLayer, useRipples } from './Stickers.jsx'

// Varied prompts, scored with the real picker (constraint score; >= 0.70 goes to the large model).
// Mostly everyday asks that the small model handles, plus a few with many hard constraints.
const PROMPTS = [
  'Make me a grocery list for tacos', // 0.04 small
  'Plan a 5-day Japan itinerary for two vegetarians on a $2,000 budget, avoiding flights, with one rest day, formatted as a table.', // 0.77 large
  'What is the capital of Australia?', // 0.01 small
  'Why does my Python recursion hit max depth? def f(n): return f(n-1)', // 0.03 small
  'Write a cover letter for a data analyst role in under 200 words, formal tone, mention SQL and Tableau, and end with a call to action.', // 0.94 large
  'Summarize this in one sentence: the city council met on Tuesday to discuss the new park budget.', // 0.11 small
  'Translate "good morning" into Spanish', // 0.13 small
  'Write a haiku about autumn rain that mentions a bicycle, uses no adjectives, and ends with a question.', // 0.87 large
  'Explain step by step how to derive the quadratic formula', // 0.59 small
  'Write a short thank-you note to my team', // 0.30 small
]

const HERO_STICKERS = [
  { art: 'cloud', tilt: 8, delay: 0.4, style: { right: '8%', top: '18%' } },
  { art: 'drop', tilt: -10, delay: 0.8, style: { right: '24%', top: '52%' }, className: 'hide-sm' },
  { art: 'bolt', tilt: 12, delay: 1.2, style: { right: '3%', top: '58%' }, className: 'hide-sm' },
]

const REGION_LABELS = { westus: 'West US', northcentralus: 'North Central US' }

const sum = (xs, f) => Math.round(xs.reduce((a, x) => a + f(x), 0) * 100) / 100

export default function Demo() {
  const [rows, setRows] = useState([])
  const [routing, setRouting] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')
  const [heroRipple, heroRipples] = useRipples()
  const [surfaceRipple, surfaceRipples] = useRipples()

  // Estimates only: uses the free /pick-model and /route endpoints, never live model calls.
  async function run() {
    setRunning(true)
    setError('')
    setRows([])
    try {
      setRouting(await route({ carbon: 0.5, water: 0.5 }, PROMPTS.length))
      for (const prompt of PROMPTS) {
        const pick = await pickModel(prompt)
        setRows((prev) => [...prev, { prompt, pick }])
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  const topRegion = routing ? [...routing.distribution].sort((a, b) => b.share - a.share)[0].region : null
  const saved = {
    energy: sum(rows, (r) => r.pick.estimated_savings.energy_wh),
    co2: sum(rows, (r) => r.pick.estimated_savings.co2_g),
    water: sum(rows, (r) => r.pick.estimated_savings.water_ml),
  }

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
            <p className="lede">The same batch of prompts, sent two ways. Estimates from the router; no live model calls.</p>
          </div>
        </div>
        <Waves />
      </section>
      <div className="surface" onPointerDown={surfaceRipple}>
        {surfaceRipples}
      <div className="container">
      <div className="demo-head">
        <div className="demo-actions">
          <span className="mono muted small" aria-live="polite">{rows.length} / {PROMPTS.length} prompts</span>
          <button type="button" className="btn" onClick={run} disabled={running}>
            {running ? 'Running…' : rows.length ? 'Run again' : 'Run demo'}
          </button>
        </div>
      </div>

      {error && <p className="error" role="alert">{error}</p>}

      <section className="banner" aria-label="Savings from right-sizing models">
        <div><div className="small">Energy saved</div><div className="mono big">{saved.energy} Wh</div></div>
        <div><div className="small">CO₂ saved</div><div className="mono big">{saved.co2} g</div></div>
        <div><div className="small">Water saved</div><div className="mono big">{saved.water} mL</div></div>
      </section>
      {routing && (
        <p className="muted small">
          Plus regional routing: {routing.savings.pct_co2 >= 0 ? `${routing.savings.pct_co2}% less` : `${-routing.savings.pct_co2}% more`} CO₂ and{' '}
          {routing.savings.pct_water_stress >= 0 ? `${routing.savings.pct_water_stress}% less` : `${-routing.savings.pct_water_stress}% more`} water impact than sending everything to{' '}
          {REGION_LABELS[routing.naive_baseline.region] || routing.naive_baseline.region}.
        </p>
      )}

      <div className="row">
        <section className="card" aria-labelledby="naive-h">
          <div className="card-head">
            <h2 id="naive-h">Naive</h2>
            <p className="muted small">Every call → gpt-5-mini in North Central US</p>
          </div>
          <ul className="log">
            {rows.map((r) => (
              <li key={r.prompt}>
                <span>{r.prompt}</span>
                <span className="mono muted small">{r.pick.default_model} · North Central US</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="card featured" aria-labelledby="green-h">
          <div className="card-head">
            <h2 id="green-h">With Green Router</h2>
            <p className="muted small">Right-sized model, greener region</p>
          </div>
          <ul className="log">
            {rows.map((r) => (
              <li key={r.prompt}>
                <span>{r.prompt}</span>
                <span className="mono small carbon">{r.pick.recommended_model} · {REGION_LABELS[topRegion] || topRegion}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
      </div>
      </div>
    </>
  )
}
