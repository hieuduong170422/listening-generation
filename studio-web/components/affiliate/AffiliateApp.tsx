'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  startStoryboard, startClip, startStitch, pollJob,
  storyboardImageUrl, clipVideoUrl, finalVideoUrl, promptsUrl, fetchBlobUrl,
  type StoryboardItem,
} from '@/lib/affiliateApi'

// ── Types ────────────────────────────────────────────────────────────────────

type JobStatus = 'idle' | 'pending' | 'running' | 'done' | 'error'

interface ItemState {
  item: StoryboardItem
  clipJobId: string | null
  clipStatus: JobStatus
  clipMsg: string
  imageBlobUrl: string | null
  videoBlobUrl: string | null
}

interface State {
  images: File[]
  imagePreviews: string[]
  idea: string
  directions: string
  clips: number
  beatsPerClip: number
  sbJobId: string | null
  sbStatus: JobStatus
  sbMsg: string
  sbError: string | null
  sessionId: string | null
  product: string
  itemStates: ItemState[]
  stitchJobId: string | null
  stitchStatus: JobStatus
  stitchMsg: string
  finalBlobUrl: string | null
}

const INIT: State = {
  images: [], imagePreviews: [],
  idea: '', directions: '', clips: 3, beatsPerClip: 2,
  sbJobId: null, sbStatus: 'idle', sbMsg: '', sbError: null,
  sessionId: null, product: '', itemStates: [],
  stitchJobId: null, stitchStatus: 'idle', stitchMsg: '', finalBlobUrl: null,
}

// ── Shared style tokens (mirrors Studio) ─────────────────────────────────────

const lbl: React.CSSProperties = {
  fontSize: '0.6875rem', fontWeight: 600, color: 'var(--t3)',
  textTransform: 'uppercase', letterSpacing: '0.05em',
  display: 'block', marginBottom: '0.3rem',
}

const inp: React.CSSProperties = {
  width: '100%', padding: '0.4375rem 0.625rem',
  backgroundColor: 'var(--bg2)', border: '1px solid var(--bd)',
  borderRadius: '6px', color: 'var(--t1)', fontSize: '0.8125rem',
  outline: 'none', boxSizing: 'border-box', fontFamily: 'inherit',
}

const dvd: React.CSSProperties = {
  height: '1px', backgroundColor: 'var(--bd-s)', margin: '0.625rem 0',
}

// ── Left Rail ─────────────────────────────────────────────────────────────────

