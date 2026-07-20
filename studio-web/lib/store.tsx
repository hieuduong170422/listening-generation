'use client'

import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  type ReactNode,
  type Dispatch,
} from 'react'
import type { Outline, StudioConfig } from './types'
import { DEFAULT_CONFIG } from './types'
import { upsertOutlineEntry, type OutlineHistoryEntry } from './history'

// ── Persistence (localStorage) ────────────────────────────────────────────────

import { STUDIO_STATE_KEY as STORAGE_KEY } from './storage'

const PERSIST_DEBOUNCE_MS = 300
const REMOTE_SYNC_DEBOUNCE_MS = 1200

interface PersistedState {
  config: StudioConfig
  outline: Outline | null
  outlineId: string | null
  scripts: Record<number, string>
  audioIds: Record<number, string>
  subtitles: Record<number, string>
  selectedPart: number | null
}

function loadPersisted(): PersistedState | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw) as Partial<PersistedState>
    if (!data || typeof data !== 'object') return null
    // Dàn ý phải có mảng parts hợp lệ, nếu không coi như dữ liệu hỏng
    if (data.outline && !Array.isArray(data.outline.parts)) return null
    const savedConfig: Partial<StudioConfig> = data.config ?? {}
    return {
      config: {
        ...DEFAULT_CONFIG,
        ...savedConfig,
        // Kênh trống trong config cũ → quay về default (Audivy)
        channel_name: savedConfig.channel_name || DEFAULT_CONFIG.channel_name,
      },
      outline: data.outline ?? null,
      outlineId: typeof data.outlineId === 'string' ? data.outlineId : null,
      scripts: data.scripts ?? {},
      audioIds: data.audioIds ?? {},
      subtitles: data.subtitles ?? {},
      selectedPart: typeof data.selectedPart === 'number' ? data.selectedPart : null,
    }
  } catch {
    return null
  }
}

function savePersisted(state: StudioState): void {
  try {
    const data: PersistedState = {
      config: state.config,
      outline: state.outline,
      outlineId: state.outlineId,
      scripts: state.scripts,
      audioIds: state.audioIds,
      subtitles: state.subtitles,
      selectedPart: state.selectedPart,
    }
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  } catch {
    // Quota đầy / private mode — bỏ qua, app vẫn chạy bình thường
  }
}

// ── State ─────────────────────────────────────────────────────────────────────

export interface StudioState {
  config: StudioConfig
  outline: Outline | null
  outlineId: string | null             // id ổn định của dàn ý hiện tại (cho history)
  scripts: Record<number, string>      // part_index → script text
  audioIds: Record<number, string>     // part_index → audio_id
  subtitles: Record<number, string>    // part_index → nội dung .srt
  selectedPart: number | null
  isGeneratingOutline: boolean
  generatingScript: number | null      // which part index
  renderingAudio: number | null
  progress: string | null
  error: string | null
}

const initialState: StudioState = {
  config: DEFAULT_CONFIG,
  outline: null,
  outlineId: null,
  scripts: {},
  audioIds: {},
  subtitles: {},
  selectedPart: null,
  isGeneratingOutline: false,
  generatingScript: null,
  renderingAudio: null,
  progress: null,
  error: null,
}

// ── Actions ───────────────────────────────────────────────────────────────────

type Action =
  | { type: 'SET_CONFIG'; config: StudioConfig }
  | { type: 'PATCH_CONFIG'; patch: Partial<StudioConfig> }
  | { type: 'SET_OUTLINE'; outline: Outline; outlineId: string }
  | { type: 'LOAD_SNAPSHOT'; entry: OutlineHistoryEntry }
  | { type: 'SET_SCRIPT'; partIndex: number; text: string }
  | { type: 'SET_AUDIO_ID'; partIndex: number; audioId: string }
  | { type: 'SET_SUBTITLE'; partIndex: number; srt: string }
  | { type: 'SELECT_PART'; partIndex: number | null }
  | { type: 'SET_GENERATING_OUTLINE'; value: boolean }
  | { type: 'SET_GENERATING_SCRIPT'; partIndex: number | null }
  | { type: 'SET_RENDERING_AUDIO'; partIndex: number | null }
  | { type: 'SET_PROGRESS'; message: string | null }
  | { type: 'SET_ERROR'; message: string | null }
  | { type: 'HYDRATE'; payload: PersistedState }
  | { type: 'RESET' }

