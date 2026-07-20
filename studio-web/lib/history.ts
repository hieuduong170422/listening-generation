import { authFetch } from './api'
import type { Outline, StudioConfig } from './types'

// ── Outline history (server-side theo user, giữ 7 ngày) ───────────────────────

export interface OutlineHistoryEntry {
  id: string
  username: string
  createdAt: number
  updatedAt: number
  config: StudioConfig
  outline: Outline
  scripts: Record<number, string>
  audioIds: Record<number, string>
  subtitles: Record<number, string>
}

interface ServerEntry {
  id: string
  username: string
  created_at: number
  updated_at: number
  config: StudioConfig
  outline: Outline
  scripts?: Record<number, string>
  audio_ids?: Record<number, string>
  subtitles?: Record<number, string>
}

function fromServer(e: ServerEntry): OutlineHistoryEntry {
  return {
    id: e.id,
    username: e.username,
    createdAt: e.created_at,
    updatedAt: e.updated_at,
    config: e.config,
    outline: e.outline,
    scripts: e.scripts ?? {},
    audioIds: e.audio_ids ?? {},
    subtitles: e.subtitles ?? {},
  }
}

export async function fetchOutlineHistory(): Promise<{
  entries: OutlineHistoryEntry[]
  isAdmin: boolean
}> {
  const res = await authFetch('/api/podcast/outlines')
  const data = await res.json() as { entries: ServerEntry[]; is_admin: boolean }
  const entries = (data.entries ?? [])
    .filter((e) => e && Array.isArray(e.outline?.parts))
    .map(fromServer)
  return { entries, isAdmin: Boolean(data.is_admin) }
}

export async function upsertOutlineEntry(
  entry: {
    id: string
    config: StudioConfig
    outline: Outline
    scripts: Record<number, string>
    audioIds: Record<number, string>
    subtitles: Record<number, string>
  },
  options: { keepalive?: boolean } = {},
): Promise<void> {
  await authFetch('/api/podcast/outlines', {
    method: 'POST',
    // keepalive: cho request sống sót khi tab đang đóng (flush lần cuối)
    keepalive: options.keepalive,
    body: JSON.stringify({
      id: entry.id,
      config: entry.config,
      outline: entry.outline,
      scripts: entry.scripts,
      audio_ids: entry.audioIds,
      subtitles: entry.subtitles,
    }),
  })
}

export async function removeOutlineEntry(id: string): Promise<void> {
  await authFetch(`/api/podcast/outlines/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
