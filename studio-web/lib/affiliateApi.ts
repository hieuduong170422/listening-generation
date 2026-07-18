import { getToken } from './api'

const BASE = '/api/affiliate'

function authHeader(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function throwIfError(res: Response) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${res.status}`)
  }
  return res
}

// ── Job polling ──────────────────────────────────────────────────────────────

export interface JobState {
  type: string
  status: 'pending' | 'running' | 'done' | 'error'
  progress: number
  message: string
  result: Record<string, unknown> | null
  error: string | null
}

export async function pollJob(jobId: string): Promise<JobState> {
  const res = await fetch(`${BASE}/job/${jobId}`, { headers: authHeader() })
  await throwIfError(res)
  return res.json()
}

// ── Storyboard ───────────────────────────────────────────────────────────────

export interface StoryboardItem {
  index: number
  scenes: string[]
  prompt: string
  frames: number[]
  error: string | null
  has_image: boolean
  has_video: boolean
}

export interface StoryboardResult {
  session_id: string
  product: string
  items: StoryboardItem[]
}

export async function startStoryboard(params: {
  images: File[]
  idea: string
  directions: string
  clips: number
  beatsPerClip: number
}): Promise<{ job_id: string; session_id: string }> {
  const fd = new FormData()
  for (const img of params.images) fd.append('images', img)
  fd.append('idea', params.idea)
  fd.append('directions', params.directions)
  fd.append('clips', String(params.clips))
  fd.append('beats_per_clip', String(params.beatsPerClip))

  const res = await fetch(`${BASE}/storyboard`, {
    method: 'POST',
    headers: authHeader(),
    body: fd,
  })
  await throwIfError(res)
  return res.json()
}

// ── Clip ─────────────────────────────────────────────────────────────────────

export async function startClip(sessionId: string, clipIndex: number): Promise<{ job_id: string }> {
  const res = await fetch(`${BASE}/clip`, {
    method: 'POST',
    headers: { ...authHeader(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, clip_index: clipIndex }),
  })
  await throwIfError(res)
  return res.json()
}

// ── Stitch ───────────────────────────────────────────────────────────────────

export async function startStitch(sessionId: string): Promise<{ job_id: string }> {
  const res = await fetch(`${BASE}/stitch`, {
    method: 'POST',
    headers: { ...authHeader(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  })
  await throwIfError(res)
  return res.json()
}

// ── File helpers ─────────────────────────────────────────────────────────────

export function storyboardImageUrl(sessionId: string, index: number) {
  return `${BASE}/file/${sessionId}/storyboard/${index}`
}

export function clipVideoUrl(sessionId: string, index: number) {
  return `${BASE}/file/${sessionId}/clip/${index}`
}

export function finalVideoUrl(sessionId: string) {
  return `${BASE}/file/${sessionId}/final`
}

export function promptsUrl(sessionId: string) {
  return `${BASE}/file/${sessionId}/prompts`
}

/**
 * Fetch a protected file and return a blob URL (for <video> / <img> that can't
 * send custom headers).
 */
export async function fetchBlobUrl(url: string): Promise<string> {
  const res = await fetch(url, { headers: authHeader() })
  if (!res.ok) throw new Error(`Failed to load file: ${res.status}`)
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}
