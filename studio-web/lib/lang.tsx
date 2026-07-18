'use client'

import { createContext, useContext, useState, type ReactNode } from 'react'

export type Lang = 'vi' | 'en'

export type T = {
  studioTitle: string
  studio: string
  history: string
  signOut: string
  langLabel: string
  topic: string
  topicPlaceholder: string
  suggestTopics: string
  suggesting: string
  language: string
  style: string
  audience: string
  tone: string
  parts: string
  minPerPart: string
  speakers: string
  solo: string
  duo: string
  speakerNamePlaceholder: string
  selectVoice: string
  loadingVoices: string
  generateOutline: string
  regenerateOutline: string
  generatingOutline: string
  showName: string
  showNamePlaceholder: string
  channel: string
  channelPlaceholder: string
  continuousNarrative: string
  textModel: string
  elevenlabsModel: string
  ttsVoice: string
  stability: string
  similarity: string
  styleExagg: string
  speed: string
  speakerBoost: string
  scriptsBadge: string
  audioBadge: string
  scriptLabel: string
  chars: string
  genScript: string
  regenScript: string
  renderAudio: string
  reRender: string
  writing: string
  rendering: string
  keyPoints: string
  loadingAudio: string
  scriptPlaceholder: string
  writingPlaceholder: string
  partsLabel: string
  minLabel: string
  noOutlineYet: string
  noOutlineHint: string
  generateLink: string
  quotaTitle: string
  noHistory: string
  loading: string
}

const vi: T = {
  studioTitle: 'Podcast Studio',
  studio: 'Studio',
  history: 'Lịch sử',
  signOut: 'Đăng xuất',
  langLabel: 'EN',
  topic: 'Chủ đề',
  topicPlaceholder: 'Tập này nói về chủ đề gì?',
  suggestTopics: '✦ Gợi ý chủ đề',
  suggesting: 'Đang gợi ý…',
  language: 'Ngôn ngữ',
  style: 'Phong cách',
  audience: 'Khán giả',
  tone: 'Giọng điệu',
  parts: 'Số phần',
  minPerPart: 'Phút / phần',
  speakers: 'Người dẫn',
  solo: 'Đơn',
  duo: 'Đôi',
  speakerNamePlaceholder: 'Tên người dẫn',
  selectVoice: '— Chọn giọng —',
  loadingVoices: 'Đang tải giọng…',
  generateOutline: 'Tạo dàn ý',
  regenerateOutline: 'Tạo lại dàn ý',
  generatingOutline: 'Đang tạo…',
  showName: 'Tên chương trình',
  showNamePlaceholder: 'Podcast của tôi',
  channel: 'Kênh',
  channelPlaceholder: '@kenhcuatoi',
  continuousNarrative: 'Liên tục (không ngắt)',
  textModel: 'Mô hình AI',
  elevenlabsModel: 'Mô hình ElevenLabs',
  ttsVoice: 'Giọng TTS',
  stability: 'Ổn định',
  similarity: 'Tương đồng',
  styleExagg: 'Cá tính',
  speed: 'Tốc độ',
  speakerBoost: 'Tăng cường giọng',
  scriptsBadge: 'script',
  audioBadge: 'audio',
  scriptLabel: 'Script',
  chars: 'ký tự',
  genScript: '✍ Tạo script',
  regenScript: '↺ Tạo lại',
  renderAudio: '▶ Tạo audio',
  reRender: '↺ Tạo lại',
  writing: 'Đang viết…',
  rendering: 'Đang tạo…',
  keyPoints: 'Điểm chính',
  loadingAudio: 'Đang tải audio…',
  scriptPlaceholder: 'Nhấn "Tạo script" hoặc tự gõ vào đây.',
  writingPlaceholder: 'Đang viết script…',
  partsLabel: 'phần',
  minLabel: 'phút',
  noOutlineYet: 'Chưa có dàn ý',
  noOutlineHint: 'Nhập chủ đề bên trái và nhấn',
  generateLink: 'Tạo dàn ý',
  quotaTitle: 'Hạn mức ElevenLabs',
  noHistory: 'Chưa có lịch sử',
  loading: 'Đang tải…',
}

const en: T = {
  studioTitle: 'Podcast Studio',
  studio: 'Studio',
  history: 'History',
  signOut: 'Sign out',
  langLabel: 'VI',
  topic: 'Topic',
  topicPlaceholder: 'What is this episode about?',
  suggestTopics: '✦ Suggest topics',
  suggesting: 'Suggesting…',
  language: 'Language',
  style: 'Style',
  audience: 'Audience',
  tone: 'Tone',
  parts: 'Parts',
  minPerPart: 'Min / part',
  speakers: 'Speakers',
  solo: 'Solo',
  duo: 'Duo',
  speakerNamePlaceholder: 'Speaker name',
  selectVoice: '— Select voice —',
  loadingVoices: 'Loading voices…',
  generateOutline: 'Generate outline',
  regenerateOutline: 'Regenerate outline',
  generatingOutline: 'Generating…',
  showName: 'Show name',
  showNamePlaceholder: 'My Podcast',
  channel: 'Channel',
  channelPlaceholder: '@mychannel',
  continuousNarrative: 'Continuous narrative',
  textModel: 'Text model',
  elevenlabsModel: 'ElevenLabs model',
  ttsVoice: 'TTS voice',
  stability: 'Stability',
  similarity: 'Similarity',
  styleExagg: 'Style exagg.',
  speed: 'Speed',
  speakerBoost: 'Speaker boost',
  scriptsBadge: 'scripts',
  audioBadge: 'audio',
  scriptLabel: 'Script',
  chars: 'chars',
  genScript: '✍ Gen script',
  regenScript: '↺ Regen script',
  renderAudio: '▶ Render audio',
  reRender: '↺ Re-render',
  writing: 'Writing…',
  rendering: 'Rendering…',
  keyPoints: 'Key points',
  loadingAudio: 'Loading audio…',
  scriptPlaceholder: 'Click "Gen script" or type directly.',
  writingPlaceholder: 'Writing script…',
  partsLabel: 'parts',
  minLabel: 'min',
  noOutlineYet: 'No outline yet',
  noOutlineHint: 'Enter a topic on the left and click',
  generateLink: 'Generate outline',
  quotaTitle: 'ElevenLabs Quota',
  noHistory: 'No history yet',
  loading: 'Loading…',
}

const translations: Record<Lang, T> = { vi, en }

interface LangCtx {
  lang: Lang
  t: T
  toggleLang: () => void
}

const LangContext = createContext<LangCtx>({ lang: 'vi', t: vi, toggleLang: () => {} })

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>('vi')
  const toggleLang = () => setLang((l) => (l === 'vi' ? 'en' : 'vi'))
  return (
    <LangContext.Provider value={{ lang, t: translations[lang], toggleLang }}>
      {children}
    </LangContext.Provider>
  )
}

export function useLang() {
  return useContext(LangContext)
}
