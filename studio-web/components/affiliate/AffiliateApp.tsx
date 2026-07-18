'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  startStoryboard, startClip, startStitch, pollJob,
  storyboardImageUrl, clipVideoUrl, finalVideoUrl, promptsUrl, fetchBlobUrl,
  type StoryboardItem,
} from '@/lib/affiliateApi'
import { getToken } from '@/lib/api'

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
  // form
  images: File[]
  imagePreviews: string[]
  idea: string
  directions: string
  clips: number
  beatsPerClip: number
  // storyboard job
  sbJobId: string | null
  sbStatus: JobStatus
  sbMsg: string
  sbError: string | null
  // results
  sessionId: string | null
  product: string
  itemStates: ItemState[]
  // stitch
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

// ── Helpers ──────────────────────────────────────────────────────────────────

function authFetch(url: string) {
  const token = getToken()
  return fetch(url, token ? { headers: { Authorization: `Bearer ${token}` } } : {})
}

const s = {
  label: {
    fontSize: '0.6875rem', fontWeight: 600 as const, color: 'var(--t3)',
    textTransform: 'uppercase' as const, letterSpacing: '0.05em',
    display: 'block', marginBottom: '0.3rem',
  },
  input: {
    width: '100%', padding: '0.5rem 0.625rem',
    backgroundColor: 'var(--bg2)', border: '1px solid var(--bd)',
    borderRadius: '6px', color: 'var(--t1)', fontSize: '0.8125rem',
    outline: 'none', boxSizing: 'border-box' as const,
  },
  card: {
    backgroundColor: 'var(--bg2)', border: '1px solid var(--bd)',
    borderRadius: '8px', overflow: 'hidden' as const,
  },
  sectionTitle: {
    fontSize: '0.75rem', fontWeight: 700 as const, color: 'var(--t3)',
    textTransform: 'uppercase' as const, letterSpacing: '0.07em',
  },
}

function StatusLine({ status, msg, error }: { status: JobStatus; msg: string; error?: string | null }) {
  if (status === 'idle') return null
  const color = status === 'error' ? '#E5534B' : status === 'done' ? 'var(--ok)' : 'var(--accent)'
  const bg = status === 'error' ? 'rgba(229,83,75,0.08)' : 'transparent'
  return (
    <div style={{
      fontSize: '0.8125rem', color, backgroundColor: bg,
      border: status === 'error' ? '1px solid rgba(229,83,75,0.2)' : 'none',
      borderRadius: '5px', padding: '0.4rem 0',
      display: 'flex', alignItems: 'center', gap: '0.5rem',
    }}>
      {(status === 'pending' || status === 'running') && (
        <span style={{ animation: 'pulse 1.5s ease-in-out infinite', fontSize: '0.75rem' }}>⏳</span>
      )}
      {status === 'done' && <span>✓</span>}
      {status === 'error' && <span>✕</span>}
      <span>{error ?? msg}</span>
    </div>
  )
}

function PrimaryBtn({ onClick, disabled, children }: { onClick: () => void; disabled: boolean; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        width: '100%', padding: '0.625rem',
        backgroundColor: disabled ? 'var(--bg3)' : 'var(--accent)',
        border: 'none', borderRadius: '6px',
        color: disabled ? 'var(--t3)' : '#fff',
        fontSize: '0.875rem', fontWeight: 600,
        cursor: disabled ? 'default' : 'pointer',
      }}
    >{children}</button>
  )
}

// ── Main Component ───────────────────────────────────────────────────────────

