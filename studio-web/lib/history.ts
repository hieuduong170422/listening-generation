import type { Outline, StudioConfig } from './types'

// ── Outline history (localStorage, giữ 7 ngày) ────────────────────────────────

export interface OutlineHistoryEntry {
  id: string
  createdAt: number
  updatedAt: number
  config: StudioConfig
  outline: Outline
  scripts: Record<number, string>
  audioIds: Record<number, string>
}

const STORAGE_KEY = 'studio-outline-history-v1'
const RETENTION_MS = 7 * 24 * 60 * 60 * 1000
const MAX_ENTRIES = 50

function isValidEntry(e: unknown): e is OutlineHistoryEntry {
  if (!e || typeof e !== 'object') return false
  const entry = e as Partial<OutlineHistoryEntry>
  return (
    typeof entry.id === 'string' &&
    typeof entry.createdAt === 'number' &&
    typeof entry.updatedAt === 'number' &&
    Boolean(entry.outline) &&
    Array.isArray(entry.outline?.parts)
  )
}

function prune(entries: OutlineHistoryEntry[]): OutlineHistoryEntry[] {
  const cutoff = Date.now() - RETENTION_MS
  return entries.filter((e) => e.updatedAt >= cutoff).slice(0, MAX_ENTRIES)
}

function save(entries: OutlineHistoryEntry[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries))
  } catch {
    // Quota đầy — bỏ entry cũ nhất rồi thử lại 1 lần
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(0, 10)))
    } catch { /* private mode — bỏ qua */ }
  }
}

export function loadOutlineHistory(): OutlineHistoryEntry[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const data = JSON.parse(raw)
    if (!Array.isArray(data)) return []
    const entries = prune(data.filter(isValidEntry))
    save(entries)
    return entries
  } catch {
    return []
  }
}

/** Thêm mới hoặc cập nhật entry theo id; entry mới nhất lên đầu. */
export function upsertOutlineEntry(
  entry: Omit<OutlineHistoryEntry, 'createdAt' | 'updatedAt'>,
): void {
  const now = Date.now()
  const existing = loadOutlineHistory()
  const prev = existing.find((e) => e.id === entry.id)
  const updated: OutlineHistoryEntry = {
    ...entry,
    createdAt: prev?.createdAt ?? now,
    updatedAt: now,
  }
  const rest = existing.filter((e) => e.id !== entry.id)
  save(prune([updated, ...rest]))
}

export function removeOutlineEntry(id: string): void {
  save(loadOutlineHistory().filter((e) => e.id !== id))
}
