import type {
  LoginResponse,
  Voice,
  Subscription,
  HistoryItem,
  Outline,
  StudioConfig,
} from './types'
import { clearStudioState } from './storage'

const TOKEN_KEY = 'studio_token'

// ── Token management ──────────────────────────────────────────────────────────

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  try { return window.localStorage.getItem(TOKEN_KEY) } catch { return null }
}

export function setToken(token: string): void {
  if (typeof window === 'undefined') return
  try { window.localStorage.setItem(TOKEN_KEY, token) } catch { /* */ }
}

export function clearToken(): void {
  if (typeof window === 'undefined') return
  try { window.localStorage.removeItem(TOKEN_KEY) } catch { /* */ }
}

// ── Core fetch helper ─────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json()
    return (body as { detail?: string }).detail ?? res.statusText
  } catch {
    return res.statusText
  }
}

export async function authFetch(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(path, { ...options, headers })
  if (res.status === 401) {
    // Token hết hạn (TTL 2h) hoặc không hợp lệ → logout: xoá token + data phiên,
    // lịch sử server-side vẫn còn nguyên theo tài khoản.
    clearToken()
    clearStudioState()
    if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
      window.location.href = '/login'
    }
    throw new ApiError(res.status, await parseError(res))
  }
  if (!res.ok) {
    throw new ApiError(res.status, await parseError(res))
  }
  return res
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function login(
  username: string,
  password: string,
): Promise<LoginResponse> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new ApiError(res.status, await parseError(res))
  return res.json() as Promise<LoginResponse>
}

// ── Voices ────────────────────────────────────────────────────────────────────

export async function fetchVoices(): Promise<Voice[]> {
  const res = await authFetch('/api/elevenlabs/voices')
  const data = await res.json() as { voices: Voice[] }
  return data.voices
}

// ── Subscription ──────────────────────────────────────────────────────────────

export async function fetchSubscription(): Promise<Subscription> {
  const res = await authFetch('/api/elevenlabs/subscription')
  return res.json() as Promise<Subscription>
}

// ── History ───────────────────────────────────────────────────────────────────

export async function fetchHistory(
  pageSize = 50,
  voiceId?: string,
): Promise<HistoryItem[]> {
  const params = new URLSearchParams({ page_size: String(pageSize) })
  if (voiceId) params.set('voice_id', voiceId)
  const res = await authFetch(`/api/elevenlabs/history?${params}`)
  const data = await res.json() as { history: HistoryItem[] }
  return data.history
}

export function getHistoryAudioUrl(itemId: string): string {
  return `/api/elevenlabs/history/${itemId}/audio`
}

// ── Outline ───────────────────────────────────────────────────────────────────

export async function generateOutline(
  config: StudioConfig,
): Promise<{ outline: Outline }> {
  const body = {
    topic: config.topic,
    num_parts: config.num_parts,
    minutes_per_part: config.minutes_per_part,
    text_model: config.text_model,
    audience_level: config.audience_level,
    tone: config.tone,
    continuous: config.continuous,
    channel_name: config.channel_name,
    language: config.language,
  }
  const res = await authFetch('/api/podcast/outline', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return res.json() as Promise<{ outline: Outline }>
}

// ── Script ────────────────────────────────────────────────────────────────────

export async function generateScript(params: {
  config: StudioConfig
  outline: Outline
  partIndex: number
  previousScripts: Record<string, string>
  signal?: AbortSignal
}): Promise<{ text: string }> {
  const { config, outline, partIndex, previousScripts, signal } = params
  const body = {
    outline,
    part_index: partIndex,
    style: config.style,
    text_model: config.text_model,
    audience_level: config.audience_level,
    tone: config.tone,
    continuous: config.continuous,
    channel_name: config.channel_name,
    num_speakers: config.num_speakers,
    host_names: config.host_names,
    language: config.language,
    use_audio_tags: config.el_config.model_id.startsWith('eleven_v3'),
    previous_scripts: previousScripts,
  }
  const res = await authFetch('/api/podcast/script', {
    method: 'POST',
    body: JSON.stringify(body),
    signal,
  })
  return res.json() as Promise<{ text: string }>
}

// ── Audio render ──────────────────────────────────────────────────────────────

export async function renderAudio(params: {
  config: StudioConfig
  partIndex: number
  script: string
  signal?: AbortSignal
}): Promise<{ audio_id: string }> {
  const { config, partIndex, script, signal } = params
  const body = {
    part_index: partIndex,
    script_text: script,
    style: config.style,
    topic: config.topic,
    voices: config.host_voices.filter(Boolean),
    el_config: config.el_config,
  }
  const res = await authFetch('/api/podcast/audio', {
    method: 'POST',
    body: JSON.stringify(body),
    signal,
  })
  return res.json() as Promise<{ audio_id: string }>
}

export async function fetchAudioBlobUrl(audioId: string): Promise<string> {
  const res = await authFetch(`/api/podcast/audio/${audioId}`)
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

/** Tải audio của 1 part về máy dưới tên `baseName.<ext>` (ext theo content-type). */
export async function downloadAudioFile(audioId: string, baseName: string): Promise<void> {
  const res = await authFetch(`/api/podcast/audio/${audioId}`)
  const blob = await res.blob()
  const ext = blob.type.includes('mpeg') || blob.type.includes('mp3')
    ? '.mp3'
    : blob.type.includes('wav') ? '.wav' : '.audio'
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${baseName}${ext}`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

// ── Suggest topics ────────────────────────────────────────────────────────────

export async function suggestTopics(params: {
  topic?: string
  language?: string
  count?: number
  text_model?: string
  audience_level?: string
  tone?: string
}): Promise<{ suggestions: string[] }> {
  const body = {
    topic: params.topic ?? '',
    language: params.language ?? 'vi',
    count: params.count ?? 8,
    text_model: params.text_model ?? 'gemini-2.5-flash',
    audience_level: params.audience_level ?? 'intermediate',
    tone: params.tone ?? '',
  }
  const res = await authFetch('/api/topics/suggest', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return res.json() as Promise<{ suggestions: string[] }>
}
