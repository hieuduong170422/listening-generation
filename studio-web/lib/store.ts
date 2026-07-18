'use client'

import {
  createContext,
  useContext,
  useReducer,
  type ReactNode,
  type Dispatch,
} from 'react'
import type { Outline, StudioConfig } from './types'
import { DEFAULT_CONFIG } from './types'

// ── State ─────────────────────────────────────────────────────────────────────

export interface StudioState {
  config: StudioConfig
  outline: Outline | null
  scripts: Record<number, string>      // part_index → script text
  audioIds: Record<number, string>     // part_index → audio_id
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
  scripts: {},
  audioIds: {},
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
  | { type: 'SET_OUTLINE'; outline: Outline }
  | { type: 'SET_SCRIPT'; partIndex: number; text: string }
  | { type: 'SET_AUDIO_ID'; partIndex: number; audioId: string }
  | { type: 'SELECT_PART'; partIndex: number | null }
  | { type: 'SET_GENERATING_OUTLINE'; value: boolean }
  | { type: 'SET_GENERATING_SCRIPT'; partIndex: number | null }
  | { type: 'SET_RENDERING_AUDIO'; partIndex: number | null }
  | { type: 'SET_PROGRESS'; message: string | null }
  | { type: 'SET_ERROR'; message: string | null }
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
        scripts: {},
        audioIds: {},
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
