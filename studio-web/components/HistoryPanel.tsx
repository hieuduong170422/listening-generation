'use client'

import { useEffect, useRef, useState } from 'react'
import { fetchSubscription, fetchAudioBlobUrl, downloadAudioFile, downloadTextFile } from '@/lib/api'
import { useLang } from '@/lib/lang'
import { useStudio } from '@/lib/store'
import {
  fetchOutlineHistory,
  removeOutlineEntry,
  type OutlineHistoryEntry,
} from '@/lib/history'
import type { Subscription } from '@/lib/types'

function formatDate(ms: number): string {
  return new Date(ms).toLocaleDateString('vi-VN', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function formatChars(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

// ── Bảng lịch sử dàn ý: 1 dòng / chủ đề, bấm vào xổ danh sách part ────────────

function OutlineHistoryTable({ onOpen }: { onOpen: () => void }) {
  const { t } = useLang()
  const { dispatch } = useStudio()
  const [entries, setEntries] = useState<OutlineHistoryEntry[]>([])
  const [isAdmin, setIsAdmin] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchOutlineHistory()
      .then(({ entries, isAdmin }) => { setEntries(entries); setIsAdmin(isAdmin) })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  function handleOpen(entry: OutlineHistoryEntry) {
    dispatch({ type: 'LOAD_SNAPSHOT', entry })
    onOpen()
  }

  async function handleDelete(id: string) {
    try {
      await removeOutlineEntry(id)
      setEntries((prev) => prev.filter((e) => e.id !== id))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  const cellStyle: React.CSSProperties = {
    padding: '0.5625rem 0.75rem', fontSize: '0.8125rem',
    borderBottom: '1px solid var(--bd-s)', verticalAlign: 'middle',
  }
  const headStyle: React.CSSProperties = {
    ...cellStyle,
    fontSize: '0.6875rem', fontWeight: 600, color: 'var(--t3)',
    textTransform: 'uppercase', letterSpacing: '0.05em',
    textAlign: 'left', whiteSpace: 'nowrap',
  }
  const nCols = isAdmin ? 5 : 4

  return (
    <div style={{
      backgroundColor: 'var(--bg2)', border: '1px solid var(--bd)',
      borderRadius: '8px', marginBottom: '1.25rem', overflow: 'hidden',
    }}>
      <div style={{ padding: '0.875rem 1rem 0.25rem' }}>
        <div style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--t1)' }}>
          {t.outlineHistoryTitle}
        </div>
        <div style={{ fontSize: '0.6875rem', color: 'var(--t3)', marginTop: '0.2rem' }}>
          {t.outlineHistoryNote}
        </div>
      </div>

      {error && (
        <p style={{ padding: '0.5rem 1rem', fontSize: '0.75rem', color: '#E5534B' }}>{error}</p>
      )}

      {loading ? (
        <p style={{ padding: '0.75rem 1rem 1rem', fontSize: '0.8125rem', color: 'var(--t3)' }}>
          {t.loading}
        </p>
      ) : entries.length === 0 ? (
        <p style={{ padding: '0.75rem 1rem 1rem', fontSize: '0.8125rem', color: 'var(--t3)' }}>
          {t.outlineHistoryEmpty}
        </p>
      ) : (
        <div style={{ overflowX: 'auto', padding: '0.5rem 0.25rem 0.25rem' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={headStyle}>{t.colTopic}</th>
                {isAdmin && <th style={headStyle}>{t.colUser}</th>}
                <th style={headStyle}>{t.colDate}</th>
                <th style={headStyle}>{t.colParts}</th>
                <th style={headStyle} />
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => {
                const total = entry.outline.parts.length
                const nScripts = Object.keys(entry.scripts).length
                const nAudio = Object.keys(entry.audioIds).length
                const isExpanded = expandedId === entry.id
                return (
                  <FragmentRow
                    key={entry.id}
                    entry={entry}
                    isAdmin={isAdmin}
                    isExpanded={isExpanded}
                    nCols={nCols}
                    total={total}
                    nScripts={nScripts}
                    nAudio={nAudio}
                    cellStyle={cellStyle}
                    onToggle={() => setExpandedId(isExpanded ? null : entry.id)}
                    onOpen={() => handleOpen(entry)}
                    onDelete={() => handleDelete(entry.id)}
                  />
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

interface FragmentRowProps {
  entry: OutlineHistoryEntry
  isAdmin: boolean
  isExpanded: boolean
  nCols: number
  total: number
  nScripts: number
  nAudio: number
  cellStyle: React.CSSProperties
  onToggle: () => void
  onOpen: () => void
  onDelete: () => void
}

function FragmentRow({
  entry, isAdmin, isExpanded, nCols, total, nScripts, nAudio,
  cellStyle, onToggle, onOpen, onDelete,
}: FragmentRowProps) {
  const { t } = useLang()
  return (
    <>
      {/* Dòng chủ đề — click để xổ part */}
      <tr
        onClick={onToggle}
        style={{ cursor: 'pointer', backgroundColor: isExpanded ? 'var(--bg3)' : 'transparent' }}
      >
        <td style={{ ...cellStyle, color: 'var(--t1)', fontWeight: 500, maxWidth: '320px' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{
              fontSize: '0.6875rem', color: 'var(--t3)', flexShrink: 0,
              display: 'inline-block',
              transform: isExpanded ? 'rotate(90deg)' : 'none',
              transition: 'transform 0.15s',
            }}>▶</span>
            <span style={{
              display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
              overflow: 'hidden', lineHeight: 1.4,
            }}>
              {entry.outline.topic}
            </span>
          </span>
        </td>
        {isAdmin && (
          <td style={{ ...cellStyle, whiteSpace: 'nowrap' }}>
            <span style={{
              fontSize: '0.6875rem', fontWeight: 600, color: 'var(--accent)',
              backgroundColor: 'rgba(107,95,227,0.1)',
              border: '1px solid rgba(107,95,227,0.25)',
              borderRadius: '4px', padding: '0.125rem 0.4rem',
            }}>
              {entry.username}
            </span>
          </td>
        )}
        <td style={{ ...cellStyle, color: 'var(--t2)', whiteSpace: 'nowrap' }}>
          {formatDate(entry.updatedAt * 1000)}
        </td>
        <td style={{ ...cellStyle, whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
          <span style={{ color: 'var(--t2)' }}>{total}</span>
          <span style={{ color: 'var(--ok)' }}> / {nScripts}</span>
          <span style={{ color: 'var(--amber)' }}> / {nAudio}</span>
        </td>
        <td
          style={{ ...cellStyle, whiteSpace: 'nowrap', textAlign: 'right' }}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={onOpen}
            style={{
              padding: '0.25rem 0.625rem', marginRight: '0.375rem',
              backgroundColor: 'var(--accent)', border: 'none',
              borderRadius: '5px', color: '#fff',
              fontSize: '0.75rem', fontWeight: 600, cursor: 'pointer',
            }}
          >
            {t.openBtn}
          </button>
          <button
            onClick={onDelete}
            style={{
              padding: '0.25rem 0.625rem',
              backgroundColor: 'transparent',
              border: '1px solid rgba(229,83,75,0.4)',
              borderRadius: '5px', color: '#E5534B',
              fontSize: '0.75rem', fontWeight: 600, cursor: 'pointer',
            }}
          >
            {t.deleteBtn}
          </button>
        </td>
      </tr>

      {/* Danh sách part của chủ đề */}
      {isExpanded && (
        <tr>
          <td colSpan={nCols} style={{ padding: 0, borderBottom: '1px solid var(--bd-s)' }}>
            <div style={{
              padding: '0.5rem 1rem 0.75rem 2rem',
              backgroundColor: 'var(--bg1)',
              display: 'flex', flexDirection: 'column', gap: '0.375rem',
            }}>
              {entry.outline.parts.map((part) => (
                <HistoryPartRow
                  key={part.index}
                  index={part.index}
                  title={part.title}
                  script={entry.scripts[part.index] ?? ''}
                  audioId={entry.audioIds[part.index] ?? ''}
                  srt={entry.subtitles[part.index] ?? ''}
                />
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// ── 1 part trong lịch sử: xem script, nghe lại + tải audio ────────────────────

function HistoryPartRow({
  index, title, script, audioId, srt,
}: { index: number; title: string; script: string; audioId: string; srt: string }) {
  const { t } = useLang()
  const [open, setOpen] = useState(false)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioState, setAudioState] = useState<'idle' | 'loading' | 'missing'>('idle')
  const [downloading, setDownloading] = useState(false)
  const urlRef = useRef<string | null>(null)

  const hasScript = Boolean(script)
  const hasAudio = Boolean(audioId)
  const hasSubtitle = Boolean(srt)
  const openable = hasScript || hasAudio || hasSubtitle

  // Tải audio khi mở panel; thu hồi blob URL khi đóng/unmount
  useEffect(() => {
    if (!open || !audioId) return
    setAudioState('loading')
    fetchAudioBlobUrl(audioId)
      .then((url) => {
        if (urlRef.current) URL.revokeObjectURL(urlRef.current)
        urlRef.current = url
        setAudioUrl(url)
        setAudioState('idle')
      })
      .catch(() => setAudioState('missing'))
  }, [open, audioId])

  useEffect(() => {
    return () => { if (urlRef.current) URL.revokeObjectURL(urlRef.current) }
  }, [])

  async function handleDownload() {
    if (!audioId || downloading) return
    setDownloading(true)
    try {
      await downloadAudioFile(audioId, `part-${String(index).padStart(2, '0')}`)
    } catch {
      setAudioState('missing')
    } finally {
      setDownloading(false)
    }
  }

  const badge = (label: string, color: string, bg: string, bd: string) => (
    <span style={{
      fontSize: '0.5625rem', fontWeight: 700,
      padding: '0.125rem 0.375rem', borderRadius: '3px',
      backgroundColor: bg, border: `1px solid ${bd}`,
      color, textTransform: 'uppercase',
    }}>{label}</span>
  )

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
        <span style={{
          width: '22px', height: '22px', borderRadius: '50%', flexShrink: 0,
          backgroundColor: open ? 'var(--accent)' : 'var(--bg3)',
          border: '1px solid var(--bd)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '0.625rem', fontWeight: 700, color: open ? '#fff' : 'var(--t2)',
        }}>
          {index}
        </span>
        <span style={{
          flex: 1, minWidth: 0, fontSize: '0.8125rem', color: 'var(--t1)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {title}
        </span>
        <span style={{ display: 'flex', gap: '0.375rem', flexShrink: 0, alignItems: 'center' }}>
          {hasScript && badge(t.scriptsBadge, 'var(--accent)', 'rgba(107,95,227,0.1)', 'rgba(107,95,227,0.2)')}
          {hasAudio && badge(t.audioBadge, 'var(--amber)', 'rgba(201,122,72,0.1)', 'rgba(201,122,72,0.2)')}
          {hasSubtitle && badge(t.subtitleBadge, 'var(--ok)', 'rgba(90,170,120,0.12)', 'rgba(90,170,120,0.25)')}
          {hasAudio && (
            <button
              onClick={handleDownload}
              disabled={downloading}
              title={t.downloadOne}
              style={{
                padding: '0.125rem 0.4375rem',
                backgroundColor: 'var(--bg3)', border: '1px solid var(--bd)',
                borderRadius: '4px', color: downloading ? 'var(--t3)' : 'var(--t2)',
                fontSize: '0.6875rem', cursor: downloading ? 'default' : 'pointer',
              }}
            >
              ⬇
            </button>
          )}
          {hasSubtitle && (
            <button
              onClick={() => downloadTextFile(srt, `part-${String(index).padStart(2, '0')}.srt`)}
              title={t.downloadSrt}
              style={{
                padding: '0.125rem 0.4375rem',
                backgroundColor: 'var(--bg3)', border: '1px solid var(--bd)',
                borderRadius: '4px', color: 'var(--t2)',
                fontSize: '0.6875rem', cursor: 'pointer',
              }}
            >
              .srt
            </button>
          )}
          {openable && (
            <button
              onClick={() => setOpen((o) => !o)}
              style={{
                padding: '0.125rem 0.4375rem',
                backgroundColor: open ? 'var(--bg3)' : 'transparent',
                border: '1px solid var(--bd)',
                borderRadius: '4px', color: 'var(--t2)',
                fontSize: '0.6875rem', cursor: 'pointer',
              }}
            >
              {open ? t.histHide : t.histView}
            </button>
          )}
        </span>
      </div>

      {open && (
        <div style={{
          margin: '0.375rem 0 0.25rem 2rem',
          border: '1px solid var(--bd-s)', borderRadius: '6px',
          backgroundColor: 'var(--bg2)', padding: '0.625rem 0.75rem',
          display: 'flex', flexDirection: 'column', gap: '0.5rem',
        }}>
          {hasScript && (
            <pre style={{
              margin: 0, fontFamily: 'inherit', fontSize: '0.75rem',
              color: 'var(--t2)', lineHeight: 1.6,
              whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
              maxHeight: '220px', overflowY: 'auto',
            }}>
              {script}
            </pre>
          )}
          {hasAudio && audioState === 'loading' && (
            <div style={{ fontSize: '0.75rem', color: 'var(--t3)' }}>{t.loadingAudio}</div>
          )}
          {hasAudio && audioState === 'missing' && (
            <div style={{ fontSize: '0.75rem', color: 'var(--amber)' }}>{t.audioGone}</div>
          )}
          {audioUrl && audioState === 'idle' && (
            <audio controls src={audioUrl} style={{ width: '100%', height: '34px', accentColor: 'var(--amber)' }} />
          )}
          {hasSubtitle && (
            <pre style={{
              margin: 0, fontFamily: 'ui-monospace, monospace', fontSize: '0.7rem',
              color: 'var(--t3)', lineHeight: 1.5,
              whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
              maxHeight: '160px', overflowY: 'auto',
              borderTop: '1px solid var(--bd-s)', paddingTop: '0.5rem',
            }}>
              {srt}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

// ── Panel chính: quota ElevenLabs + bảng lịch sử theo chủ đề ──────────────────

export default function HistoryPanel({ onOpenOutline }: { onOpenOutline?: () => void }) {
  const { t } = useLang()
  const [sub, setSub] = useState<Subscription | null>(null)

  useEffect(() => {
    fetchSubscription().then(setSub).catch(() => setSub(null))
  }, [])

  const usedPct = sub ? Math.min(100, (sub.character_count / sub.character_limit) * 100) : 0

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

      {/* Lịch sử dàn ý theo chủ đề */}
      <OutlineHistoryTable onOpen={onOpenOutline ?? (() => {})} />
    </div>
  )
}
