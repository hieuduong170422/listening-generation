'use client'

import { useEffect, useRef, useState } from 'react'
import { useStudio } from '@/lib/store'
import { useLang } from '@/lib/lang'
import { generateScript, renderAudio, fetchAudioBlobUrl, downloadAudioFile, generateSubtitle, downloadTextFile, ApiError } from '@/lib/api'
import type { PartBrief } from '@/lib/types'

function PartItem({ part }: { part: PartBrief }) {
  const { state, dispatch } = useStudio()
  const { t } = useLang()
  const { config, scripts, audioIds, subtitles, generatingScript, renderingAudio } = state

  const isExpanded = state.selectedPart === part.index
  const scriptText = scripts[part.index] ?? ''
  const hasScript = Boolean(scriptText)
  const hasAudio = Boolean(audioIds[part.index])
  const hasSubtitle = Boolean(subtitles[part.index])
  const isGenerating = generatingScript === part.index
  const isRendering = renderingAudio === part.index

  const [localScript, setLocalScript] = useState(scriptText)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioLoading, setAudioLoading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [subtitling, setSubtitling] = useState(false)
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

  async function handleDownloadAudio() {
    const aid = audioIds[part.index]
    if (!aid || downloading) return
    setDownloading(true)
    try {
      await downloadAudioFile(aid, `part-${String(part.index).padStart(2, '0')}`)
    } catch (err) {
      dispatch({ type: 'SET_ERROR', message: err instanceof ApiError ? err.message : 'Download failed' })
    } finally {
      setDownloading(false)
    }
  }

  async function handleGenerateSubtitle() {
    const aid = audioIds[part.index]
    if (!aid || subtitling) return
    setSubtitling(true)
    dispatch({ type: 'SET_ERROR', message: null })
    try {
      const res = await generateSubtitle({ audioId: aid, language: config.language })
      dispatch({ type: 'SET_SUBTITLE', partIndex: part.index, srt: res.srt })
    } catch (err) {
      dispatch({ type: 'SET_ERROR', message: err instanceof ApiError ? err.message : 'Subtitle generation failed' })
    } finally {
      setSubtitling(false)
    }
  }

  function handleDownloadSubtitle() {
    const srt = subtitles[part.index]
    if (!srt) return
    downloadTextFile(srt, `part-${String(part.index).padStart(2, '0')}.srt`)
  }

  const busy = isGenerating || isRendering
  const otherGenerating = generatingScript !== null && !isGenerating
  const otherRendering = renderingAudio !== null && !isRendering
  let statusColor = 'var(--t3)'
  if (hasAudio || isRendering) statusColor = 'var(--amber)'
  else if (hasScript || isGenerating) statusColor = 'var(--ok)'

  return (
    <div style={{
      backgroundColor: 'var(--bg2)',
      border: `1px solid ${isExpanded ? 'var(--accent)' : 'var(--bd)'}`,
      borderRadius: '8px', overflow: 'hidden',
      transition: 'border-color 0.15s',
      flexShrink: 0,
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
          <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--t1)', lineHeight: 1.35 }}>
            {part.title}
          </div>
          {!isExpanded && (
            <div style={{
              fontSize: '0.75rem', color: 'var(--t2)', marginTop: '0.2rem', lineHeight: 1.5,
              display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
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
          {hasSubtitle && !isExpanded && (
            <span style={{
              fontSize: '0.5625rem', fontWeight: 700,
              padding: '0.125rem 0.375rem', borderRadius: '3px',
              backgroundColor: 'rgba(90,170,120,0.12)',
              border: '1px solid rgba(90,170,120,0.25)',
              color: 'var(--ok)', textTransform: 'uppercase', letterSpacing: '0.04em',
            }}>{t.subtitleBadge}</span>
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
              disabled={busy || otherGenerating}
              style={{
                flex: 1, padding: '0.5rem',
                backgroundColor: busy || otherGenerating ? 'var(--bg3)' : 'var(--accent)',
                border: 'none', borderRadius: '6px',
                color: busy || otherGenerating ? 'var(--t3)' : '#fff',
                fontSize: '0.8125rem', fontWeight: 600,
                cursor: busy || otherGenerating ? 'default' : 'pointer',
              }}
            >
              {isGenerating ? t.writing : hasScript ? t.regenScript : t.genScript}
            </button>
            <button
              onClick={handleRenderAudio}
              disabled={busy || otherRendering || !localScript.trim()}
              style={{
                flex: 1, padding: '0.5rem',
                backgroundColor: isRendering ? 'var(--bg3)' : 'var(--amber-m)',
                border: `1px solid ${isRendering || otherRendering || !localScript.trim() ? 'transparent' : 'var(--amber)'}`,
                borderRadius: '6px',
                color: busy || otherRendering || !localScript.trim() ? 'var(--t3)' : 'var(--amber)',
                fontSize: '0.8125rem', fontWeight: 600,
                cursor: busy || otherRendering || !localScript.trim() ? 'default' : 'pointer',
              }}
            >
              {isRendering ? t.rendering : hasAudio ? t.reRender : t.renderAudio}
            </button>
            {hasAudio && (
              <button
                onClick={handleDownloadAudio}
                disabled={downloading}
                title={t.downloadOne}
                style={{
                  flexShrink: 0, padding: '0.5rem 0.75rem',
                  backgroundColor: 'var(--bg3)',
                  border: '1px solid var(--bd)', borderRadius: '6px',
                  color: downloading ? 'var(--t3)' : 'var(--t2)',
                  fontSize: '0.8125rem', fontWeight: 600,
                  cursor: downloading ? 'default' : 'pointer',
                }}
              >
                {downloading ? t.downloadingAudio : t.downloadOne}
              </button>
            )}
          </div>

          {/* Subtitle row — chỉ khi part đã có audio */}
          {hasAudio && (
            <div style={{
              display: 'flex', gap: '0.5rem', padding: '0 1rem 0.625rem',
              backgroundColor: 'var(--bg1)',
            }}>
              <button
                onClick={handleGenerateSubtitle}
                disabled={subtitling}
                style={{
                  flex: 1, padding: '0.5rem',
                  backgroundColor: 'var(--bg3)',
                  border: '1px solid var(--bd)', borderRadius: '6px',
                  color: subtitling ? 'var(--t3)' : 'var(--t2)',
                  fontSize: '0.8125rem', fontWeight: 600,
                  cursor: subtitling ? 'default' : 'pointer',
                }}
              >
                {subtitling ? t.subtitling : hasSubtitle ? t.reGenSubtitle : t.genSubtitle}
              </button>
              {hasSubtitle && (
                <button
                  onClick={handleDownloadSubtitle}
                  style={{
                    flexShrink: 0, padding: '0.5rem 0.75rem',
                    backgroundColor: 'var(--bg3)',
                    border: '1px solid var(--bd)', borderRadius: '6px',
                    color: 'var(--t2)',
                    fontSize: '0.8125rem', fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  {t.downloadSrt}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function PartList() {
  const { state, dispatch } = useStudio()
  const { t } = useLang()
  const { outline, scripts, audioIds, subtitles, config, generatingScript, renderingAudio } = state

  const [batchRunning, setBatchRunning] = useState(false)
  const [renderAllRunning, setRenderAllRunning] = useState(false)
  const [downloadingAll, setDownloadingAll] = useState(false)
  const [subAllRunning, setSubAllRunning] = useState(false)
  const [subAllPart, setSubAllPart] = useState<number | null>(null)
  const cancelRef = useRef(false)
  const abortRef = useRef<AbortController | null>(null)
  const cancelAudioRef = useRef(false)
  const abortAudioRef = useRef<AbortController | null>(null)
  const cancelSubRef = useRef(false)

  if (!outline) return null

  const totalParts = outline.parts.length
  const doneScripts = Object.keys(scripts).length
  const doneAudio = Object.keys(audioIds).length
  const doneSubtitles = Object.keys(subtitles).length
  const allDone = doneScripts >= totalParts
  // Part đủ điều kiện render audio: đã có script, chưa có audio
  const audioPending = outline.parts.filter(
    (p) => scripts[p.index]?.trim() && !audioIds[p.index],
  ).length
  // Part đủ điều kiện tạo phụ đề: đã có audio, chưa có phụ đề
  const subtitlePending = outline.parts.filter(
    (p) => audioIds[p.index] && !subtitles[p.index],
  ).length

  async function handleGenerateAll() {
    if (!outline || batchRunning) return
    setBatchRunning(true)
    cancelRef.current = false
    dispatch({ type: 'SET_ERROR', message: null })

    let accumulated: Record<string, string> = Object.fromEntries(
      Object.entries(scripts).map(([k, v]) => [String(k), v])
    )

    try {
      for (const part of outline.parts) {
        if (cancelRef.current) break
        if (accumulated[String(part.index)]) continue

        dispatch({ type: 'SET_GENERATING_SCRIPT', partIndex: part.index })
        const controller = new AbortController()
        abortRef.current = controller
        try {
          const res = await generateScript({
            config,
            outline,
            partIndex: part.index,
            previousScripts: accumulated,
            signal: controller.signal,
          })
          accumulated = { ...accumulated, [String(part.index)]: res.text }
          dispatch({ type: 'SET_SCRIPT', partIndex: part.index, text: res.text })
        } catch (err) {
          if (cancelRef.current) break
          const msg = err instanceof ApiError ? err.message : 'Script generation failed'
          dispatch({ type: 'SET_ERROR', message: `${t.batchFailedAt} ${part.index}: ${msg}` })
          break
        }
      }
    } finally {
      abortRef.current = null
      dispatch({ type: 'SET_GENERATING_SCRIPT', partIndex: null })
      setBatchRunning(false)
    }
  }

  function handleCancelAll() {
    cancelRef.current = true
    abortRef.current?.abort()
  }

  async function handleRenderAll() {
    if (!outline || renderAllRunning || batchRunning) return
    if (Object.keys(scripts).length < outline.parts.length) {
      dispatch({ type: 'SET_ERROR', message: t.finishScriptsFirst })
      return
    }
    if (config.host_voices.filter(Boolean).length === 0) {
      dispatch({ type: 'SET_ERROR', message: t.selectVoiceFirst })
      return
    }
    setRenderAllRunning(true)
    cancelAudioRef.current = false
    dispatch({ type: 'SET_ERROR', message: null })
    try {
      for (const part of outline.parts) {
        if (cancelAudioRef.current) break
        const script = scripts[part.index]
        if (!script?.trim() || audioIds[part.index]) continue

        dispatch({ type: 'SET_RENDERING_AUDIO', partIndex: part.index })
        const controller = new AbortController()
        abortAudioRef.current = controller
        try {
          const res = await renderAudio({
            config, partIndex: part.index, script, signal: controller.signal,
          })
          dispatch({ type: 'SET_AUDIO_ID', partIndex: part.index, audioId: res.audio_id })
        } catch (err) {
          if (cancelAudioRef.current) break
          const msg = err instanceof ApiError ? err.message : 'Audio render failed'
          dispatch({ type: 'SET_ERROR', message: `${t.batchFailedAt} ${part.index}: ${msg}` })
          break
        }
      }
    } finally {
      abortAudioRef.current = null
      dispatch({ type: 'SET_RENDERING_AUDIO', partIndex: null })
      setRenderAllRunning(false)
    }
  }

  function handleCancelRenderAll() {
    cancelAudioRef.current = true
    abortAudioRef.current?.abort()
  }

  async function handleSubtitleAll() {
    if (!outline || subAllRunning) return
    setSubAllRunning(true)
    cancelSubRef.current = false
    dispatch({ type: 'SET_ERROR', message: null })
    try {
      for (const part of outline.parts) {
        if (cancelSubRef.current) break
        const aid = audioIds[part.index]
        if (!aid || subtitles[part.index]) continue

        setSubAllPart(part.index)
        try {
          const res = await generateSubtitle({ audioId: aid, language: config.language })
          dispatch({ type: 'SET_SUBTITLE', partIndex: part.index, srt: res.srt })
        } catch (err) {
          if (cancelSubRef.current) break
          const msg = err instanceof ApiError ? err.message : 'Subtitle generation failed'
          dispatch({ type: 'SET_ERROR', message: `${t.batchFailedAt} ${part.index}: ${msg}` })
          break
        }
      }
    } finally {
      setSubAllPart(null)
      setSubAllRunning(false)
    }
  }

  function handleCancelSubtitleAll() {
    cancelSubRef.current = true
  }

  async function handleDownloadAll() {
    if (!outline || downloadingAll) return
    setDownloadingAll(true)
    let failed = 0
    try {
      for (const part of outline.parts) {
        const aid = audioIds[part.index]
        if (!aid) continue
        try {
          await downloadAudioFile(aid, `part-${String(part.index).padStart(2, '0')}`)
        } catch {
          failed += 1 // audio có thể đã mất sau khi server restart — bỏ qua part này
        }
      }
      if (failed > 0) {
        dispatch({ type: 'SET_ERROR', message: `${failed} audio không tải được (có thể đã mất sau khi server restart)` })
      }
    } finally {
      setDownloadingAll(false)
    }
  }

  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {/* Outline header */}
      <div style={{
        padding: '0.75rem 1.125rem', borderBottom: '1px solid var(--bd)',
        backgroundColor: 'var(--bg1)', flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem',
      }}>
        <div style={{ minWidth: 0 }}>
          <h2 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--t1)', marginBottom: '0.25rem', lineHeight: 1.3 }}>
            {outline.topic}
          </h2>
          <div style={{ display: 'flex', gap: '0.75rem', fontSize: '0.75rem', color: 'var(--t2)', flexWrap: 'wrap' }}>
            <span>{totalParts} {t.partsLabel} · {outline.total_minutes} {t.minLabel}</span>
            {doneScripts > 0 && <span style={{ color: 'var(--ok)' }}>{doneScripts}/{totalParts} {t.scriptsBadge}</span>}
            {doneAudio > 0 && <span style={{ color: 'var(--amber)' }}>{doneAudio}/{totalParts} {t.audioBadge}</span>}
            {doneSubtitles > 0 && <span style={{ color: 'var(--ok)' }}>{doneSubtitles}/{totalParts} {t.subtitleBadge}</span>}
          </div>
        </div>

        {/* Batch actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0 }}>
          {doneAudio > 0 && (
            <button
              onClick={handleDownloadAll}
              disabled={downloadingAll}
              style={{
                padding: '0.4375rem 0.875rem',
                backgroundColor: 'var(--amber-m)',
                border: '1px solid var(--amber)',
                borderRadius: '6px',
                color: downloadingAll ? 'var(--t3)' : 'var(--amber)',
                fontSize: '0.8125rem', fontWeight: 600,
                cursor: downloadingAll ? 'default' : 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              {downloadingAll ? t.downloadingAudio : `${t.downloadAll} (${doneAudio})`}
            </button>
          )}
          {batchRunning && generatingScript !== null && (
            <span style={{
              fontSize: '0.75rem', color: 'var(--accent)', fontWeight: 600,
              animation: 'pulse 1.5s ease-in-out infinite',
              whiteSpace: 'nowrap',
            }}>
              {t.writingPart} {generatingScript}/{totalParts}…
            </span>
          )}
          {batchRunning ? (
            <button
              onClick={handleCancelAll}
              style={{
                padding: '0.4375rem 0.875rem',
                backgroundColor: 'rgba(224,82,82,0.12)',
                border: '1px solid rgba(224,82,82,0.45)',
                borderRadius: '6px',
                color: '#e05252',
                fontSize: '0.8125rem', fontWeight: 600,
                cursor: 'pointer', whiteSpace: 'nowrap',
              }}
            >
              {t.cancelBtn}
            </button>
          ) : (
            <button
              onClick={handleGenerateAll}
              disabled={allDone || generatingScript !== null || renderAllRunning}
              title={allDone ? t.allScriptsDone : undefined}
              style={{
                padding: '0.4375rem 0.875rem',
                backgroundColor: allDone || generatingScript !== null || renderAllRunning ? 'var(--bg3)' : 'var(--accent)',
                border: 'none', borderRadius: '6px',
                color: allDone || generatingScript !== null || renderAllRunning ? 'var(--t3)' : '#fff',
                fontSize: '0.8125rem', fontWeight: 600,
                cursor: allDone || generatingScript !== null || renderAllRunning ? 'default' : 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              {t.genAllScripts}
            </button>
          )}

          {/* Batch render audio — chỉ hiện khi TẤT CẢ part đã có script */}
          {allDone && renderAllRunning && renderingAudio !== null && (
            <span style={{
              fontSize: '0.75rem', color: 'var(--amber)', fontWeight: 600,
              animation: 'pulse 1.5s ease-in-out infinite',
              whiteSpace: 'nowrap',
            }}>
              {t.renderingAudioPart} {renderingAudio}/{totalParts}…
            </span>
          )}
          {allDone && (renderAllRunning ? (
            <button
              onClick={handleCancelRenderAll}
              style={{
                padding: '0.4375rem 0.875rem',
                backgroundColor: 'rgba(224,82,82,0.12)',
                border: '1px solid rgba(224,82,82,0.45)',
                borderRadius: '6px',
                color: '#e05252',
                fontSize: '0.8125rem', fontWeight: 600,
                cursor: 'pointer', whiteSpace: 'nowrap',
              }}
            >
              {t.cancelBtn}
            </button>
          ) : (
            <button
              onClick={handleRenderAll}
              disabled={audioPending === 0 || batchRunning || renderingAudio !== null}
              title={audioPending === 0 ? t.allAudioDone : undefined}
              style={{
                padding: '0.4375rem 0.875rem',
                backgroundColor: audioPending === 0 || batchRunning || renderingAudio !== null
                  ? 'var(--bg3)' : 'var(--amber-m)',
                border: `1px solid ${audioPending === 0 || batchRunning || renderingAudio !== null ? 'transparent' : 'var(--amber)'}`,
                borderRadius: '6px',
                color: audioPending === 0 || batchRunning || renderingAudio !== null ? 'var(--t3)' : 'var(--amber)',
                fontSize: '0.8125rem', fontWeight: 600,
                cursor: audioPending === 0 || batchRunning || renderingAudio !== null ? 'default' : 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              {t.renderAllAudio}{audioPending > 0 ? ` (${audioPending})` : ''}
            </button>
          ))}

          {/* Batch tạo phụ đề — chỉ hiện khi đã có ít nhất 1 audio */}
          {doneAudio > 0 && subAllRunning && subAllPart !== null && (
            <span style={{
              fontSize: '0.75rem', color: 'var(--ok)', fontWeight: 600,
              animation: 'pulse 1.5s ease-in-out infinite',
              whiteSpace: 'nowrap',
            }}>
              {t.subtitlingPart} {subAllPart}/{totalParts}…
            </span>
          )}
          {doneAudio > 0 && (subAllRunning ? (
            <button
              onClick={handleCancelSubtitleAll}
              style={{
                padding: '0.4375rem 0.875rem',
                backgroundColor: 'rgba(224,82,82,0.12)',
                border: '1px solid rgba(224,82,82,0.45)',
                borderRadius: '6px',
                color: '#e05252',
                fontSize: '0.8125rem', fontWeight: 600,
                cursor: 'pointer', whiteSpace: 'nowrap',
              }}
            >
              {t.cancelBtn}
            </button>
          ) : (
            <button
              onClick={handleSubtitleAll}
              disabled={subtitlePending === 0}
              title={subtitlePending === 0 ? t.allSubtitlesDone : undefined}
              style={{
                padding: '0.4375rem 0.875rem',
                backgroundColor: subtitlePending === 0 ? 'var(--bg3)' : 'var(--bg3)',
                border: `1px solid ${subtitlePending === 0 ? 'transparent' : 'var(--bd)'}`,
                borderRadius: '6px',
                color: subtitlePending === 0 ? 'var(--t3)' : 'var(--t1)',
                fontSize: '0.8125rem', fontWeight: 600,
                cursor: subtitlePending === 0 ? 'default' : 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              {t.genAllSubtitles}{subtitlePending > 0 ? ` (${subtitlePending})` : ''}
            </button>
          ))}
        </div>
      </div>

      {/* Accordion list */}
      <div style={{
        flex: 1, minHeight: 0, overflowY: 'auto', padding: '0.75rem 0.875rem',
        display: 'flex', flexDirection: 'column', gap: '0.625rem',
      }}>
        {outline.parts.map((part) => <PartItem key={part.index} part={part} />)}
      </div>
    </div>
  )
}
