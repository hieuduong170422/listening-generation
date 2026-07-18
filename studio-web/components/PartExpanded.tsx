'use client'

import { useEffect, useRef, useState } from 'react'
import { useStudio } from '@/lib/store'
import { generateScript, renderAudio, fetchAudioBlobUrl, ApiError } from '@/lib/api'

export default function PartExpanded() {
  const { state, dispatch } = useStudio()
  const { outline, config, scripts, audioIds, selectedPart, generatingScript, renderingAudio } = state

  const part = outline?.parts.find((p) => p.index === selectedPart)

  const [localScript, setLocalScript] = useState('')
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioLoading, setAudioLoading] = useState(false)
  const prevAudioRef = useRef<string | null>(null)

  // Sync local script with store when part changes
  useEffect(() => {
    if (selectedPart == null) return
    setLocalScript(scripts[selectedPart] ?? '')
    setAudioUrl(null)
  }, [selectedPart, scripts])

  // Load audio blob when audioId is set
  useEffect(() => {
    if (selectedPart == null) return
    const aid = audioIds[selectedPart]
    if (!aid) { setAudioUrl(null); return }

    setAudioLoading(true)
    fetchAudioBlobUrl(aid)
      .then((url) => {
        if (prevAudioRef.current) URL.revokeObjectURL(prevAudioRef.current)
        prevAudioRef.current = url
        setAudioUrl(url)
      })
      .catch(() => setAudioUrl(null))
      .finally(() => setAudioLoading(false))
  }, [selectedPart, audioIds])

  // Cleanup blob URLs on unmount
  useEffect(() => {
    return () => { if (prevAudioRef.current) URL.revokeObjectURL(prevAudioRef.current) }
  }, [])

  if (!part || selectedPart == null) return null

  const isGenerating = generatingScript === selectedPart
  const isRendering = renderingAudio === selectedPart
  const scriptText = scripts[selectedPart] ?? ''
  const charCount = scriptText.length

  async function handleGenerateScript() {
    if (!outline) return
    const previousScripts = Object.fromEntries(
      Object.entries(scripts).map(([k, v]) => [String(k), v])
    )
    dispatch({ type: 'SET_GENERATING_SCRIPT', partIndex: selectedPart! })
    dispatch({ type: 'SET_ERROR', message: null })
    try {
      const res = await generateScript({
        config,
        outline,
        partIndex: selectedPart!,
        previousScripts,
      })
      dispatch({ type: 'SET_SCRIPT', partIndex: selectedPart!, text: res.text })
      setLocalScript(res.text)
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Script generation failed'
      dispatch({ type: 'SET_ERROR', message: msg })
    } finally {
      dispatch({ type: 'SET_GENERATING_SCRIPT', partIndex: null })
    }
  }

  async function handleRenderAudio() {
    if (!outline) return
    const script = localScript || scriptText
    if (!script.trim()) {
      dispatch({ type: 'SET_ERROR', message: 'Generate or write a script first' })
      return
    }
    dispatch({ type: 'SET_RENDERING_AUDIO', partIndex: selectedPart! })
    dispatch({ type: 'SET_ERROR', message: null })
    try {
      const res = await renderAudio({
        config,
        partIndex: selectedPart!,
        script,
      })
      dispatch({ type: 'SET_AUDIO_ID', partIndex: selectedPart!, audioId: res.audio_id })
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Audio render failed'
      dispatch({ type: 'SET_ERROR', message: msg })
    } finally {
      dispatch({ type: 'SET_RENDERING_AUDIO', partIndex: null })
    }
  }

  function handleScriptChange(text: string) {
    setLocalScript(text)
    dispatch({ type: 'SET_SCRIPT', partIndex: selectedPart!, text })
  }

  return (
    <div style={{
      width: '420px',
      flexShrink: 0,
      backgroundColor: 'var(--bg1)',
      borderLeft: '1px solid var(--bd)',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '1rem',
        borderBottom: '1px solid var(--bd)',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: '0.5rem',
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
            <span style={{
              width: '22px', height: '22px', borderRadius: '50%',
              backgroundColor: 'var(--accent)', display: 'flex',
              alignItems: 'center', justifyContent: 'center',
              fontSize: '0.6875rem', fontWeight: 700, color: '#fff', flexShrink: 0,
            }}>
              {part.index}
            </span>
            <h3 style={{ fontSize: '0.9375rem', fontWeight: 700, color: 'var(--t1)', lineHeight: 1.3 }}>
              {part.title}
            </h3>
          </div>
          <p style={{ fontSize: '0.75rem', color: 'var(--t2)', lineHeight: 1.5, paddingLeft: '1.875rem' }}>
            {part.summary}
          </p>
        </div>
        <button
          onClick={() => dispatch({ type: 'SELECT_PART', partIndex: null })}
          style={{
            flexShrink: 0, width: '24px', height: '24px',
            backgroundColor: 'transparent', border: 'none',
            color: 'var(--t3)', cursor: 'pointer', fontSize: '1.125rem',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            borderRadius: '4px',
          }}
          title="Close"
        >
          ×
        </button>
      </div>

      {/* Key points */}
      {part.key_points.length > 0 && (
        <div style={{
          padding: '0.75rem 1rem',
          borderBottom: '1px solid var(--bd-s)',
          flexShrink: 0,
        }}>
          <p style={{
            fontSize: '0.6875rem', fontWeight: 600, color: 'var(--t3)',
            textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.5rem',
          }}>
            Key points
          </p>
          <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
            {part.key_points.map((kp, i) => (
              <li key={i} style={{ display: 'flex', gap: '0.5rem', fontSize: '0.75rem', color: 'var(--t2)', lineHeight: 1.5 }}>
                <span style={{ color: 'var(--accent)', flexShrink: 0 }}>·</span>
                {kp}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Script editor */}
      <div style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        overflow: 'hidden', padding: '0.75rem 1rem',
      }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          marginBottom: '0.5rem',
        }}>
          <span style={{
            fontSize: '0.6875rem', fontWeight: 600, color: 'var(--t3)',
            textTransform: 'uppercase', letterSpacing: '0.05em',
          }}>
            Script
          </span>
          {charCount > 0 && (
            <span style={{
              fontSize: '0.6875rem', color: 'var(--t3)',
              fontVariantNumeric: 'tabular-nums',
            }}>
              {charCount.toLocaleString()} chars
            </span>
          )}
        </div>

        <textarea
          value={localScript}
          onChange={(e) => handleScriptChange(e.target.value)}
          placeholder={isGenerating ? 'Writing script…' : 'Script will appear here. Click "Generate script" or type directly.'}
          disabled={isGenerating}
          style={{
            flex: 1,
            backgroundColor: 'var(--bg2)',
            border: '1px solid var(--bd)',
            borderRadius: '6px',
            color: isGenerating ? 'var(--t3)' : 'var(--t1)',
            fontSize: '0.8125rem',
            lineHeight: 1.7,
            padding: '0.75rem',
            resize: 'none',
            outline: 'none',
            fontFamily: 'inherit',
            width: '100%',
          }}
        />
      </div>

      {/* Audio player */}
      {(audioUrl || audioLoading) && (
        <div style={{
          padding: '0.75rem 1rem',
          borderTop: '1px solid var(--bd-s)',
          flexShrink: 0,
        }}>
          <p style={{
            fontSize: '0.6875rem', fontWeight: 600, color: 'var(--t3)',
            textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.5rem',
          }}>
            Audio
          </p>
          {audioLoading ? (
            <div style={{ fontSize: '0.75rem', color: 'var(--t3)', padding: '0.5rem 0' }}>
              Loading audio…
            </div>
          ) : audioUrl ? (
            <audio
              controls
              src={audioUrl}
              style={{ width: '100%', accentColor: 'var(--amber)', height: '36px' }}
            />
          ) : null}
        </div>
      )}

      {/* Action buttons */}
      <div style={{
        padding: '0.75rem 1rem',
        borderTop: '1px solid var(--bd)',
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        gap: '0.5rem',
      }}>
        <button
          onClick={handleGenerateScript}
          disabled={isGenerating || isRendering}
          style={{
            width: '100%',
            padding: '0.5625rem',
            backgroundColor: isGenerating || isRendering ? 'var(--bg3)' : 'var(--accent)',
            border: 'none', borderRadius: '6px',
            color: isGenerating || isRendering ? 'var(--t3)' : '#fff',
            fontSize: '0.8125rem', fontWeight: 600,
            cursor: isGenerating || isRendering ? 'default' : 'pointer',
          }}
        >
          {isGenerating ? 'Writing script…' : scriptText ? 'Regenerate script' : 'Generate script'}
        </button>

        <button
          onClick={handleRenderAudio}
          disabled={isRendering || isGenerating || !localScript.trim()}
          style={{
            width: '100%',
            padding: '0.5625rem',
            backgroundColor: isRendering ? 'var(--bg3)' : 'var(--amber-m)',
            border: `1px solid ${isRendering ? 'transparent' : 'var(--amber)'}`,
            borderRadius: '6px',
            color: isRendering || isGenerating || !localScript.trim()
              ? 'var(--t3)' : 'var(--amber)',
            fontSize: '0.8125rem', fontWeight: 600,
            cursor: isRendering || isGenerating || !localScript.trim() ? 'default' : 'pointer',
          }}
        >
          {isRendering ? 'Rendering audio…' : audioIds[selectedPart!] ? 'Re-render audio' : 'Render audio'}
        </button>
      </div>
    </div>
  )
}
