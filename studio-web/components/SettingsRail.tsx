'use client'

import { useStudio } from '@/lib/store'
import { useLang } from '@/lib/lang'
import type { StudioConfig } from '@/lib/types'

const EL_MODELS = [
  { value: 'eleven_flash_v2_5', label: 'Flash v2.5' },
  { value: 'eleven_multilingual_v2', label: 'Multilingual v2' },
  { value: 'eleven_turbo_v2_5', label: 'Turbo v2.5' },
  { value: 'eleven_v3', label: 'Eleven v3 (cảm xúc)' },
]

const TEXT_MODELS = [
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
  { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
  { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
]

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
  field: { display: 'flex', flexDirection: 'column' as const, gap: '0.25rem' },
  gap: { display: 'flex', flexDirection: 'column' as const, gap: '0.625rem' },
  divider: { height: '1px', backgroundColor: 'var(--bd-s)', margin: '0.375rem 0' },
  section: {
    fontSize: '0.625rem',
    fontWeight: 700,
    color: 'var(--t3)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.07em',
    marginBottom: '0.5rem',
  },
}

export default function SettingsRail() {
  const { state, dispatch } = useStudio()
  const { t } = useLang()
  const cfg = state.config

  function patch(p: Partial<StudioConfig>) {
    dispatch({ type: 'PATCH_CONFIG', patch: p })
  }

  function patchEl(p: Partial<StudioConfig['el_config']>) {
    dispatch({ type: 'PATCH_CONFIG', patch: { el_config: { ...cfg.el_config, ...p } } })
  }

  const sliders: [keyof StudioConfig['el_config'], string, number, number, number][] = [
    ['stability', t.stability, 0, 1, 0.01],
    ['similarity_boost', t.similarity, 0, 1, 0.01],
    ['style', t.styleExagg, 0, 1, 0.01],
    ['speed', t.speed, 0.7, 1.2, 0.05],
  ]

  return (
    <aside style={{
      width: '220px',
      flexShrink: 0,
      backgroundColor: 'var(--bg1)',
      borderLeft: '1px solid var(--bd)',
      overflowY: 'auto',
      height: 'calc(100vh - 50px)',
      padding: '0.75rem',
    }}>
      <div style={s.gap}>

        {/* Channel */}
        <div>
          <p style={s.section}>{t.channel}</p>
          <div style={s.field}>
            <input
              type="text"
              value={cfg.channel_name}
              onChange={(e) => patch({ channel_name: e.target.value })}
              placeholder={t.channelPlaceholder}
              style={s.input}
            />
          </div>
        </div>

        {/* Continuous */}
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={cfg.continuous}
            onChange={(e) => patch({ continuous: e.target.checked })}
            style={{ accentColor: 'var(--accent)', width: '13px', height: '13px', flexShrink: 0 }}
          />
          <span style={{ fontSize: '0.75rem', color: 'var(--t2)', lineHeight: 1.3 }}>
            {t.continuousNarrative}
          </span>
        </label>

        <div style={s.divider} />

        {/* Models */}
        <div>
          <p style={s.section}>{t.textModel}</p>
          <select value={cfg.text_model} onChange={(e) => patch({ text_model: e.target.value })} style={s.select}>
            {TEXT_MODELS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </div>

        <div style={s.field}>
          <label style={s.label}>{t.elevenlabsModel}</label>
          <select
            value={cfg.el_config.model_id}
            onChange={(e) => patchEl({ model_id: e.target.value })}
            style={s.select}
          >
            {EL_MODELS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </div>

        <div style={s.divider} />

        {/* TTS sliders */}
        <div>
          <p style={s.section}>{t.ttsVoice}</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {sliders.map(([key, label, min, max, step]) => (
              <div key={key}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.125rem' }}>
                  <span style={{ fontSize: '0.6875rem', color: 'var(--t2)' }}>{label}</span>
                  <span style={{
                    fontSize: '0.6875rem', color: 'var(--t3)',
                    fontVariantNumeric: 'tabular-nums',
                  }}>
                    {(cfg.el_config[key] as number).toFixed(2)}
                  </span>
                </div>
                <input
                  type="range" min={min} max={max} step={step}
                  value={cfg.el_config[key] as number}
                  onChange={(e) => patchEl({ [key]: Number(e.target.value) } as Partial<StudioConfig['el_config']>)}
                  style={{ width: '100%', accentColor: 'var(--amber)' }}
                />
              </div>
            ))}
          </div>
        </div>

        {/* Speaker boost */}
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={cfg.el_config.use_speaker_boost}
            onChange={(e) => patchEl({ use_speaker_boost: e.target.checked })}
            style={{ accentColor: 'var(--amber)', width: '13px', height: '13px', flexShrink: 0 }}
          />
          <span style={{ fontSize: '0.75rem', color: 'var(--t2)' }}>{t.speakerBoost}</span>
        </label>

      </div>
    </aside>
  )
}
