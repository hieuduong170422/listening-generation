'use client'

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Voice } from '@/lib/types'

// ── Style → keyword mapping for scoring ──────────────────────────────────────

const STYLE_KEYWORDS: Record<string, string[]> = {
  podcast:      ['podcast', 'conversational', 'social media', 'social_media', 'entertainment', 'interview'],
  interview:    ['interview', 'news', 'conversational', 'informational', 'podcast'],
  monologue:    ['narration', 'audiobook', 'storytelling', 'characters', 'meditation', 'ground_truth'],
  documentary:  ['documentary', 'narration', 'news', 'informational', 'audiobook'],
}

const STYLE_LABELS: Record<string, string> = {
  podcast: 'Podcast',
  interview: 'Phỏng vấn',
  monologue: 'Độc thoại',
  documentary: 'Phóng sự',
}

function rateVoice(voice: Voice, style: string): number {
  const labelValues = Object.values(voice.labels ?? {}).map((v) => String(v).toLowerCase())
  const keywords = STYLE_KEYWORDS[style] ?? []
  const hits = keywords.filter((kw) => labelValues.some((lv) => lv.includes(kw)))
  if (hits.length >= 2) return 5
  if (hits.length === 1) return 4
  if (voice.category === 'premade') return 3
  return 2
}

function Stars({ value, max = 5 }: { value: number; max?: number }) {
  return (
    <span style={{ fontSize: '0.625rem', letterSpacing: '-0.5px', lineHeight: 1 }}>
      {Array.from({ length: max }, (_, i) => (
        <span key={i} style={{ color: i < value ? 'var(--amber)' : 'var(--bd)' }}>★</span>
      ))}
    </span>
  )
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  voices: Voice[]
  value: string
  onChange: (voiceId: string) => void
  loading: boolean
  currentStyle: string
  placeholder: string
}

