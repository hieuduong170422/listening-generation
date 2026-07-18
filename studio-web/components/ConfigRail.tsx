'use client'

import { useEffect, useState } from 'react'
import { useStudio } from '@/lib/store'
import { useLang } from '@/lib/lang'
import { fetchVoices, generateOutline, suggestTopics, ApiError } from '@/lib/api'
import type { Voice, StudioConfig } from '@/lib/types'
import VoicePicker from './VoicePicker'

const LANGUAGES = [
  { value: 'vi', label: 'Tiếng Việt' },
  { value: 'en', label: 'English' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
  { value: 'zh', label: '中文' },
]

const STYLES_VI = ['podcast', 'interview', 'monologue', 'documentary']
const STYLES_EN = ['Podcast', 'Interview', 'Monologue', 'Documentary']
const STYLES_LABEL_VI = ['Podcast', 'Phỏng vấn', 'Độc thoại', 'Phóng sự']

const AUDIENCE_VI = ['beginner', 'intermediate', 'advanced', 'expert']
const AUDIENCE_LABEL_VI = ['Người mới', 'Trung cấp', 'Nâng cao', 'Chuyên gia']
const AUDIENCE_LABEL_EN = ['Beginner', 'Intermediate', 'Advanced', 'Expert']

const TONES_VI = ['conversational', 'formal', 'casual', 'educational', 'entertaining']
const TONES_LABEL_VI = ['Trò chuyện', 'Trang trọng', 'Thân thiện', 'Giáo dục', 'Giải trí']
const TONES_LABEL_EN = ['Conversational', 'Formal', 'Casual', 'Educational', 'Entertaining']

const s = {
  label: {
    display: 'block',
    fontSize: '0.6875rem',
    fontWeight: 600,
    color: 'var(--t3)',
    marginBottom: '0.25rem',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  },
  input: {
    width: '100%',
    padding: '0.4375rem 0.5625rem',
    backgroundColor: 'var(--bg2)',
    border: '1px solid var(--bd)',
    borderRadius: '6px',
    color: 'var(--t1)',
    fontSize: '0.8125rem',
    outline: 'none',
    boxSizing: 'border-box' as const,
  },
  select: {
    width: '100%',
    padding: '0.4375rem 0.5625rem',
    backgroundColor: 'var(--bg2)',
    border: '1px solid var(--bd)',
    borderRadius: '6px',
    color: 'var(--t1)',
    fontSize: '0.8125rem',
    outline: 'none',
    cursor: 'pointer',
    boxSizing: 'border-box' as const,
  },
  field: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.25rem',
  },
  gap: { display: 'flex', flexDirection: 'column' as const, gap: '0.625rem' },
}