function ConfigRail({ st, setSt, onGenerate }: {
  st: State
  setSt: React.Dispatch<React.SetStateAction<State>>
  onGenerate: () => void
}) {
  const busy = st.sbStatus === 'running' || st.sbStatus === 'pending'

  const handleFiles = useCallback((files: File[]) => {
    if (!files.length) return
    setSt((prev) => {
      const newFiles = [...prev.images, ...files].slice(0, 10)
      const newPreviews = [...prev.imagePreviews, ...files.map(f => URL.createObjectURL(f))].slice(0, 10)
      return { ...prev, images: newFiles, imagePreviews: newPreviews }
    })
  }, [setSt])

  function removeImage(idx: number) {
    setSt((prev) => {
      URL.revokeObjectURL(prev.imagePreviews[idx])
      return {
        ...prev,
        images: prev.images.filter((_, i) => i !== idx),
        imagePreviews: prev.imagePreviews.filter((_, i) => i !== idx),
      }
    })
  }

  return (
    <aside style={{
      width: '260px', flexShrink: 0,
      backgroundColor: 'var(--bg1)',
      borderRight: '1px solid var(--bd)',
      display: 'flex', flexDirection: 'column',
      overflowY: 'auto',
    }}>
      <div style={{ flex: 1, padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>

        {/* Upload */}
        <div>
          <span style={lbl}>Ảnh sản phẩm ({st.images.length}/10)</span>
          <label
            style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              gap: '0.25rem', border: '1px dashed var(--bd)',
              borderRadius: '6px', padding: '0.75rem',
              cursor: 'pointer', backgroundColor: 'var(--bg2)',
              color: 'var(--t3)', fontSize: '0.75rem', textAlign: 'center',
            }}
            onDragOver={(e) => { e.preventDefault(); e.currentTarget.style.borderColor = 'var(--accent)' }}
            onDragLeave={(e) => { e.currentTarget.style.borderColor = 'var(--bd)' }}
            onDrop={(e) => {
              e.preventDefault()
              e.currentTarget.style.borderColor = 'var(--bd)'
              handleFiles(Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/')))
            }}
          >
            <span style={{ fontSize: '1.125rem' }}>📷</span>
            <span>Kéo thả hoặc <span style={{ color: 'var(--accent)' }}>click</span></span>
            <input type="file" multiple accept="image/*" style={{ display: 'none' }}
              onChange={(e) => handleFiles(Array.from(e.target.files ?? []))} />
          </label>

          {st.imagePreviews.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.375rem', marginTop: '0.5rem' }}>
              {st.imagePreviews.map((url, i) => (
                <div key={i} style={{ position: 'relative', width: '52px', height: '52px' }}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '4px', border: '1px solid var(--bd)' }} />
                  <button onClick={() => removeImage(i)} style={{
                    position: 'absolute', top: '1px', right: '1px',
                    width: '14px', height: '14px', borderRadius: '50%',
                    backgroundColor: 'rgba(0,0,0,0.7)', border: 'none',
                    color: '#fff', fontSize: '0.5rem', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>✕</button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={dvd} />

        {/* Idea */}
        <div>
          <label style={lbl}>Mô tả sản phẩm *</label>
          <textarea value={st.idea}
            onChange={(e) => setSt(p => ({ ...p, idea: e.target.value }))}
            rows={4} placeholder="vd: thùng rác treo tủ bếp, nắp kín, ruột tháo rời..."
            style={{ ...inp, resize: 'vertical', lineHeight: 1.5 }} />
        </div>

        {/* Directions */}
        <div>
          <label style={lbl}>Yêu cầu góc quay (tuỳ chọn)</label>
          <textarea value={st.directions}
            onChange={(e) => setSt(p => ({ ...p, directions: e.target.value }))}
            rows={2} placeholder="vd: cảnh 1 top-down, cảnh cuối cận sản phẩm..."
            style={{ ...inp, resize: 'vertical', lineHeight: 1.5 }} />
        </div>

        <div style={dvd} />

        {/* Sliders */}
        <div>
          <label style={lbl}>Số clip: <strong style={{ color: 'var(--t1)' }}>{st.clips}</strong></label>
          <input type="range" min={1} max={8} value={st.clips}
            onChange={(e) => setSt(p => ({ ...p, clips: Number(e.target.value) }))}
            style={{ width: '100%', accentColor: 'var(--accent)' }} />
        </div>

        <div>
          <label style={lbl}>Cảnh / clip: <strong style={{ color: 'var(--t1)' }}>{st.beatsPerClip}</strong></label>
          <input type="range" min={1} max={4} value={st.beatsPerClip}
            onChange={(e) => setSt(p => ({ ...p, beatsPerClip: Number(e.target.value) }))}
            style={{ width: '100%', accentColor: 'var(--accent)' }} />
        </div>

        <div style={{
          backgroundColor: 'var(--bg2)', border: '1px solid var(--bd)',
          borderRadius: '6px', padding: '0.4375rem 0.625rem',
          fontSize: '0.8125rem', color: 'var(--t2)',
        }}>
          Ước tính: <strong style={{ color: 'var(--t1)' }}>{st.clips * st.beatsPerClip * 4}s</strong>
          <span style={{ color: 'var(--t3)', fontSize: '0.75rem', marginLeft: '0.375rem' }}>
            ({st.clips} × {st.beatsPerClip} × 4s)
          </span>
        </div>
      </div>

      {/* Generate button — sticky bottom */}
      <div style={{ padding: '0.75rem 1rem', borderTop: '1px solid var(--bd)', backgroundColor: 'var(--bg1)' }}>
        {st.sbError && (
          <p style={{ fontSize: '0.75rem', color: '#E5534B', marginBottom: '0.5rem', lineHeight: 1.4 }}>
            {st.sbError}
          </p>
        )}
        <button
          onClick={onGenerate}
          disabled={busy || !st.images.length || !st.idea.trim()}
          style={{
            width: '100%', padding: '0.5625rem',
            backgroundColor: (busy || !st.images.length || !st.idea.trim()) ? 'var(--bg3)' : 'var(--accent)',
            border: 'none', borderRadius: '6px',
            color: (busy || !st.images.length || !st.idea.trim()) ? 'var(--t3)' : '#fff',
            fontSize: '0.875rem', fontWeight: 600,
            cursor: (busy || !st.images.length || !st.idea.trim()) ? 'default' : 'pointer',
          }}
        >
          {busy ? `⏳ ${st.sbMsg || 'Đang xử lý…'}` : '🚀 Sinh Storyboard'}
        </button>
      </div>
    </aside>
  )
}

// ── Clip card ─────────────────────────────────────────────────────────────────

function ClipCard({ is, sessionId, onRenderClip }: {
  is: ItemState
  sessionId: string
  onRenderClip: () => void
}) {
  const [open, setOpen] = useState(false)
  const busy = is.clipStatus === 'running' || is.clipStatus === 'pending'

  const dot = is.item.has_video ? 'var(--amber)'
    : is.clipStatus === 'error' ? '#E5534B'
    : (is.clipStatus === 'running' || is.clipStatus === 'pending') ? 'var(--accent)'
    : is.item.has_image ? 'var(--ok)'
    : 'var(--bd)'

  return (
    <div style={{ border: '1px solid var(--bd)', borderRadius: '8px', overflow: 'hidden', backgroundColor: 'var(--bg1)' }}>
      {/* Collapsed header */}
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', padding: '0.625rem 0.875rem',
          backgroundColor: 'transparent', border: 'none',
          display: 'flex', alignItems: 'center', gap: '0.625rem',
          cursor: 'pointer', textAlign: 'left',
        }}
      >
        <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: dot, flexShrink: 0 }} />
        <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--t1)', flex: 1 }}>
          Clip {is.item.index}
          {is.item.has_video && <span style={{ fontSize: '0.6875rem', fontWeight: 400, color: 'var(--amber)', marginLeft: '0.5rem' }}>✓ video</span>}
          {(is.clipStatus === 'running' || is.clipStatus === 'pending') && (
            <span style={{ fontSize: '0.6875rem', fontWeight: 400, color: 'var(--accent)', marginLeft: '0.5rem' }}>⏳ {is.clipMsg}</span>
          )}
          {is.clipStatus === 'error' && <span style={{ fontSize: '0.6875rem', fontWeight: 400, color: '#E5534B', marginLeft: '0.5rem' }}>✕ lỗi</span>}
        </span>
        <span style={{ fontSize: '0.6875rem', color: 'var(--t3)' }}>{is.item.scenes.length} cảnh</span>
        <span style={{ fontSize: '0.75rem', color: 'var(--t3)', display: 'inline-block', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }}>▾</span>
      </button>

      {/* Expanded */}
      {open && (
        <div style={{ borderTop: '1px solid var(--bd-s)', display: 'grid', gridTemplateColumns: '1fr 1.5fr' }}>
          {/* Left */}
          <div style={{ padding: '0.875rem', borderRight: '1px solid var(--bd-s)', display: 'flex', flexDirection: 'column', gap: '0.625rem' }}>
            {is.imageBlobUrl && (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img src={is.imageBlobUrl} alt="" style={{ width: '100%', borderRadius: '5px', border: '1px solid var(--bd)' }} />
            )}
            {is.videoBlobUrl && (
              <video controls src={is.videoBlobUrl} style={{ width: '100%', borderRadius: '5px', backgroundColor: '#000' }} />
            )}
            <button onClick={onRenderClip} disabled={busy} style={{
              padding: '0.4375rem 0.625rem',
              backgroundColor: busy ? 'var(--bg3)' : 'var(--amber-m)',
              border: `1px solid ${busy ? 'transparent' : 'var(--amber)'}`,
              borderRadius: '5px', color: busy ? 'var(--t3)' : 'var(--amber)',
              fontSize: '0.8125rem', fontWeight: 600, cursor: busy ? 'default' : 'pointer',
            }}>
              {busy ? '⏳ Đang render…' : is.item.has_video ? '↺ Render lại' : '▶ Tạo clip (Veo)'}
            </button>
            {is.clipStatus === 'error' && (
              <p style={{ fontSize: '0.75rem', color: '#E5534B', lineHeight: 1.4 }}>{is.clipMsg}</p>
            )}
            {is.videoBlobUrl && (
              <a href={is.videoBlobUrl} download={`clip_${is.item.index}.mp4`}
                style={{ fontSize: '0.75rem', color: 'var(--t3)', textDecoration: 'underline', textDecorationStyle: 'dotted' }}>
                ↓ Tải clip
              </a>
            )}
          </div>

          {/* Right */}
          <div style={{ padding: '0.875rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {is.item.scenes.length > 0 && (
              <div>
                <p style={{ ...lbl, marginBottom: '0.375rem' }}>Cảnh trong clip</p>
                <ol style={{ paddingLeft: '1.125rem', margin: 0, display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                  {is.item.scenes.map((sc, i) => (
                    <li key={i} style={{ fontSize: '0.8125rem', color: 'var(--t2)', lineHeight: 1.5 }}>{sc}</li>
                  ))}
                </ol>
              </div>
            )}
            {is.item.prompt && (
              <div style={{ flex: 1 }}>
                <p style={{ ...lbl, marginBottom: '0.375rem' }}>Prompt (EN)</p>
                <div style={{
                  backgroundColor: 'var(--bg2)', border: '1px solid var(--bd)',
                  borderRadius: '5px', padding: '0.5rem 0.625rem',
                  fontSize: '0.75rem', color: 'var(--t2)', lineHeight: 1.6,
                  maxHeight: '160px', overflowY: 'auto',
                  fontFamily: 'ui-monospace, monospace',
                }}>
                  {is.item.prompt}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Center panel ──────────────────────────────────────────────────────────────

function CenterPanel({ st, onClip, onStitch }: {
  st: State
  onClip: (index: number) => void
  onStitch: () => void
}) {
  const stitchBusy = st.stitchStatus === 'running' || st.stitchStatus === 'pending'
  const doneClips = st.itemStates.filter(is => is.item.has_video).length

  if (st.sbStatus === 'idle') {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--t3)', gap: '0.75rem' }}>
        <span style={{ fontSize: '2.5rem' }}>🎬</span>
        <div style={{ textAlign: 'center' }}>
          <p style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--t2)', marginBottom: '0.25rem' }}>Chưa có storyboard</p>
          <p style={{ fontSize: '0.8125rem', lineHeight: 1.6 }}>
            Upload ảnh sản phẩm + mô tả bên trái, rồi nhấn<br />
            <strong style={{ color: 'var(--accent)' }}>Sinh Storyboard</strong>
          </p>
        </div>
      </div>
    )
  }

  if (st.sbStatus === 'pending' || st.sbStatus === 'running') {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '0.875rem' }}>
        <div style={{
          width: '32px', height: '32px',
          border: '2px solid var(--bd)', borderTopColor: 'var(--accent)',
          borderRadius: '50%', animation: 'spin 0.8s linear infinite',
        }} />
        <p style={{ fontSize: '0.875rem', color: 'var(--t2)' }}>{st.sbMsg || 'Đang sinh storyboard…'}</p>
      </div>
    )
  }

  if (st.sbStatus === 'error') {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', color: '#E5534B' }}>
        <span style={{ fontSize: '2rem' }}>✕</span>
        <p style={{ fontSize: '0.875rem' }}>{st.sbError}</p>
      </div>
    )
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Toolbar */}
      <div style={{
        padding: '0.625rem 1rem', borderBottom: '1px solid var(--bd)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0,
        backgroundColor: 'var(--bg1)',
      }}>
        <div>
          <p style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--t1)' }}>{st.product || 'Storyboard'}</p>
          <p style={{ fontSize: '0.75rem', color: 'var(--t3)' }}>{st.itemStates.length} clip · {doneClips} đã render</p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          {st.sessionId && (
            <a href={promptsUrl(st.sessionId)} download="prompts.txt" style={{
              padding: '0.3125rem 0.625rem',
              backgroundColor: 'var(--bg2)', border: '1px solid var(--bd)',
              borderRadius: '5px', color: 'var(--t2)', fontSize: '0.75rem', textDecoration: 'none',
            }}>↓ Prompts</a>
          )}
          <button onClick={onStitch} disabled={stitchBusy} style={{
            padding: '0.3125rem 0.75rem',
            backgroundColor: stitchBusy ? 'var(--bg3)' : 'var(--amber-m)',
            border: `1px solid ${stitchBusy ? 'transparent' : 'var(--amber)'}`,
            borderRadius: '5px', color: stitchBusy ? 'var(--t3)' : 'var(--amber)',
            fontSize: '0.8125rem', fontWeight: 600, cursor: stitchBusy ? 'default' : 'pointer',
          }}>
            {stitchBusy ? `⏳ ${st.stitchMsg}` : `🎬 Nối ${doneClips} clip`}
          </button>
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '0.875rem 1rem', display: 'flex', flexDirection: 'column', gap: '0.625rem' }}>
        {/* Final video */}
        {st.finalBlobUrl && (
          <div style={{
            padding: '0.875rem', marginBottom: '0.25rem',
            backgroundColor: 'var(--bg2)', border: '1px solid var(--amber)', borderRadius: '8px',
          }}>
            <p style={{ ...lbl, color: 'var(--amber)', marginBottom: '0.625rem' }}>Video hoàn chỉnh</p>
            <video controls src={st.finalBlobUrl}
              style={{ width: '100%', maxHeight: '300px', borderRadius: '5px', backgroundColor: '#000', display: 'block' }} />
            <a href={st.finalBlobUrl} download="ugc_review.mp4" style={{
              display: 'inline-block', marginTop: '0.5rem',
              padding: '0.375rem 0.75rem',
              backgroundColor: 'var(--amber-m)', border: '1px solid var(--amber)',
              borderRadius: '5px', color: 'var(--amber)',
              fontSize: '0.8125rem', fontWeight: 600, textDecoration: 'none',
            }}>↓ Tải video</a>
          </div>
        )}

        {/* Clip cards */}
        {st.itemStates.map((is) => (
          <ClipCard
            key={is.item.index}
            is={is}
            sessionId={st.sessionId!}
            onRenderClip={() => onClip(is.item.index)}
          />
        ))}
      </div>
    </div>
  )
}