// ── Reducer ───────────────────────────────────────────────────────────────────

function reducer(state: StudioState, action: Action): StudioState {
  switch (action.type) {
    case 'SET_CONFIG':
      return { ...state, config: action.config }

    case 'PATCH_CONFIG':
      return { ...state, config: { ...state.config, ...action.patch } }

    case 'SET_OUTLINE':
      return {
        ...state,
        outline: action.outline,
        outlineId: action.outlineId,
        scripts: {},
        audioIds: {},
        subtitles: {},
        selectedPart: null,
        error: null,
      }

    case 'LOAD_SNAPSHOT':
      return {
        ...state,
        config: { ...DEFAULT_CONFIG, ...action.entry.config },
        outline: action.entry.outline,
        outlineId: action.entry.id,
        scripts: action.entry.scripts,
        audioIds: action.entry.audioIds,
        subtitles: action.entry.subtitles ?? {},
        selectedPart: null,
        error: null,
      }

    case 'SET_SCRIPT':
      return {
        ...state,
        scripts: { ...state.scripts, [action.partIndex]: action.text },
      }

    case 'SET_AUDIO_ID':
      return {
        ...state,
        audioIds: { ...state.audioIds, [action.partIndex]: action.audioId },
      }

    case 'SET_SUBTITLE':
      return {
        ...state,
        subtitles: { ...state.subtitles, [action.partIndex]: action.srt },
      }

    case 'SELECT_PART':
      return { ...state, selectedPart: action.partIndex }

    case 'SET_GENERATING_OUTLINE':
      return { ...state, isGeneratingOutline: action.value }

    case 'SET_GENERATING_SCRIPT':
      return { ...state, generatingScript: action.partIndex }

    case 'SET_RENDERING_AUDIO':
      return { ...state, renderingAudio: action.partIndex }

    case 'SET_PROGRESS':
      return { ...state, progress: action.message }

    case 'SET_ERROR':
      return { ...state, error: action.message }

    case 'HYDRATE':
      return { ...state, ...action.payload }

    case 'RESET':
      return { ...initialState }

    default:
      return state
  }
}

// ── Context ───────────────────────────────────────────────────────────────────

interface StudioContextValue {
  state: StudioState
  dispatch: Dispatch<Action>
}

const StudioContext = createContext<StudioContextValue | null>(null)

// ── Provider ──────────────────────────────────────────────────────────────────

export function StudioProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)

  // Khôi phục sau F5 — chạy sau mount để tránh SSR hydration mismatch
  useEffect(() => {
    const saved = loadPersisted()
    if (saved) dispatch({ type: 'HYDRATE', payload: saved })
  }, [])

  // Lưu localStorage mỗi khi dữ liệu chính đổi (debounce vì gõ script dispatch từng phím)
  useEffect(() => {
    const id = window.setTimeout(() => savePersisted(state), PERSIST_DEBOUNCE_MS)
    return () => window.clearTimeout(id)
  }, [state.config, state.outline, state.outlineId, state.scripts, state.audioIds, state.selectedPart])

  // Đồng bộ lịch sử dàn ý lên server (theo user, giữ 7 ngày) — fire-and-forget
  useEffect(() => {
    if (!state.outline || !state.outlineId) return
    const outline = state.outline
    const outlineId = state.outlineId
    const id = window.setTimeout(() => {
      upsertOutlineEntry({
        id: outlineId,
        config: state.config,
        outline,
        scripts: state.scripts,
        audioIds: state.audioIds,
        subtitles: state.subtitles,
      }).catch(() => { /* offline/hết phiên — lần đổi kế tiếp sẽ sync lại */ })
    }, REMOTE_SYNC_DEBOUNCE_MS)
    return () => window.clearTimeout(id)
  }, [state.config, state.outline, state.outlineId, state.scripts, state.audioIds, state.subtitles])

  return (
    <StudioContext.Provider value={{ state, dispatch }}>
      {children}
    </StudioContext.Provider>
  )
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useStudio(): StudioContextValue {
  const ctx = useContext(StudioContext)
  if (!ctx) throw new Error('useStudio must be used inside <StudioProvider>')
  return ctx
}