export default function ConfigRail() {
  const { state, dispatch } = useStudio()
  const { t, lang } = useLang()
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

  async function handleSuggest() {
    setSuggesting(true)
    setSuggestions([])
    try {
      const res = await suggestTopics({
        topic: cfg.topic,
        language: cfg.language,
        count: 5,
        text_model: cfg.text_model,
        audience_level: cfg.audience_level,
        tone: cfg.tone,
      })
      setSuggestions(res.suggestions)
    } catch (err) {
      dispatch({ type: 'SET_ERROR', message: err instanceof ApiError ? err.message : 'Error' })
    } finally {
      setSuggesting(false)
    }
  }

  async function handleGenerateOutline() {
    if (!cfg.topic.trim()) {
      dispatch({ type: 'SET_ERROR', message: lang === 'vi' ? 'Vui lòng nhập chủ đề trước' : 'Please enter a topic first' })
      return
    }
    dispatch({ type: 'SET_GENERATING_OUTLINE', value: true })
    dispatch({ type: 'SET_ERROR', message: null })
    try {
      const res = await generateOutline(cfg)
      dispatch({ type: 'SET_OUTLINE', outline: res.outline })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', message: err instanceof ApiError ? err.message : 'Outline generation failed' })
    } finally {
      dispatch({ type: 'SET_GENERATING_OUTLINE', value: false })
    }
  }

  const numSpeakers = cfg.num_speakers
  const styleLabels = lang === 'vi' ? STYLES_LABEL_VI : STYLES_EN
  const audienceLabels = lang === 'vi' ? AUDIENCE_LABEL_VI : AUDIENCE_LABEL_EN
  const toneLabels = lang === 'vi' ? TONES_LABEL_VI : TONES_LABEL_EN

  return (
    <aside style={{
      width: '248px',
      flexShrink: 0,
      backgroundColor: 'var(--bg1)',
      borderRight: '1px solid var(--bd)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>
      <div style={{ flex: 1, overflowY: 'auto', padding: '0.75rem 0.75rem 0.5rem' }}>
        <div style={s.gap}>

          {/* Topic */}
          <div style={s.field}>
            <label style={s.label}>{t.topic}</label>
            <textarea
              value={cfg.topic}
              onChange={(e) => patch({ topic: e.target.value })}
              rows={3}
              placeholder={t.topicPlaceholder}
              style={{
                ...s.input, resize: 'vertical',
                lineHeight: 1.5, fontFamily: 'inherit',
              }}
            />
            <button
              onClick={handleSuggest}
              disabled={suggesting}
              style={{
                padding: '0.3125rem 0.5rem',
                backgroundColor: 'var(--bg3)', border: '1px solid var(--bd)',
                borderRadius: '5px', color: suggesting ? 'var(--t3)' : 'var(--t2)',
                fontSize: '0.75rem', cursor: suggesting ? 'default' : 'pointer',
                textAlign: 'left' as const,
              }}
            >
              {suggesting ? t.suggesting : t.suggestTopics}
            </button>
            {suggestions.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                {suggestions.map((sug) => (
                  <button
                    key={sug}
                    onClick={() => { patch({ topic: sug }); setSuggestions([]) }}
                    style={{
                      textAlign: 'left', padding: '0.3125rem 0.5rem',
                      backgroundColor: 'var(--accent-g)',
                      border: '1px solid rgba(107,95,227,0.2)',
                      borderRadius: '4px', color: 'var(--t1)',
                      fontSize: '0.75rem', cursor: 'pointer', lineHeight: 1.4,
                    }}
                  >
                    {sug}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Language */}
          <div style={s.field}>
            <label style={s.label}>{t.language}</label>
            <select value={cfg.language} onChange={(e) => patch({ language: e.target.value })} style={s.select}>
              {LANGUAGES.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
            </select>
          </div>

          {/* Style + Audience */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
            <div style={s.field}>
              <label style={s.label}>{t.style}</label>
              <select value={cfg.style} onChange={(e) => patch({ style: e.target.value })} style={s.select}>
                {STYLES_VI.map((v, i) => <option key={v} value={v}>{styleLabels[i]}</option>)}
              </select>
            </div>
            <div style={s.field}>
              <label style={s.label}>{t.audience}</label>
              <select value={cfg.audience_level} onChange={(e) => patch({ audience_level: e.target.value })} style={s.select}>
                {AUDIENCE_VI.map((v, i) => <option key={v} value={v}>{audienceLabels[i]}</option>)}
              </select>
            </div>
          </div>

          {/* Tone */}
          <div style={s.field}>
            <label style={s.label}>{t.tone}</label>
            <select value={cfg.tone} onChange={(e) => patch({ tone: e.target.value })} style={s.select}>
              {TONES_VI.map((v, i) => <option key={v} value={v}>{toneLabels[i]}</option>)}
            </select>
          </div>

          {/* Parts + Min/part */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
            <div style={s.field}>
              <label style={s.label}>{t.parts}</label>
              <input
                type="number" min={1} max={20}
                value={cfg.num_parts}
                onChange={(e) => patch({ num_parts: Number(e.target.value) })}
                style={s.input}
              />
            </div>
            <div style={s.field}>
              <label style={s.label}>{t.minPerPart}</label>
              <input
                type="number" min={1} max={60}
                value={cfg.minutes_per_part}
                onChange={(e) => patch({
                  minutes_per_part: Number(e.target.value),
                  total_minutes: cfg.num_parts * Number(e.target.value),
                })}
                style={s.input}
              />
            </div>
          </div>

          {/* Speakers */}
          <div style={s.field}>
            <label style={s.label}>{t.speakers}</label>
            <div style={{ display: 'flex', gap: '0.375rem', marginBottom: '0.375rem' }}>
              {[1, 2].map((n) => (
                <button
                  key={n}
                  onClick={() => {
                    const names = n === 1
                      ? (lang === 'vi' ? ['Người dẫn'] : ['Host'])
                      : (lang === 'vi' ? ['Người dẫn A', 'Người dẫn B'] : ['Host A', 'Host B'])
                    patch({ num_speakers: n, host_names: names, host_voices: Array(n).fill('') })
                  }}
                  style={{
                    flex: 1, padding: '0.375rem',
                    backgroundColor: numSpeakers === n ? 'var(--accent)' : 'var(--bg3)',
                    border: `1px solid ${numSpeakers === n ? 'var(--accent)' : 'var(--bd)'}`,
                    borderRadius: '5px',
                    color: numSpeakers === n ? '#fff' : 'var(--t2)',
                    fontSize: '0.8125rem', cursor: 'pointer',
                    fontWeight: numSpeakers === n ? 600 : 400,
                  }}
                >
                  {n === 1 ? t.solo : t.duo}
                </button>
              ))}
            </div>

            {Array.from({ length: numSpeakers }, (_, i) => (
              <div key={i} style={{
                backgroundColor: 'var(--bg2)', border: '1px solid var(--bd)',
                borderRadius: '6px', padding: '0.5rem', marginBottom: '0.375rem',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', marginBottom: '0.375rem' }}>
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
                    placeholder={t.speakerNamePlaceholder}
                    style={{ ...s.input, flex: 1 }}
                  />
                </div>
                <VoicePicker
                  voices={voices}
                  value={cfg.host_voices[i] ?? ''}
                  onChange={(vid) => {
                    const vids = [...cfg.host_voices]
                    vids[i] = vid
                    patch({ host_voices: vids })
                  }}
                  loading={voicesLoading}
                  currentStyle={cfg.style}
                  placeholder={voicesLoading ? t.loadingVoices : t.selectVoice}
                />
              </div>
            ))}
          </div>

        </div>
      </div>

      {/* Sticky generate button */}
      <div style={{
        padding: '0.625rem 0.75rem',
        borderTop: '1px solid var(--bd)',
        backgroundColor: 'var(--bg1)',
        flexShrink: 0,
      }}>
        {state.error && (
          <p style={{
            fontSize: '0.75rem', color: '#E5534B',
            backgroundColor: 'rgba(229,83,75,0.08)',
            border: '1px solid rgba(229,83,75,0.2)',
            borderRadius: '4px', padding: '0.3rem 0.45rem',
            marginBottom: '0.4rem', lineHeight: 1.4,
          }}>
            {state.error}
          </p>
        )}
        <button
          onClick={handleGenerateOutline}
          disabled={state.isGeneratingOutline || !cfg.topic.trim()}
          style={{
            width: '100%', padding: '0.5625rem',
            backgroundColor: state.isGeneratingOutline || !cfg.topic.trim()
              ? 'var(--bg3)' : 'var(--accent)',
            border: 'none', borderRadius: '6px',
            color: state.isGeneratingOutline || !cfg.topic.trim() ? 'var(--t3)' : '#fff',
            fontSize: '0.875rem', fontWeight: 600,
            cursor: state.isGeneratingOutline || !cfg.topic.trim() ? 'default' : 'pointer',
          }}
        >
          {state.isGeneratingOutline
            ? t.generatingOutline
            : state.outline ? t.regenerateOutline : t.generateOutline}
        </button>
      </div>
    </aside>
  )
}
