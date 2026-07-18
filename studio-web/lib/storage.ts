export const STUDIO_STATE_KEY = 'studio-state-v1'
const LEGACY_HISTORY_KEY = 'studio-outline-history-v1'

/**
 * Xoá data phiên làm việc của user trên trình duyệt (config/dàn ý/script đang mở).
 * KHÔNG đụng tới lịch sử dàn ý — lịch sử nằm trên server theo tài khoản.
 */
export function clearStudioState(): void {
  try {
    window.localStorage.removeItem(STUDIO_STATE_KEY)
    window.localStorage.removeItem(LEGACY_HISTORY_KEY)
  } catch { /* private mode — bỏ qua */ }
}
