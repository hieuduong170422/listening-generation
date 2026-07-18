'use client'

import { useEffect, useRef, useState } from 'react'
import { useStudio } from '@/lib/store'
import { useLang } from '@/lib/lang'
import { generateScript, renderAudio, fetchAudioBlobUrl, ApiError } from '@/lib/api'
import type { PartBrief } from '@/lib/types'

function PartItem({ part }: { part: PartBrief }) {
  const { state, dispatch } = useStudio()
  const { t } = useLang()
  const { config, scripts, audioIds, generatingScript, renderingAudio } = state

  const isExpanded = state.selectedPart === part.index
  const scriptText = scripts[part.index] ?? ''
  const hasScript = Boolean(scriptText)
  const hasAudio = Boolean(audioIds[part.index])
  const isGenerating = generatingScript === part.index
  const isRendering = renderingAudio === part.index

  const [localScript, setLocalScript] = useState(scriptText)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioLoading, setAudioLoading] = useState(false)
  const prevAudioRef = useRef<string | null>(null)

  useEffect(() => { setLocalScript(scriptText) }, [scriptText])

  useEffect(() => {
    const aid = audioIds[part.index]
    if (!aid || !isExpanded) { setAudioUrl(null); return }
    setAudioLoading(true)
    fetchAudioBlobUrl(aid)
      .then((url) => {
        if (prevAudioRef.current) URL.revokeObjectURL(prevAudioRef.current)
        prevAudioRef.current = url
        setAudioUrl(url)
      })
      .catch(() => setAudioUrl(null))
      .finally(() => setAudioLoading(false))
  }, [part.index, audioIds, isExpanded])

  useEffect(() => {
    return () => { if (prevAudioRef.current) URL.revokeObjectURL(prevAudioRef.current) }
  }, [])

  function toggle() {
    dispatch({ type: 'SELECT_PART', partIndex: isExpanded ? null : part.index })
  }

  async function handleGenerateScript() {
    const previousScripts = Object.fromEntries(
      Object.entries(scripts).map(([k, v]) => [String(k), v])
    )
    dispatch({ type: 'SET_GENERATING_SCRIPT', partIndex: part.index })
    dispatch({ type: 'SET_ERROR', message: null })
    try {
      const res = await generateScript({
        config,
        outline: state.outline!,
        partIndex: part.index,
        previousScripts,
      })
      dispatch({ type: 'SET_SCRIPT', partIndex: part.index, text: res.text })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', message: err instanceof ApiError ? err.message : 'Script generation failed' })
    } finally {
      dispatch({ type: 'SET_GENERATING_SCRIPT', partIndex: null })
    }
  }

  async function handleRenderAudio() {
    const script = localScript || scriptText
    if (!script.trim()) {
      dispatch({ type: 'SET_ERROR', message: 'Generate or write a script first' })
      return
    }
    dispatch({ type: 'SET_RENDERING_AUDIO', partIndex: part.index })
    dispatch({ type: 'SET_ERROR', message: null })
    try {
      const res = await renderAudio({ config, partIndex: part.index, script })
      dispatch({ type: 'SET_AUDIO_ID', partIndex: part.index, audioId: res.audio_id })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', message: err instanceof ApiError ? err.message : 'Audio render failed' })
    } finally {
      dispatch({ type: 'SET_RENDERING_AUDIO', partIndex: null })
    }
  }

  function handleScriptChange(text: string) {
    setLocalScript(text)
    dispatch({ type: 'SET_SCRIPT', partIndex: part.index, text })
  }

  const busy = isGenerating || isRendering
  let statusColor = 'var(--t3)'
  if (hasAudio || isRendering) statusColor = 'var(--amber)'
  else if (hasScript || isGenerating) statusColor = 'var(--ok)'

  return (
    <div style={{
      backgroundColor: 'var(--bg2)',
      border: `1px solid ${isExpanded ? 'var(--accent)' : 'var(--bd)'}`,
      borderRadius: '8px', overflow: 'hidden',
      transition: 'border-color 0.15s',
    }}>
      {/* Header row */}
      <button
        onClick={toggle}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: '0.75rem',
          padding: '0.8125rem 1rem', backgroundColor: 'transparent',
          border: 'none', cursor: 'pointer', textAlign: 'left',
        }}
      >
        <span style={{
          width: '26px', height: '26px', borderRadius: '50%', flexShrink: 0,
          backgroundColor: isExpanded ? 'var(--accent)' : 'var(--bg3)',
          border: `1px solid ${isExpanded ? 'var(--accent)' : 'var(--bd)'}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '0.75rem', fontWeight: 700,
          color: isExpanded ? '#fff' : 'var(--t2)',
          transition: 'background-color 0.15s, color 0.15s',
        }}>
          {part.index}
        </span>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--t1)', lineHeight: 1.3 }}>
            {part.title}
          </div>
          {!isExpanded && (
            <div style={{
              fontSize: '0.75rem', color: 'var(--t2)', marginTop: '0.1rem',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {part.summary}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', flexShrink: 0 }}>
          <span style={{
            width: '6px', height: '6px', borderRadius: '50%',
            backgroundColor: statusColor,
            animation: busy ? 'pulse 1.5s ease-in-out infinite' : 'none',
            flexShrink: 0,
          }} />
          {hasScript && !isExpanded && (
            <span style={{
              fontSize: '0.5625rem', fontWeight: 700,
              padding: '0.125rem 0.375rem', borderRadius: '3px',
              backgroundColor: 'rgba(107,95,227,0.1)',
              border: '1px solid rgba(107,95,227,0.2)',
              color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.04em',
            }}>{t.scriptsBadge}</span>
          )}
          {hasAudio && !isExpanded && (
            <span style={{
              fontSize: '0.5625rem', fontWeight: 700,
              padding: '0.125rem 0.375rem', borderRadius: '3px',
              backgroundColor: 'rgba(201,122,72,0.1)',
              border: '1px solid rgba(201,122,72,0.2)',
              color: 'var(--amber)', textTransform: 'uppercase', letterSpacing: '0.04em',
            }}>{t.audioBadge}</span>
          )}
          <span style={{
            fontSize: '0.8125rem', color: 'var(--t3)',
            display: 'inline-block',
            transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s ease',
            marginLeft: '0.125rem',
          }}>▾</span>
        </div>
      </button>

      {/* Expanded */}
      {isExpanded && (
        <div style={{ borderTop: '1px solid var(--bd-s)' }}>
          {/* Summary + key points */}
          <div style={{
            padding: '0.625rem 1rem', backgroundColor: 'var(--bg1)',
            borderBottom: '1px solid var(--bd-s)',
          }}>
            <p style={{ fontSize: '0.8125rem', color: 'var(--t2)', lineHeight: 1.6, marginBottom: '0.4rem' }}>
              {part.summary}
            </p>
            {part.key_points.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }}>
                {part.key_points.map((kp, i) => (
                  <span key={i} style={{
                    fontSize: '0.6875rem', color: 'var(--t3)',
                    backgroundColor: 'var(--bg2)', border: '1px solid var(--bd-s)',
                    borderRadius: '3px', padding: '0.125rem 0.375rem',
                  }}>{kp}</span>
                ))}
              </div>
            )}
          </div>

          {/* Script editor */}
          <div style={{ padding: '0.75rem 1rem 0.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
              <span style={{
                fontSize: '0.6875rem', fontWeight: 600, color: 'var(--t3)',
                textTransform: 'uppercase', letterSpacing: '0.06em',
              }}>{t.scriptLabel}</span>
              {localScript.length > 0 && (
                <span style={{ fontSize: '0.6875rem', color: 'var(--t3)', fontVariantNumeric: 'tabular-nums' }}>
                  {localScript.length.toLocaleString()} {t.chars}
                </span>
              )}
            </div>
            <textarea
              value={localScript}
              onChange={(e) => handleScriptChange(e.target.value)}
              placeholder={isGenerating ? t.writingPlaceholder : t.scriptPlaceholder}
              disabled={isGenerating}
              rows={8}
              style={{
                width: '100%', backgroundColor: 'var(--bg1)',
                border: '1px solid var(--bd)', borderRadius: '6px',
                color: isGenerating ? 'var(--t3)' : 'var(--t1)',
                fontSize: '0.8125rem', lineHeight: 1.7, padding: '0.625rem 0.75rem',
                resize: 'vertical', outline: 'none', fontFamily: 'inherit',
                boxSizing: 'border-box',
              }}
            />
          </div>

          {/* Audio player */}
          {(audioUrl || audioLoading) && (
            <div style={{ padding: '0 1rem 0.625rem' }}>
              {audioLoading
                ? <div style={{ fontSize: '0.75rem', color: 'var(--t3)', padding: '0.25rem 0' }}>{t.loadingAudio}</div>
                : audioUrl
                  ? <audio controls src={audioUrl} style={{ width: '100%', accentColor: 'var(--amber)', height: '34px' }} />
                  : null}
            </div>
          )}

          {/* Buttons */}
          <div style={{
            display: 'flex', gap: '0.5rem', padding: '0.625rem 1rem',
            borderTop: '1px solid var(--bd-s)', backgroundColor: 'var(--bg1)',
          }}>
            <button
              onClick={handleGenerateScript}
              disabled={busy}
              style={{
                flex: 1, padding: '0.5rem',
                backgroundColor: busy ? 'var(--bg3)' : 'var(--accent)',
                border: 'none', borderRadius: '6px',
                color: busy ? 'var(--t3)' : '#fff',
                fontSize: '0.8125rem', fontWeight: 600,
                cursor: busy ? 'default' : 'pointer',
              }}
            >
              {isGenerating ? t.writing : hasScript ? t.regenScript : t.genScript}
            </button>
            <button
              onClick={handleRenderAudio}
              disabled={busy || !localScript.trim()}
              style={{
                flex: 1, padding: '0.5rem',
                backgroundColor: isRendering ? 'var(--bg3)' : 'var(--amber-m)',
                border: `1px solid ${isRendering || !localScript.trim() ? 'transparent' : 'var(--amber)'}`,
                borderRadius: '6px',
                color: busy || !localScript.trim() ? 'var(--t3)' : 'var(--amber)',
                fontSize: '0.8125rem', fontWeight: 600,
                cursor: busy || !localScript.trim() ? 'default' : 'pointer',
              }}
            >
              {isRendering ? t.rendering : hasAudio ? t.reRender : t.renderAudio}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function PartList() {
  const { state } = useStudio()
  const { t } = useLang()
  const { outline, scripts, audioIds } = state

  if (!outline) return null

  const totalParts = outline.parts.length
  const doneScripts = Object.keys(scripts).length
  const doneAudio = Object.keys(audioIds).length

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {/* Outline header */}
      <div style={{
        padding: '0.75rem 1.125rem', borderBottom: '1px solid var(--bd)',
        backgroundColor: 'var(--bg1)', flexShrink: 0,
      }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--t1)', marginBottom: '0.25rem', lineHeight: 1.3 }}>
          {outline.topic}
        </h2>
        <div style={{ display: 'flex', gap: '0.75rem', fontSize: '0.75rem', color: 'var(--t2)' }}>
          <span>{totalParts} {t.partsLabel} · {outline.total_minutes} {t.minLabel}</span>
          {doneScripts > 0 && <span style={{ color: 'var(--ok)' }}>{doneScripts}/{totalParts} {t.scriptsBadge}</span>}
          {doneAudio > 0 && <span style={{ color: 'var(--amber)' }}>{doneAudio}/{totalParts} {t.audioBadge}</span>}
        </div>
      </div>

      {/* Accordion list */}
      <div style={{
        flex: 1, overflowY: 'auto', padding: '0.75rem 0.875rem',
        display: 'flex', flexDirection: 'column', gap: '0.5rem',
      }}>
        {outline.parts.map((part) => <PartItem key={part.index} part={part} />)}
      </div>
    </div>
  )
}
