// Settings controls shared by the Dashboard and the Live demo, so both pages always use the same values.
import { BoltIcon, DropIcon } from './art.jsx'

// Eco <-> Quality slider (the picker's user_preference). 50 = the validated default cutoff.
export const PREFERENCE_LABELS = { 0: 'Max eco', 25: 'Eco', 50: 'Balanced', 75: 'Quality', 100: 'Max quality' }

// Default settings for the whole app.
export const DEFAULT_SETTINGS = { quality: 50, cleanWhitespace: true, carbon: 70 }

// Request weights for /route and /complete from the carbon slider (0-100).
export const weightsFor = (carbon) => ({ carbon: carbon / 100, water: (100 - carbon) / 100 })

export function PreferenceControls({ settings, update }) {
  const { quality, cleanWhitespace } = settings
  return (
    <>
      <div className="slider-row">
        <span className="carbon slider-end"><BoltIcon /> Eco</span>
        <label htmlFor="quality" className="sr-only">Eco versus quality</label>
        <input
          id="quality"
          type="range"
          min="0"
          max="100"
          step="25"
          value={quality}
          onChange={(e) => update({ quality: Number(e.target.value) })}
          aria-valuetext={PREFERENCE_LABELS[quality]}
        />
        <span className="slider-end">Quality</span>
      </div>
      <p className="muted small pref-note">
        <strong>{PREFERENCE_LABELS[quality]}</strong>
        {quality === 50 ? ' (default): our validated cutoff.' : quality < 50 ? ': more prompts go to the small model.' : ': the large model is used unless the prompt is simple.'}
      </p>
      <label className="switch">
        <input type="checkbox" role="switch" checked={cleanWhitespace} onChange={(e) => update({ cleanWhitespace: e.target.checked })} />
        <span className="switch-track" aria-hidden="true" />
        <span className="small">Clean up extra spaces before scoring</span>
      </label>
    </>
  )
}

export function WeightSlider({ settings, update }) {
  const { carbon } = settings
  return (
    <div className="slider-row">
      <span className="carbon slider-end"><BoltIcon /> Carbon {carbon}%</span>
      <label htmlFor="weight" className="sr-only">Carbon versus water priority</label>
      <input
        id="weight"
        type="range"
        min="0"
        max="100"
        step="5"
        value={carbon}
        onChange={(e) => update({ carbon: Number(e.target.value) })}
        aria-valuetext={`Carbon ${carbon}%, water ${100 - carbon}%`}
      />
      <span className="water slider-end">Water {100 - carbon}% <DropIcon /></span>
    </div>
  )
}
