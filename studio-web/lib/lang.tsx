'use client'

import { createContext, useContext, useState, type ReactNode } from 'react'

export type Lang = 'vi' | 'en'

export type T = {
  studioTitle: string
  studio: string
  history: string
  signOut: string
  langLabel: string
  tools: string
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
  genAllScripts: string
  cancelBtn: string
  writingPart: string
  batchFailedAt: string
  allScriptsDone: string
  downloadAll: string
  downloadOne: string
  downloadingAudio: string
  renderAllAudio: string
  renderingAudioPart: string
  allAudioDone: string
  selectVoiceFirst: string
  finishScriptsFirst: string
  outlineHistoryTitle: string
  outlineHistoryNote: string
  outlineHistoryEmpty: string
  colTopic: string
  colUser: string
  colDate: string
  colParts: string
  openBtn: string
  deleteBtn: string
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
  tools: 'Công cụ',
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
  channel: 'Tên kênh',
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
  genAllScripts: '⚡ Tạo tất cả script',
  cancelBtn: '✕ Huỷ',
  writingPart: 'Đang viết phần',
  batchFailedAt: 'Lỗi khi tạo phần',
  allScriptsDone: 'Đã có đủ script cho tất cả các phần',
  downloadAll: '⬇ Tải tất cả audio',
  downloadOne: '⬇ Tải audio',
  downloadingAudio: 'Đang tải…',
  renderAllAudio: '🔊 Tạo tất cả audio',
  renderingAudioPart: 'Đang tạo audio phần',
  allAudioDone: 'Các phần có script đều đã có audio',
  selectVoiceFirst: 'Chọn giọng TTS ở menu trái trước khi tạo audio',
  finishScriptsFirst: 'Hãy tạo xong script cho tất cả các phần trước khi tạo audio',
  outlineHistoryTitle: 'Dàn ý đã tạo (7 ngày gần nhất)',
  outlineHistoryNote: 'Lưu trên server theo tài khoản, tự xoá sau 7 ngày. Bấm vào chủ đề để xem các phần.',
  outlineHistoryEmpty: 'Chưa có dàn ý nào được lưu.',
  colTopic: 'Chủ đề',
  colUser: 'Người tạo',
  colDate: 'Cập nhật',
  colParts: 'Phần / Script / Audio',
  openBtn: 'Mở',
  deleteBtn: 'Xoá',
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
  tools: 'Tools',
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
  channel: 'Channel name',
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
  genAllScripts: '⚡ Gen all scripts',
  cancelBtn: '✕ Cancel',
  writingPart: 'Writing part',
  batchFailedAt: 'Failed at part',
  allScriptsDone: 'All parts already have scripts',
  downloadAll: '⬇ Download all audio',
  downloadOne: '⬇ Download audio',
  downloadingAudio: 'Downloading…',
  renderAllAudio: '🔊 Render all audio',
  renderingAudioPart: 'Rendering audio for part',
  allAudioDone: 'Every scripted part already has audio',
  selectVoiceFirst: 'Select a TTS voice in the left menu first',
  finishScriptsFirst: 'Finish generating scripts for every part before rendering audio',
  outlineHistoryTitle: 'Generated outlines (last 7 days)',
  outlineHistoryNote: 'Stored server-side per account, auto-deleted after 7 days. Click a topic to see its parts.',
  outlineHistoryEmpty: 'No saved outlines yet.',
  colTopic: 'Topic',
  colUser: 'Creator',
  colDate: 'Updated',
  colParts: 'Parts / Scripts / Audio',
  openBtn: 'Open',
  deleteBtn: 'Delete',
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