export default function AffiliateApp() {
  const [st, setSt] = useState<State>(INIT)
  const sbPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const stitchPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const clipPollRefs = useRef<Record<number, ReturnType<typeof setInterval>>>({})
  const blobsRef = useRef<string[]>([])

  // Revoke blob URLs on unmount
  useEffect(() => {
    return () => {
      blobsRef.current.forEach((u) => URL.revokeObjectURL(u))
      if (sbPollRef.current) clearInterval(sbPollRef.current)
      if (stitchPollRef.current) clearInterval(stitchPollRef.current)
      Object.values(clipPollRefs.current).forEach(clearInterval)
    }
  }, [])

  function trackBlob(url: string) {
    blobsRef.current.push(url)
    return url
  }

  // ── Image upload ────────────────────────────────────────────────────────────

  const handleFiles = useCallback((files: File[]) => {
    if (!files.length) return
    const previews = files.map((f) => URL.createObjectURL(f))
    previews.forEach((u) => blobsRef.current.push(u))
    setSt((prev) => ({
      ...prev,
      images: [...prev.images, ...files].slice(0, 10),
      imagePreviews: [...prev.imagePreviews, ...previews].slice(0, 10),
    }))
  }, [])

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

  // ── Storyboard generation ───────────────────────────────────────────────────

  async function handleGenerate() {
    if (!st.images.length || !st.idea.trim()) return
    setSt((prev) => ({ ...prev, sbStatus: 'pending', sbMsg: 'Đang gửi yêu cầu…', sbError: null, itemStates: [], sessionId: null, finalBlobUrl: null, stitchStatus: 'idle' }))

    try {
      const { job_id, session_id } = await startStoryboard({
        images: st.images,
        idea: st.idea,
        directions: st.directions,
        clips: st.clips,
        beatsPerClip: st.beatsPerClip,
      })
      setSt((prev) => ({ ...prev, sbJobId: job_id, sessionId: session_id, sbStatus: 'running', sbMsg: `Đang sinh ${st.clips} storyboard…` }))

      sbPollRef.current = setInterval(async () => {
        try {
          const job = await pollJob(job_id)
          if (job.status === 'done') {
            clearInterval(sbPollRef.current!)
            const result = job.result as { session_id: string; product: string; items: StoryboardItem[] }
            // Load storyboard images as blob URLs
            const itemStates: ItemState[] = await Promise.all(
              result.items.map(async (item): Promise<ItemState> => {
                let imageBlobUrl: string | null = null
                if (item.has_image) {
                  try {
                    imageBlobUrl = trackBlob(await fetchBlobUrl(storyboardImageUrl(result.session_id, item.index)))
                  } catch { /* ignore */ }
                }
                return { item, clipJobId: null, clipStatus: 'idle', clipMsg: '', imageBlobUrl, videoBlobUrl: null }
              })
            )
            setSt((prev) => ({
              ...prev,
              sbStatus: 'done', sbMsg: `Xong — ${result.items.length} storyboard`,
              product: result.product, itemStates,
            }))
          } else if (job.status === 'error') {
            clearInterval(sbPollRef.current!)
            setSt((prev) => ({ ...prev, sbStatus: 'error', sbError: job.error ?? 'Lỗi sinh storyboard' }))
          } else {
            setSt((prev) => ({ ...prev, sbMsg: job.message }))
          }
        } catch (e) {
          clearInterval(sbPollRef.current!)
          setSt((prev) => ({ ...prev, sbStatus: 'error', sbError: String(e) }))
        }
      }, 3000)
    } catch (e) {
      setSt((prev) => ({ ...prev, sbStatus: 'error', sbError: String(e) }))
    }
  }

  // ── Clip generation ─────────────────────────────────────────────────────────

  async function handleClip(clipIndex: number) {
    if (!st.sessionId) return
    setSt((prev) => ({
      ...prev,
      itemStates: prev.itemStates.map((is) =>
        is.item.index === clipIndex
          ? { ...is, clipStatus: 'running', clipMsg: 'Veo đang render… (~2-4 phút)', videoBlobUrl: null }
          : is
      ),
    }))

    try {
      const { job_id } = await startClip(st.sessionId, clipIndex)
      setSt((prev) => ({
        ...prev,
        itemStates: prev.itemStates.map((is) =>
          is.item.index === clipIndex ? { ...is, clipJobId: job_id } : is
        ),
      }))

      clipPollRefs.current[clipIndex] = setInterval(async () => {
        try {
          const job = await pollJob(job_id)
          if (job.status === 'done') {
            clearInterval(clipPollRefs.current[clipIndex])
            const sid = st.sessionId!
            let videoBlobUrl: string | null = null
            try {
              videoBlobUrl = trackBlob(await fetchBlobUrl(clipVideoUrl(sid, clipIndex)))
            } catch { /* ignore */ }
            setSt((prev) => ({
              ...prev,
              itemStates: prev.itemStates.map((is) =>
                is.item.index === clipIndex
                  ? { ...is, clipStatus: 'done', clipMsg: 'Clip xong', item: { ...is.item, has_video: true }, videoBlobUrl }
                  : is
              ),
            }))
          } else if (job.status === 'error') {
            clearInterval(clipPollRefs.current[clipIndex])
            setSt((prev) => ({
              ...prev,
              itemStates: prev.itemStates.map((is) =>
                is.item.index === clipIndex
                  ? { ...is, clipStatus: 'error', clipMsg: job.error ?? 'Lỗi render clip' }
                  : is
              ),
            }))
          } else {
            setSt((prev) => ({
              ...prev,
              itemStates: prev.itemStates.map((is) =>
                is.item.index === clipIndex ? { ...is, clipMsg: job.message } : is
              ),
            }))
          }
        } catch (e) {
          clearInterval(clipPollRefs.current[clipIndex])
          setSt((prev) => ({
            ...prev,
            itemStates: prev.itemStates.map((is) =>
              is.item.index === clipIndex
                ? { ...is, clipStatus: 'error', clipMsg: String(e) }
                : is
            ),
          }))
        }
      }, 4000)
    } catch (e) {
      setSt((prev) => ({
        ...prev,
        itemStates: prev.itemStates.map((is) =>
          is.item.index === clipIndex
            ? { ...is, clipStatus: 'error', clipMsg: String(e) }
            : is
        ),
      }))
    }
  }

  // ── Stitch ──────────────────────────────────────────────────────────────────

  async function handleStitch() {
    if (!st.sessionId) return
    setSt((prev) => ({ ...prev, stitchStatus: 'running', stitchMsg: 'Đang nối clip…', finalBlobUrl: null }))
    try {
      const { job_id } = await startStitch(st.sessionId)
      setSt((prev) => ({ ...prev, stitchJobId: job_id }))

      stitchPollRef.current = setInterval(async () => {
        try {
          const job = await pollJob(job_id)
          if (job.status === 'done') {
            clearInterval(stitchPollRef.current!)
            const sid = st.sessionId!
            let finalBlobUrl: string | null = null
            try {
              finalBlobUrl = trackBlob(await fetchBlobUrl(finalVideoUrl(sid)))
            } catch { /* ignore */ }
            setSt((prev) => ({
              ...prev,
              stitchStatus: 'done', stitchMsg: 'Video hoàn chỉnh đã sẵn sàng',
              finalBlobUrl,
            }))
          } else if (job.status === 'error') {
            clearInterval(stitchPollRef.current!)
            setSt((prev) => ({ ...prev, stitchStatus: 'error', stitchMsg: job.error ?? 'Lỗi nối clip' }))
          } else {
            setSt((prev) => ({ ...prev, stitchMsg: job.message }))
          }
        } catch (e) {
          clearInterval(stitchPollRef.current!)
          setSt((prev) => ({ ...prev, stitchStatus: 'error', stitchMsg: String(e) }))
        }
      }, 4000)
    } catch (e) {
      setSt((prev) => ({ ...prev, stitchStatus: 'error', stitchMsg: String(e) }))
    }
  }

  const totalDuration = st.clips * st.beatsPerClip * 4
  const doneClips = st.itemStates.filter((is) => is.item.has_video).length

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div style={{ maxWidth: '960px', margin: '0 auto', padding: '1.5rem 1.25rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

      {/* ── Step 1: Images ── */}
      <section>
        <h2 style={{ ...s.sectionTitle, marginBottom: '0.75rem' }}>1 — Ảnh sản phẩm</h2>

        {/* Upload zone */}
        <label
          style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            border: '2px dashed var(--bd)', borderRadius: '8px', padding: '1.5rem',
            cursor: 'pointer', backgroundColor: 'var(--bg2)',
            color: 'var(--t3)', fontSize: '0.875rem', gap: '0.375rem',
            transition: 'border-color 0.15s',
            marginBottom: '0.75rem',
          }}
          onDragOver={(e) => { e.preventDefault(); e.currentTarget.style.borderColor = 'var(--accent)' }}
          onDragLeave={(e) => { e.currentTarget.style.borderColor = 'var(--bd)' }}
          onDrop={(e) => {
            e.preventDefault()
            e.currentTarget.style.borderColor = 'var(--bd)'
            handleFiles(Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith('image/')))
          }}
        >
          <span style={{ fontSize: '1.5rem' }}>📷</span>
          <span>Kéo thả hoặc <strong style={{ color: 'var(--accent)' }}>click để upload</strong></span>
          <span style={{ fontSize: '0.75rem' }}>PNG, JPG, WEBP · tối đa 10 ảnh</span>
          <input
            type="file" multiple accept="image/*" style={{ display: 'none' }}
            onChange={(e) => handleFiles(Array.from(e.target.files ?? []))}
          />
        </label>

        {/* Previews */}
        {st.imagePreviews.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            {st.imagePreviews.map((url, i) => (
              <div key={i} style={{ position: 'relative', width: '80px', height: '80px' }}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '5px', border: '1px solid var(--bd)' }} />
                <button
                  onClick={() => removeImage(i)}
                  style={{
                    position: 'absolute', top: '2px', right: '2px',
                    width: '18px', height: '18px', borderRadius: '50%',
                    backgroundColor: 'rgba(0,0,0,0.6)', border: 'none',
                    color: '#fff', fontSize: '0.625rem', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}
                >✕</button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Step 2: Config ── */}
      <section style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        <h2 style={s.sectionTitle}>2 — Cấu hình</h2>

        <div>
          <label style={s.label}>Mô tả sản phẩm / ý tưởng chiến dịch *</label>
          <textarea
            value={st.idea}
            onChange={(e) => setSt((p) => ({ ...p, idea: e.target.value }))}
            rows={3}
            placeholder="vd: thùng rác treo tủ bếp, nắp đậy kín, ruột tháo rời đổ rác tiện…"
            style={{ ...s.input, resize: 'vertical', lineHeight: 1.5, fontFamily: 'inherit' }}
          />
        </div>

        <div>
          <label style={s.label}>Yêu cầu cụ thể về cảnh / góc quay (tuỳ chọn)</label>
          <textarea
            value={st.directions}
            onChange={(e) => setSt((p) => ({ ...p, directions: e.target.value }))}
            rows={2}
            placeholder="vd: cảnh 1 quay top-down; cảnh cuối cận sản phẩm…"
            style={{ ...s.input, resize: 'vertical', lineHeight: 1.5, fontFamily: 'inherit' }}
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
          <div>
            <label style={s.label}>Số clip: {st.clips}</label>
            <input type="range" min={1} max={8} value={st.clips}
              onChange={(e) => setSt((p) => ({ ...p, clips: Number(e.target.value) }))}
              style={{ width: '100%', accentColor: 'var(--accent)' }} />
          </div>
          <div>
            <label style={s.label}>Cảnh / clip: {st.beatsPerClip}</label>
            <input type="range" min={1} max={4} value={st.beatsPerClip}
              onChange={(e) => setSt((p) => ({ ...p, beatsPerClip: Number(e.target.value) }))}
              style={{ width: '100%', accentColor: 'var(--accent)' }} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
            <span style={{ fontSize: '0.8125rem', color: 'var(--t2)' }}>
              ≈ <strong style={{ color: 'var(--t1)' }}>{totalDuration}s</strong> video
            </span>
            <span style={{ fontSize: '0.75rem', color: 'var(--t3)' }}>
              {st.clips} clip × {st.beatsPerClip} cảnh × 4s
            </span>
          </div>
        </div>

        <PrimaryBtn
          onClick={handleGenerate}
          disabled={!st.images.length || !st.idea.trim() || st.sbStatus === 'running' || st.sbStatus === 'pending'}
        >
          {st.sbStatus === 'running' || st.sbStatus === 'pending' ? '⏳ Đang sinh storyboard…' : '🚀 Sinh Storyboard + Prompt'}
        </PrimaryBtn>

        <StatusLine status={st.sbStatus} msg={st.sbMsg} error={st.sbError} />
      </section>

      {/* ── Step 3: Results ── */}
      {st.itemStates.length > 0 && (
        <section>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
            <h2 style={s.sectionTitle}>
              3 — Kết quả {st.product && <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>— {st.product}</span>}
            </h2>
            <span style={{ fontSize: '0.75rem', color: 'var(--t2)' }}>
              {doneClips}/{st.itemStates.length} clip
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
            {st.itemStates.map((is) => (
              <ClipCard
                key={is.item.index}
                is={is}
                sessionId={st.sessionId!}
                onRenderClip={() => handleClip(is.item.index)}
              />
            ))}
          </div>

          {/* Stitch */}
          <div style={{ marginTop: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.625rem' }}>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <div style={{ flex: 1 }}>
                <PrimaryBtn
                  onClick={handleStitch}
                  disabled={st.stitchStatus === 'running' || st.stitchStatus === 'pending'}
                >
                  {st.stitchStatus === 'running' || st.stitchStatus === 'pending'
                    ? '⏳ Đang nối clip…'
                    : `🎬 Nối ${doneClips > 0 ? doneClips : 'tất cả'} clip thành video hoàn chỉnh`}
                </PrimaryBtn>
              </div>
              {st.sessionId && (
                <a
                  href={promptsUrl(st.sessionId)}
                  download="prompts.txt"
                  style={{
                    padding: '0.5rem 0.75rem', flexShrink: 0,
                    backgroundColor: 'var(--bg3)', border: '1px solid var(--bd)',
                    borderRadius: '6px', color: 'var(--t2)', fontSize: '0.8125rem',
                    textDecoration: 'none', whiteSpace: 'nowrap',
                  }}
                >
                  ↓ Tải prompt
                </a>
              )}
            </div>

            <StatusLine status={st.stitchStatus} msg={st.stitchMsg} />

            {st.finalBlobUrl && (
              <div style={{ ...s.card, padding: '1rem' }}>
                <p style={{ ...s.sectionTitle, marginBottom: '0.75rem' }}>Video hoàn chỉnh</p>
                <video
                  controls src={st.finalBlobUrl}
                  style={{ width: '100%', maxHeight: '480px', borderRadius: '6px', backgroundColor: '#000' }}
                />
                <a
                  href={st.finalBlobUrl}
                  download="ugc_review.mp4"
                  style={{
                    display: 'inline-block', marginTop: '0.625rem',
                    padding: '0.4375rem 0.875rem',
                    backgroundColor: 'var(--amber-m)', border: '1px solid var(--amber)',
                    borderRadius: '5px', color: 'var(--amber)',
                    fontSize: '0.8125rem', fontWeight: 600, textDecoration: 'none',
                  }}
                >
                  ↓ Tải video hoàn chỉnh
                </a>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  )
}

// ── ClipCard ─────────────────────────────────────────────────────────────────

function ClipCard({ is, sessionId, onRenderClip }: {
  is: ItemState
  sessionId: string
  onRenderClip: () => void
}) {
  const { item, clipStatus, clipMsg, imageBlobUrl, videoBlobUrl } = is
  const busy = clipStatus === 'running' || clipStatus === 'pending'

  return (
    <div style={{
      backgroundColor: 'var(--bg2)', border: '1px solid var(--bd)',
      borderRadius: '8px', overflow: 'hidden',
    }}>
      <div style={{ padding: '0.625rem 1rem', borderBottom: '1px solid var(--bd-s)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <span style={{
          width: '24px', height: '24px', borderRadius: '50%',
          backgroundColor: item.has_video ? 'var(--amber)' : item.has_image ? 'var(--ok)' : 'var(--bg3)',
          border: `1px solid ${item.has_video ? 'var(--amber)' : item.has_image ? 'var(--ok)' : 'var(--bd)'}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: '0.625rem', fontWeight: 700,
          color: item.has_video || item.has_image ? '#fff' : 'var(--t2)',
          flexShrink: 0,
        }}>{item.index}</span>
        <span style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--t1)' }}>
          Clip {item.index}
        </span>
        <span style={{ fontSize: '0.75rem', color: 'var(--t3)', marginLeft: 'auto' }}>
          {item.scenes.length} cảnh
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 0 }}>
        {/* Left: image + video + button */}
        <div style={{ padding: '0.875rem', borderRight: '1px solid var(--bd-s)', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {imageBlobUrl && (
            <div>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={imageBlobUrl} alt={`storyboard ${item.index}`}
                style={{ width: '100%', borderRadius: '5px', display: 'block' }} />
              <a
                href={storyboardImageUrl(sessionId, item.index)}
                download={`storyboard_${item.index}.png`}
                style={{
                  display: 'inline-block', marginTop: '0.375rem',
                  fontSize: '0.75rem', color: 'var(--t3)',
                  textDecoration: 'underline', textDecorationStyle: 'dotted',
                }}
              >↓ Tải ảnh</a>
            </div>
          )}

          {videoBlobUrl ? (
            <div>
              <video controls src={videoBlobUrl}
                style={{ width: '100%', borderRadius: '5px', backgroundColor: '#000' }} />
              <a href={videoBlobUrl} download={`clip_${item.index}.mp4`}
                style={{ display: 'inline-block', marginTop: '0.375rem', fontSize: '0.75rem', color: 'var(--t3)', textDecoration: 'underline', textDecorationStyle: 'dotted' }}>
                ↓ Tải clip
              </a>
            </div>
          ) : null}

          {item.error && (
            <p style={{ fontSize: '0.75rem', color: '#E5534B', lineHeight: 1.4 }}>{item.error}</p>
          )}

          <button
            onClick={onRenderClip}
            disabled={busy}
            style={{
              padding: '0.4375rem 0.625rem',
              backgroundColor: busy ? 'var(--bg3)' : 'var(--amber-m)',
              border: `1px solid ${busy ? 'transparent' : 'var(--amber)'}`,
              borderRadius: '5px',
              color: busy ? 'var(--t3)' : 'var(--amber)',
              fontSize: '0.8125rem', fontWeight: 600,
              cursor: busy ? 'default' : 'pointer',
            }}
          >
            {busy ? `⏳ ${clipMsg}` : item.has_video ? '↺ Tạo lại clip' : '▶ Tạo clip (Veo)'}
          </button>

          {clipStatus === 'error' && (
            <p style={{ fontSize: '0.75rem', color: '#E5534B' }}>{clipMsg}</p>
          )}
        </div>

        {/* Right: scenes + prompt */}
        <div style={{ padding: '0.875rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {item.scenes.length > 0 && (
            <div>
              <p style={{ fontSize: '0.6875rem', fontWeight: 600, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.375rem' }}>
                Cảnh trong clip
              </p>
              <ol style={{ paddingLeft: '1.125rem', margin: 0, display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                {item.scenes.map((sc, i) => (
                  <li key={i} style={{ fontSize: '0.8125rem', color: 'var(--t2)', lineHeight: 1.5 }}>{sc}</li>
                ))}
              </ol>
            </div>
          )}

          {item.prompt && (
            <div style={{ flex: 1 }}>
              <p style={{ fontSize: '0.6875rem', fontWeight: 600, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.375rem' }}>
                Prompt (EN)
              </p>
              <div style={{
                backgroundColor: 'var(--bg1)', border: '1px solid var(--bd)',
                borderRadius: '5px', padding: '0.5rem 0.625rem',
                fontSize: '0.75rem', color: 'var(--t2)', lineHeight: 1.6,
                maxHeight: '140px', overflowY: 'auto',
                fontFamily: 'monospace',
              }}>
                {item.prompt}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
