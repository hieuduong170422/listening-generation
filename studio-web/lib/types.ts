export interface PartBrief {
  index: number
  title: string
  summary: string
  key_points: string[]
}

export interface Outline {
  topic: string
  total_minutes: number
  parts: PartBrief[]
}

export interface Voice {
  voice_id: string
  name: string
  category: string
  labels: Record<string, string>
  preview_url: string
}

export interface ElConfig {
  model_id: string
  stability: number
  similarity_boost: number
  style: number
  speed: number
  use_speaker_boost: boolean
  output_format: string
}

export interface StudioConfig {
  topic: string
  language: string
  channel_name: string
  num_parts: number
  total_minutes: number
  minutes_per_part: number
  style: string
  audience_level: string
  tone: string
  continuous: boolean
  text_model: string
  num_speakers: number
  host_names: string[]
  host_voices: string[]
  el_config: ElConfig
}

export const DEFAULT_CONFIG: StudioConfig = {
  topic: '',
  language: 'vi',
  channel_name: '',
  num_parts: 3,
  total_minutes: 30,
  minutes_per_part: 10,
  style: 'podcast',
  audience_level: 'intermediate',
  tone: 'conversational',
  continuous: true,
  text_model: 'gemini-2.5-flash',
  num_speakers: 2,
  host_names: ['Nam', 'Linh'],
  host_voices: ['', ''],
  el_config: {
    model_id: 'eleven_flash_v2_5',
    stability: 0.5,
    similarity_boost: 0.75,
    style: 0.0,
    speed: 1.0,
    use_speaker_boost: true,
    output_format: 'mp3_44100_128',
  },
}

export interface HistoryItem {
  history_item_id: string
  voice_name: string
  text: string
  date_unix: number
  model_id: string
  character_count_change_from: number
  character_count_change_to: number
}

export interface Subscription {
  character_count: number
  character_limit: number
  tier: string
}

export interface LoginResponse {
  token: string
  username: string
  is_admin: boolean
}
