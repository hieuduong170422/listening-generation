'use client'

import { useEffect, useState } from 'react'
import { fetchHistory, fetchSubscription, getHistoryAudioUrl } from '@/lib/api'
import { useLang } from '@/lib/lang'
import type { HistoryItem, Subscription } from '@/lib/types'

function formatDate(unix: number): string {
  return new Date(unix * 1000).toLocaleDateString('vi-VN', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function formatChars(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

export default function HistoryPanel() {
  const { t } = useLang()
  const [sub, setSub] = useState<Subscription | null>(null)
  const [items, setItems] = useState<HistoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [audioEl, setAudioEl] = useState<HTMLAudioElement | null>(null)

  useEffect(() => {
    setLoading(true)
    Promise.all([fetchSubscription(), fetchHistory(100)])
      .then(([s, h]) => { setSub(s); setItems(h) })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  function togglePlay(item: HistoryItem) {
    if (playingId === item.history_item_id) {
      audioEl?.pause()
      setPlayingId(null)
      setAudioEl(null)
      return
    }
    audioEl?.pause()
    const el = new Audio(getHistoryAudioUrl(item.history_item_id))
    el.onended = () => { setPlayingId(null); setAudioEl(null) }
    el.play().catch(() => {})
    setPlayingId(item.history_item_id)
    setAudioEl(el)
  }

  const usedPct = sub ? Math.min(100, (sub.character_count / sub.character_limit) * 100) : 0

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, color: 'var(--t3)' }}>
        {t.loading}
      </div>
    )
  }

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '1.25rem' }}>
      {/* Subscription quota */}
      {sub && (
        <div style={{
          backgroundColor: 'var(--bg2)', border: '1px solid var(--bd)',
          borderRadius: '8px', padding: '1rem', marginBottom: '1.25rem',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '0.625rem' }}>
            <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--t1)' }}>
              {t.quotaTitle}
            </span>
            <span style={{ fontSize: '0.75rem', color: 'var(--t2)', fontVariantNumeric: 'tabular-nums' }}>
              {formatChars(sub.character_count)} / {formatChars(sub.character_limit)} chars
            </span>
          </div>
          <div style={{
            height: '6px', backgroundColor: 'var(--bg3)',
            borderRadius: '3px', overflow: 'hidden',
          }}>
            <div style={{
              height: '100%', borderRadius: '3px',
              width: `${usedPct}%`,
              backgroundColor: usedPct > 80 ? '#E5534B' : 'var(--amber)',
              transition: 'width 0.3s ease',
            }} />
          </div>
          {sub.tier && (
            <span style={{
              display: 'inline-block', marginTop: '0.5rem',
              fontSize: '0.625rem', fontWeight: 600, textTransform: 'uppercase',
              letterSpacing: '0.05em', color: 'var(--t3)',
              backgroundColor: 'var(--bg3)', border: '1px solid var(--bd)',
              borderRadius: '4px', padding: '0.1rem 0.35rem',
            }}>
              {sub.tier}
            </span>
          )}
        </div>
      )}

      {error && (
        <p style={{
          fontSize: '0.8125rem', color: '#E5534B', marginBottom: '1rem',
          backgroundColor: 'rgba(229,83,75,0.1)', border: '1px solid rgba(229,83,75,0.25)',
          borderRadius: '6px', padding: '0.5rem 0.75rem',
        }}>
          {error}
        </p>
      )}

      {/* History list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {items.length === 0 && !error && (
          <p style={{ color: 'var(--t3)', fontSize: '0.875rem', textAlign: 'center', marginTop: '2rem' }}>
            {t.noHistory}
          </p>
        )}
        {items.map((item) => {
          const isPlaying = playingId === item.history_item_id
          const charDelta = item.character_count_change_to - item.character_count_change_from

          return (
            <div
              key={item.history_item_id}
              style={{
                display: 'flex', alignItems: 'flex-start', gap: '0.75rem',
                padding: '0.75rem 0.875rem',
                backgroundColor: 'var(--bg2)', border: `1px solid ${isPlaying ? 'var(--amber)' : 'var(--bd)'}`,
                borderRadius: '7px',
                transition: 'border-color 0.15s',
              }}
            >
              {/* Play button */}
              <button
                onClick={() => togglePlay(item)}
                style={{
                  flexShrink: 0, width: '32px', height: '32px', borderRadius: '50%',
                  backgroundColor: isPlaying ? 'var(--amber)' : 'var(--amber-m)',
                  border: '1px solid var(--amber)',
                  color: isPlaying ? '#fff' : 'var(--amber)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  cursor: 'pointer', fontSize: '0.75rem',
                }}
                title={isPlaying ? 'Pause' : 'Play'}
              >
                {isPlaying ? '⏸' : '▶'}
              </button>

              {/* Info */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem', marginBottom: '0.25rem' }}>
                  <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--t1)' }}>
                    {item.voice_name}
                  </span>
                  <span style={{ fontSize: '0.6875rem', color: 'var(--t3)', flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
                    {formatChars(charDelta)} chars
                  </span>
                </div>
                <p style={{
                  fontSize: '0.75rem', color: 'var(--t2)', lineHeight: 1.4,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  marginBottom: '0.25rem',
                }}>
                  {item.text}
                </p>
                <span style={{ fontSize: '0.6875rem', color: 'var(--t3)' }}>
                  {formatDate(item.date_unix)}
                </span>
              </div>

              {/* Download */}
              <a
                href={getHistoryAudioUrl(item.history_item_id)}
                download
                style={{
                  flexShrink: 0, width: '28px', height: '28px', borderRadius: '5px',
                  backgroundColor: 'var(--bg3)', border: '1px solid var(--bd)',
                  color: 'var(--t3)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  textDecoration: 'none', fontSize: '0.75rem',
                  transition: 'color 0.15s, border-color 0.15s',
                }}
                title="Download"
              >
                ↓
              </a>
            </div>
          )
        })}
      </div>
    </div>
  )
}
