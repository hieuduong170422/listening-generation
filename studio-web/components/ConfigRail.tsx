'use client'

import { useEffect, useState } from 'react'
import { useStudio } from '@/lib/store'
import { fetchVoices, generateOutline, suggestTopics, ApiError } from '@/lib/api'
import type { Voice, StudioConfig } from '@/lib/types'

const LANGUAGES = [
  { value: 'vi', label: 'Tiếng Việt' },
  { value: 'en', label: 'English' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
  { value: 'zh', label: '中文' },
]

const STYLES = [
  { value: 'podcast', label: 'Podcast' },
  { value: 'interview', label: 'Interview' },
  { value: 'monologue', label: 'Monologue' },
  { value: 'documentary', label: 'Documentary' },
]

const AUDIENCE_LEVELS = [
  { value: 'beginner', label: 'Beginner' },
  { value: 'intermediate', label: 'Intermediate' },
  { value: 'advanced', label: 'Advanced' },
  { value: 'expert', label: 'Expert' },
]

const TONES = [
  { value: 'conversational', label: 'Conversational' },
  { value: 'formal', label: 'Formal' },
  { value: 'casual', label: 'Casual' },
  { value: 'educational', label: 'Educational' },
  { value: 'entertaining', label: 'Entertaining' },
]

const EL_MODELS = [
  { value: 'eleven_flash_v2_5', label: 'Flash v2.5 (Fast)' },
  { value: 'eleven_multilingual_v2', label: 'Multilingual v2' },
  { value: 'eleven_turbo_v2_5', label: 'Turbo v2.5' },
]

const TEXT_MODELS = [
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
  { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
  { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
]

const s = {
  label: {
    display: 'block',
    fontSize: '0.75rem',
    fontWeight: 500,
    color: 'var(--t2)',
    marginBottom: '0.375rem',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.04em',
  },
  input: {
    width: '100%',
    padding: '0.5rem 0.625rem',
    backgroundColor: 'var(--bg2)',
    border: '1px solid var(--bd)',
    borderRadius: '6px',
    color: 'var(--t1)',
    fontSize: '0.8125rem',
    outline: 'none',
  },
  select: {
    width: '100%',
    padding: '0.5rem 0.625rem',
    backgroundColor: 'var(--bg2)',
    border: '1px solid var(--bd)',
    borderRadius: '6px',
    color: 'var(--t1)',
    fontSize: '0.8125rem',
    outline: 'none',
    cursor: 'pointer',
  },
  section: {
    marginBottom: '1.25rem',
  },
  row: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '0.5rem',
  },
  fieldGroup: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.375rem',
  },
  sliderRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
  },
  sliderVal: {
    fontSize: '0.75rem',
    color: 'var(--t2)',
    minWidth: '2.5rem',
    textAlign: 'right' as const,
    fontVariantNumeric: 'tabular-nums' as const,
  },
  divider: {
    height: '1px',
    backgroundColor: 'var(--bd-s)',
    margin: '1rem 0',
  },
  sectionTitle: {
    fontSize: '0.6875rem',
    fontWeight: 600,
    color: 'var(--t3)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.06em',
    marginBottom: '0.75rem',
  },
}

interface ConfigRailProps {
  className?: string
}