// ── Root ──────────────────────────────────────────────────────────────────────

export default function AffiliateApp() {
  const [st, setSt] = useState<State>(INIT)
  const sbPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const stitchPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const clipPollRefs = useRef<Record<number, ReturnType<typeof setInterval>>>({})
  const blobsRef = useRef<string[]>([])

  useEffect(() => {
    return () => {
      blobsRef.current.forEach(URL.revokeObjectURL)
      if (sbPollRef.current) clearInterval(sbPollRef.current)
      if (stitchPollRef.current) clearInterval(stitchPollRef.current)
      Object.values(clipPollRefs.current).forEach(clearInterval)
    }
  }, [])

  function trackBlob(url: string) { blobsRef.current.push(url); return url }

  async function handleGenerate() {
    if (!st.images.length || !st.idea.trim()) return
    setSt(p => ({ ...p, sbStatus: 'pending', sbMsg: 'Đang gửi…', sbError: null, itemStates: [], sessionId: null, finalBlobUrl: null, stitchStatus: 'idle' }))
    try {
      const { job_id, session_id } = await startStoryboard({
        images: st.images, idea: st.idea, directions: st.directions,
        clips: st.clips, beatsPerClip: st.beatsPerClip,
      })
      setSt(p => ({ ...p, sbJobId: job_id, sessionId: session_id, sbStatus: 'running', sbMsg: `Sinh ${st.clips} storyboard…` }))
      sbPollRef.current = setInterval(async () => {
        try {
          const job = await pollJob(job_id)
          if (job.status === 'done') {
            clearInterval(sbPollRef.current!)
            const result = job.result as { session_id: string; product: string; items: StoryboardItem[] }
            const itemStates: ItemState[] = await Promise.all(
              result.items.map(async (item): Promise<ItemState> => {
                let imageBlobUrl: string | null = null
                if (item.has_image) {
                  try { imageBlobUrl = trackBlob(await fetchBlobUrl(storyboardImageUrl(result.session_id, item.index))) } catch { /* */ }
                }
                return { item, clipJobId: null, clipStatus: 'idle', clipMsg: '', imageBlobUrl, videoBlobUrl: null }
              })
            )
            setSt(p => ({ ...p, sbStatus: 'done', sbMsg: '', product: result.product, itemStates }))
          } else if (job.status === 'error') {
            clearInterval(sbPollRef.current!)
            setSt(p => ({ ...p, sbStatus: 'error', sbError: job.error ?? 'Lỗi sinh storyboard' }))
          } else {
            setSt(p => ({ ...p, sbMsg: job.message }))
          }
        } catch (e) {
          clearInterval(sbPollRef.current!)
          setSt(p => ({ ...p, sbStatus: 'error', sbError: String(e) }))
        }
      }, 3000)
    } catch (e) {
      setSt(p => ({ ...p, sbStatus: 'error', sbError: String(e) }))
    }
  }

  async function handleClip(clipIndex: number) {
    if (!st.sessionId) return
    setSt(p => ({
      ...p,
      itemStates: p.itemStates.map(is =>
        is.item.index === clipIndex
          ? { ...is, clipStatus: 'running', clipMsg: 'Veo đang render…', videoBlobUrl: null }
          : is
      ),
    }))
    try {
      const { job_id } = await startClip(st.sessionId, clipIndex)
      const sid = st.sessionId
      clipPollRefs.current[clipIndex] = setInterval(async () => {
        try {
          const job = await pollJob(job_id)
          if (job.status === 'done') {
            clearInterval(clipPollRefs.current[clipIndex])
            let videoBlobUrl: string | null = null
            try { videoBlobUrl = trackBlob(await fetchBlobUrl(clipVideoUrl(sid, clipIndex))) } catch { /* */ }
            setSt(p => ({
              ...p,
              itemStates: p.itemStates.map(is =>
                is.item.index === clipIndex
                  ? { ...is, clipStatus: 'done', clipMsg: '', item: { ...is.item, has_video: true }, videoBlobUrl }
                  : is
              ),
            }))
          } else if (job.status === 'error') {
            clearInterval(clipPollRefs.current[clipIndex])
            setSt(p => ({
              ...p,
              itemStates: p.itemStates.map(is =>
                is.item.index === clipIndex ? { ...is, clipStatus: 'error', clipMsg: job.error ?? 'Lỗi' } : is
              ),
            }))
          } else {
            setSt(p => ({
              ...p,
              itemStates: p.itemStates.map(is =>
                is.item.index === clipIndex ? { ...is, clipMsg: job.message } : is
              ),
            }))
          }
        } catch (e) {
          clearInterval(clipPollRefs.current[clipIndex])
          setSt(p => ({
            ...p,
            itemStates: p.itemStates.map(is =>
              is.item.index === clipIndex ? { ...is, clipStatus: 'error', clipMsg: String(e) } : is
            ),
          }))
        }
      }, 4000)
    } catch (e) {
      setSt(p => ({
        ...p,
        itemStates: p.itemStates.map(is =>
          is.item.index === clipIndex ? { ...is, clipStatus: 'error', clipMsg: String(e) } : is
        ),
      }))
    }
  }

  async function handleStitch() {
    if (!st.sessionId) return
    setSt(p => ({ ...p, stitchStatus: 'running', stitchMsg: 'Đang nối…', finalBlobUrl: null }))
    try {
      const { job_id } = await startStitch(st.sessionId)
      const sid = st.sessionId
      stitchPollRef.current = setInterval(async () => {
        try {
          const job = await pollJob(job_id)
          if (job.status === 'done') {
            clearInterval(stitchPollRef.current!)
            let finalBlobUrl: string | null = null
            try { finalBlobUrl = trackBlob(await fetchBlobUrl(finalVideoUrl(sid))) } catch { /* */ }
            setSt(p => ({ ...p, stitchStatus: 'done', stitchMsg: '', finalBlobUrl }))
          } else if (job.status === 'error') {
            clearInterval(stitchPollRef.current!)
            setSt(p => ({ ...p, stitchStatus: 'error', stitchMsg: job.error ?? 'Lỗi nối clip' }))
          } else {
            setSt(p => ({ ...p, stitchMsg: job.message }))
          }
        } catch (e) {
          clearInterval(stitchPollRef.current!)
          setSt(p => ({ ...p, stitchStatus: 'error', stitchMsg: String(e) }))
        }
      }, 4000)
    } catch (e) {
      setSt(p => ({ ...p, stitchStatus: 'error', stitchMsg: String(e) }))
    }
  }

  return (
    <>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <ConfigRail st={st} setSt={setSt} onGenerate={handleGenerate} />
        <CenterPanel st={st} onClip={handleClip} onStitch={handleStitch} />
      </div>
    </>
  )
}
