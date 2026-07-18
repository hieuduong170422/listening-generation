// Node 25 creates a broken `localStorage` global when --localstorage-file
// is passed without a valid path (Next.js 15 dev mode triggers this).
// This patch runs before any rendering and replaces the broken global.

export async function register() {
  const ls = (globalThis as Record<string, unknown>).localStorage as Record<string, unknown> | undefined
  const isBroken = ls !== undefined && typeof ls?.getItem !== 'function'
  if (isBroken) {
    const store = new Map<string, string>()
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      writable: true,
      value: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, val: string) => { store.set(key, val) },
        removeItem: (key: string) => { store.delete(key) },
        clear: () => { store.clear() },
        get length() { return store.size },
        key: (n: number) => [...store.keys()][n] ?? null,
      },
    })
  }
}