export default function ConfigRail({ className }: ConfigRailProps) {
  const { state, dispatch } = useStudio()
  const cfg = state.config
  const [voices, setVoices] = useState<Voice[]>([])
  const [voicesLoading, setVoicesLoading] = useState(false)
  const [suggesting, setSuggesting] = useState(false)
  const [suggestions, setSuggestions] = useState<string[]>([])

  useEffect(() => {
    setVoicesLoading(true)
    fetchVoices()
      .then(setVoices)
      .catch(() => setVoices([]))
      .finally(() => setVoicesLoading(false))
  }, [])

  function patch(p: Partial<StudioConfig>) {
    dispatch({ type: 'PATCH_CONFIG', patch: p })
  }

  function patchEl(p: Partial<StudioConfig['el_config']>) {
    dispatch({ type: 'PATCH_CONFIG', patch: { el_config: { ...cfg.el_config, ...p } } })
  }

  async function handleSuggest() {
    setSuggesting(true)
    setSuggestions([])
    try {
      const res = await suggestTopics({
        topic: cfg.topic,
        language: cfg.language,
        count: 6,
        text_model: cfg.text_model,
        audience_level: cfg.audience_level,
        tone: cfg.tone,
      })
      setSuggestions(res.suggestions)
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Could not fetch suggestions'
      dispatch({ type: 'SET_ERROR', message: msg })
    } finally {
      setSuggesting(false)
    }
  }

  async function handleGenerateOutline() {
    if (!cfg.topic.trim()) {
      dispatch({ type: 'SET_ERROR', message: 'Please enter a topic first' })
      return
    }
    dispatch({ type: 'SET_GENERATING_OUTLINE', value: true })
    dispatch({ type: 'SET_ERROR', message: null })
    try {
      const res = await generateOutline(cfg)
      dispatch({ type: 'SET_OUTLINE', outline: res.outline })
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Outline generation failed'
      dispatch({ type: 'SET_ERROR', message: msg })
    } finally {
      dispatch({ type: 'SET_GENERATING_OUTLINE', value: false })
    }
  }

  const numSpeakers = cfg.num_speakers

  return (
    <aside
      className={className}
      style={{
        width: '280px',
        flexShrink: 0,
        backgroundColor: 'var(--bg1)',
        borderRight: '1px solid var(--bd)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Scrollable body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '1rem' }}>

        {/* Topic */}
        <div style={s.section}>
          <p style={s.sectionTitle}>Topic</p>
          <div style={s.fieldGroup}>
            <textarea
              value={cfg.topic}
              onChange={(e) => patch({ topic: e.target.value })}
              rows={3}
              placeholder="What is this episode about?"
              style={{
                ...s.input,
                resize: 'vertical',
                lineHeight: 1.5,
                fontFamily: 'inherit',
              }}
            />
            <button
              onClick={handleSuggest}
              disabled={suggesting}
              style={{
                padding: '0.375rem 0.625rem',
                backgroundColor: 'var(--bg3)',
                border: '1px solid var(--bd)',
                borderRadius: '5px',
                color: suggesting ? 'var(--t3)' : 'var(--t2)',
                fontSize: '0.75rem',
                cursor: suggesting ? 'default' : 'pointer',
              }}
            >
              {suggesting ? 'Suggesting…' : '✦ Suggest topics'}
            </button>

            {suggestions.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => { patch({ topic: s }); setSuggestions([]) }}
                    style={{
                      textAlign: 'left',
                      padding: '0.375rem 0.5rem',
                      backgroundColor: 'var(--accent-g)',
                      border: '1px solid rgba(107,95,227,0.2)',
                      borderRadius: '4px',
                      color: 'var(--t1)',
                      fontSize: '0.75rem',
                      cursor: 'pointer',
                      lineHeight: 1.4,
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div style={s.divider} />

        {/* Show info */}
        <div style={s.section}>
          <p style={s.sectionTitle}>Show</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={s.fieldGroup}>
              <label style={s.label}>Show name</label>
              <input
                type="text"
                value={cfg.show_name}
                onChange={(e) => patch({ show_name: e.target.value })}
                placeholder="My Podcast"
                style={s.input}
              />
            </div>
            <div style={s.fieldGroup}>
              <label style={s.label}>Channel</label>
              <input
                type="text"
                value={cfg.channel_name}
                onChange={(e) => patch({ channel_name: e.target.value })}
                placeholder="@mychannel"
                style={s.input}
              />
            </div>
            <div style={s.fieldGroup}>
              <label style={s.label}>Language</label>
              <select
                value={cfg.language}
                onChange={(e) => patch({ language: e.target.value })}
                style={s.select}
              >
                {LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>{l.label}</option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div style={s.divider} />

        {/* Structure */}
        <div style={s.section}>
          <p style={s.sectionTitle}>Structure</p>
          <div style={s.row}>
            <div style={s.fieldGroup}>
              <label style={s.label}>Parts</label>
              <input
                type="number"
                min={1} max={20}
                value={cfg.num_parts}
                onChange={(e) => patch({ num_parts: Number(e.target.value) })}
                style={s.input}
              />
            </div>
            <div style={s.fieldGroup}>
              <label style={s.label}>Min / part</label>
              <input
                type="number"
                min={1} max={60}
                value={cfg.minutes_per_part}
                onChange={(e) => patch({
                  minutes_per_part: Number(e.target.value),
                  total_minutes: cfg.num_parts * Number(e.target.value),
                })}
                style={s.input}
              />
            </div>
          </div>
        </div>

        <div style={s.divider} />

        {/* Content */}
        <div style={s.section}>
          <p style={s.sectionTitle}>Content</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={s.fieldGroup}>
              <label style={s.label}>Style</label>
              <select value={cfg.style} onChange={(e) => patch({ style: e.target.value })} style={s.select}>
                {STYLES.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
              </select>
            </div>
            <div style={s.fieldGroup}>
              <label style={s.label}>Audience</label>
              <select value={cfg.audience_level} onChange={(e) => patch({ audience_level: e.target.value })} style={s.select}>
                {AUDIENCE_LEVELS.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
              </select>
            </div>
            <div style={s.fieldGroup}>
              <label style={s.label}>Tone</label>
              <select value={cfg.tone} onChange={(e) => patch({ tone: e.target.value })} style={s.select}>
                {TONES.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
              </select>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <input
                type="checkbox"
                id="continuous"
                checked={cfg.continuous}
                onChange={(e) => patch({ continuous: e.target.checked })}
                style={{ accentColor: 'var(--accent)', width: '14px', height: '14px' }}
              />
              <label htmlFor="continuous" style={{ fontSize: '0.8125rem', color: 'var(--t2)', cursor: 'pointer' }}>
                Continuous narrative
              </label>
            </div>
          </div>
        </div>

        <div style={s.divider} />

        {/* Voices */}
        <div style={s.section}>
          <p style={s.sectionTitle}>Voices</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem' }}>
            {/* Num speakers toggle */}
            <div style={{ display: 'flex', gap: '0.375rem' }}>
              {[1, 2].map((n) => (
                <button
                  key={n}
                  onClick={() => {
                    const names = n === 1 ? ['Host'] : ['Host A', 'Host B']
                    const voiceIds = Array(n).fill('')
                    patch({ num_speakers: n, host_names: names, host_voices: voiceIds })
                  }}
                  style={{
                    flex: 1,
                    padding: '0.375rem',
                    backgroundColor: numSpeakers === n ? 'var(--accent)' : 'var(--bg3)',
                    border: `1px solid ${numSpeakers === n ? 'var(--accent)' : 'var(--bd)'}`,
                    borderRadius: '5px',
                    color: numSpeakers === n ? '#fff' : 'var(--t2)',
                    fontSize: '0.75rem',
                    cursor: 'pointer',
                    fontWeight: numSpeakers === n ? 600 : 400,
                  }}
                >
                  {n === 1 ? 'Solo' : 'Duo'}
                </button>
              ))}
            </div>

            {/* Per-speaker config */}
            {Array.from({ length: numSpeakers }, (_, i) => (
              <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                  <span style={{
                    width: '20px', height: '20px', borderRadius: '50%',
                    backgroundColor: i === 0 ? 'var(--accent)' : 'var(--amber)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '0.625rem', fontWeight: 700, color: '#fff', flexShrink: 0,
                  }}>
                    {i + 1}
                  </span>
                  <input
                    type="text"
                    value={cfg.host_names[i] ?? ''}
                    onChange={(e) => {
                      const names = [...cfg.host_names]
                      names[i] = e.target.value
                      patch({ host_names: names })
                    }}
                    placeholder={`Speaker ${i + 1}`}
                    style={{ ...s.input, flex: 1 }}
                  />
                </div>
                <select
                  value={cfg.host_voices[i] ?? ''}
                  onChange={(e) => {
                    const vids = [...cfg.host_voices]
                    vids[i] = e.target.value
                    patch({ host_voices: vids })
                  }}
                  style={s.select}
                  disabled={voicesLoading}
                >
                  <option value="">{voicesLoading ? 'Loading…' : '— Select voice —'}</option>
                  {voices.map((v) => (
                    <option key={v.voice_id} value={v.voice_id}>{v.name}</option>
                  ))}
                </select>
              </div>
            ))}
          </div>
        </div>

        <div style={s.divider} />

        {/* TTS settings */}
        <div style={s.section}>
          <p style={s.sectionTitle}>TTS Settings</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div style={s.fieldGroup}>
              <label style={s.label}>ElevenLabs Model</label>
              <select
                value={cfg.el_config.model_id}
                onChange={(e) => patchEl({ model_id: e.target.value })}
                style={s.select}
              >
                {EL_MODELS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>

            {([
              ['stability', 'Stability', 0, 1, 0.01],
              ['similarity_boost', 'Similarity', 0, 1, 0.01],
              ['style', 'Style exagg.', 0, 1, 0.01],
              ['speed', 'Speed', 0.7, 1.2, 0.05],
            ] as [keyof StudioConfig['el_config'], string, number, number, number][]).map(([key, label, min, max, step]) => (
              <div key={key} style={s.fieldGroup}>
                <label style={s.label}>{label}</label>
                <div style={s.sliderRow}>
                  <input
                    type="range"
                    min={min} max={max} step={step}
                    value={cfg.el_config[key] as number}
                    onChange={(e) => patchEl({ [key]: Number(e.target.value) } as Partial<StudioConfig['el_config']>)}
                    style={{ flex: 1, accentColor: 'var(--amber)' }}
                  />
                  <span style={s.sliderVal}>
                    {(cfg.el_config[key] as number).toFixed(2)}
                  </span>
                </div>
              </div>
            ))}

            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <input
                type="checkbox"
                id="speakerBoost"
                checked={cfg.el_config.use_speaker_boost}
                onChange={(e) => patchEl({ use_speaker_boost: e.target.checked })}
                style={{ accentColor: 'var(--amber)', width: '14px', height: '14px' }}
              />
              <label htmlFor="speakerBoost" style={{ fontSize: '0.8125rem', color: 'var(--t2)', cursor: 'pointer' }}>
                Speaker boost
              </label>
            </div>
          </div>
        </div>

        <div style={s.divider} />

        {/* Text model */}
        <div style={{ ...s.section, marginBottom: '5rem' }}>
          <p style={s.sectionTitle}>Text Model</p>
          <div style={s.fieldGroup}>
            <select
              value={cfg.text_model}
              onChange={(e) => patch({ text_model: e.target.value })}
              style={s.select}
            >
              {TEXT_MODELS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
        </div>
      </div>

      {/* Sticky Generate button */}
      <div style={{
        padding: '0.75rem 1rem',
        borderTop: '1px solid var(--bd)',
        backgroundColor: 'var(--bg1)',
        flexShrink: 0,
      }}>
        {state.error && (
          <p style={{
            fontSize: '0.75rem', color: '#E5534B',
            backgroundColor: 'rgba(229,83,75,0.1)',
            border: '1px solid rgba(229,83,75,0.25)',
            borderRadius: '4px', padding: '0.375rem 0.5rem',
            marginBottom: '0.5rem',
          }}>
            {state.error}
          </p>
        )}
        <button
          onClick={handleGenerateOutline}
          disabled={state.isGeneratingOutline || !cfg.topic.trim()}
          style={{
            width: '100%',
            padding: '0.625rem',
            backgroundColor: state.isGeneratingOutline || !cfg.topic.trim()
              ? 'var(--bg3)' : 'var(--accent)',
            border: 'none',
            borderRadius: '6px',
            color: state.isGeneratingOutline || !cfg.topic.trim()
              ? 'var(--t3)' : '#fff',
            fontSize: '0.875rem',
            fontWeight: 600,
            cursor: state.isGeneratingOutline || !cfg.topic.trim() ? 'default' : 'pointer',
          }}
        >
          {state.isGeneratingOutline ? 'Generating outline…' : state.outline ? 'Regenerate outline' : 'Generate outline'}
        </button>
      </div>
    </aside>
  )
}