export default function VoicePicker({ voices, value, onChange, loading, currentStyle, placeholder }: Props) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [filterStyle, setFilterStyle] = useState<string>('all')
  const [playingId, setPlayingId] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const triggerRef = useRef<HTMLDivElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ top: 0, left: 0, width: 0 })

  const selected = voices.find((v) => v.voice_id === value)

  // Position dropdown below trigger
  function openDropdown() {
    const rect = triggerRef.current?.getBoundingClientRect()
    if (rect) setPos({ top: rect.bottom + 4, left: rect.left, width: Math.max(rect.width, 260) })
    setOpen(true)
  }

  // Close on outside click
  useEffect(() => {
    if (!open) return
    function handle(e: MouseEvent) {
      const t = e.target as Node
      if (!triggerRef.current?.contains(t) && !dropdownRef.current?.contains(t)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [open])

  // Stop audio on unmount
  useEffect(() => {
    return () => { audioRef.current?.pause() }
  }, [])

  function togglePlay(voice: Voice, e: React.MouseEvent) {
    e.stopPropagation()
    if (!voice.preview_url) return

    if (playingId === voice.voice_id) {
      audioRef.current?.pause()
      setPlayingId(null)
    } else {
      audioRef.current?.pause()
      const audio = new Audio(voice.preview_url)
      audio.onended = () => setPlayingId(null)
      audio.play().catch(() => {})
      audioRef.current = audio
      setPlayingId(voice.voice_id)
    }
  }

  // Filter + sort voices
  const activeStyle = filterStyle === 'all' ? currentStyle : filterStyle
  const filtered = voices
    .filter((v) => v.name.toLowerCase().includes(search.toLowerCase()))
    .filter((v) => filterStyle === 'all' || rateVoice(v, filterStyle) >= 3)
    .map((v) => ({ voice: v, score: rateVoice(v, activeStyle) }))
    .sort((a, b) => b.score - a.score)

  const styles = Object.keys(STYLE_KEYWORDS)

  return (
    <div ref={triggerRef}>
      {/* Trigger row */}
      <div style={{ display: 'flex', gap: '0.375rem' }}>
        <button
          onClick={openDropdown}
          disabled={loading}
          style={{
            flex: 1, padding: '0.4375rem 0.5625rem',
            backgroundColor: 'var(--bg2)', border: `1px solid ${open ? 'var(--accent)' : 'var(--bd)'}`,
            borderRadius: '6px', color: selected ? 'var(--t1)' : 'var(--t3)',
            fontSize: '0.8125rem', cursor: loading ? 'default' : 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            textAlign: 'left', outline: 'none',
          }}
        >
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {loading ? 'Đang tải…' : (selected?.name ?? placeholder)}
          </span>
          {selected && <Stars value={rateVoice(selected, currentStyle)} />}
          <span style={{ color: 'var(--t3)', fontSize: '0.625rem', marginLeft: '0.25rem', flexShrink: 0 }}>▾</span>
        </button>

        {/* Preview button for selected voice */}
        {selected?.preview_url && (
          <button
            onClick={(e) => togglePlay(selected, e)}
            title="Nghe thử giọng đang chọn"
            style={{
              width: '30px', flexShrink: 0,
              backgroundColor: playingId === selected.voice_id ? 'var(--accent)' : 'var(--bg2)',
              border: '1px solid var(--bd)', borderRadius: '6px',
              color: playingId === selected.voice_id ? '#fff' : 'var(--t2)',
              fontSize: '0.75rem', cursor: 'pointer', outline: 'none',
            }}
          >
            {playingId === selected.voice_id ? '⏸' : '▶'}
          </button>
        )}
      </div>

      {/* Dropdown portal */}
      {open && typeof document !== 'undefined' && createPortal(
        <div
          ref={dropdownRef}
          style={{
            position: 'fixed',
            top: pos.top, left: pos.left, width: pos.width,
            backgroundColor: 'var(--bg2)', border: '1px solid var(--bd)',
            borderRadius: '8px', boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
            zIndex: 9999, overflow: 'hidden',
            display: 'flex', flexDirection: 'column',
            maxHeight: '360px',
          }}
        >
          {/* Search */}
          <div style={{ padding: '0.5rem', borderBottom: '1px solid var(--bd-s)' }}>
            <input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Tìm giọng…"
              style={{
                width: '100%', padding: '0.375rem 0.5rem',
                backgroundColor: 'var(--bg1)', border: '1px solid var(--bd)',
                borderRadius: '5px', color: 'var(--t1)', fontSize: '0.8125rem',
                outline: 'none', boxSizing: 'border-box',
              }}
            />
          </div>

          {/* Style filter chips */}
          <div style={{
            padding: '0.375rem 0.5rem', display: 'flex', gap: '0.25rem', flexWrap: 'wrap',
            borderBottom: '1px solid var(--bd-s)',
          }}>
            <Chip label="Tất cả" active={filterStyle === 'all'} onClick={() => setFilterStyle('all')} />
            {styles.map((s) => (
              <Chip key={s} label={STYLE_LABELS[s]} active={filterStyle === s} onClick={() => setFilterStyle(s)} />
            ))}
          </div>

          {/* Sorted by current style label */}
          <div style={{ padding: '0.25rem 0.5rem', borderBottom: '1px solid var(--bd-s)' }}>
            <span style={{ fontSize: '0.6875rem', color: 'var(--t3)' }}>
              Xếp hạng theo: <strong style={{ color: 'var(--t2)' }}>{STYLE_LABELS[activeStyle] ?? activeStyle}</strong>
              {' '}· {filtered.length} giọng
            </span>
          </div>

          {/* Voice list */}
          <div style={{ overflowY: 'auto', flex: 1 }}>
            {filtered.length === 0 && (
              <div style={{ padding: '1rem', textAlign: 'center', fontSize: '0.8125rem', color: 'var(--t3)' }}>
                Không tìm thấy giọng nào
              </div>
            )}
            {filtered.map(({ voice, score }) => {
              const isSelected = voice.voice_id === value
              const isPlaying = playingId === voice.voice_id
              return (
                <div
                  key={voice.voice_id}
                  onClick={() => { onChange(voice.voice_id); setOpen(false); setSearch('') }}
                  style={{
                    padding: '0.4375rem 0.5rem',
                    display: 'flex', alignItems: 'center', gap: '0.375rem',
                    cursor: 'pointer',
                    backgroundColor: isSelected ? 'rgba(var(--accent-rgb,99,102,241),0.1)' : 'transparent',
                    borderLeft: isSelected ? '2px solid var(--accent)' : '2px solid transparent',
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected) e.currentTarget.style.backgroundColor = 'var(--bg3)'
                  }}
                  onMouseLeave={(e) => {
                    if (!isSelected) e.currentTarget.style.backgroundColor = 'transparent'
                  }}
                >
                  {/* Name + category */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      fontSize: '0.8125rem', fontWeight: isSelected ? 600 : 400,
                      color: isSelected ? 'var(--accent)' : 'var(--t1)',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {voice.name}
                    </div>
                    <div style={{ fontSize: '0.625rem', color: 'var(--t3)', marginTop: '0.0625rem' }}>
                      {voice.labels?.gender ?? ''}{voice.labels?.accent ? ` · ${voice.labels.accent}` : ''}
                    </div>
                  </div>

                  {/* Stars for active style */}
                  <Stars value={score} />

                  {/* Preview button */}
                  {voice.preview_url && (
                    <button
                      onClick={(e) => togglePlay(voice, e)}
                      style={{
                        width: '24px', height: '24px', flexShrink: 0,
                        backgroundColor: isPlaying ? 'var(--accent)' : 'var(--bg3)',
                        border: '1px solid var(--bd)',
                        borderRadius: '4px',
                        color: isPlaying ? '#fff' : 'var(--t2)',
                        fontSize: '0.625rem', cursor: 'pointer', outline: 'none',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}
                    >
                      {isPlaying ? '⏸' : '▶'}
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </div>,
        document.body
      )}
    </div>
  )
}

function Chip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '0.1875rem 0.4375rem',
        backgroundColor: active ? 'var(--accent)' : 'var(--bg3)',
        border: `1px solid ${active ? 'var(--accent)' : 'var(--bd)'}`,
        borderRadius: '4px',
        color: active ? '#fff' : 'var(--t2)',
        fontSize: '0.6875rem', fontWeight: active ? 600 : 400,
        cursor: 'pointer', outline: 'none',
      }}
    >
      {label}
    </button>
  )
}
