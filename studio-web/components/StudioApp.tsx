'use client'

import { useEffect, useRef, useState } from 'react'
import { clearToken } from '@/lib/api'
import { clearStudioState } from '@/lib/storage'
import { useStudio } from '@/lib/store'
import { useLang } from '@/lib/lang'
import ConfigRail from './ConfigRail'
import SettingsRail from './SettingsRail'
import PartList from './PartList'
import HistoryPanel from './HistoryPanel'

type Tab = 'studio' | 'history'

const TOOLS = [
  { icon: '🧩', label: 'Prompt Template', href: '/templates' },
  { icon: '📊', label: 'Kalodata', href: '/kalodata-products' },
  { icon: '🎬', label: 'Video Affiliate', href: '/affiliate' },
  { icon: '🛡️', label: 'Admin', href: '/admin' },
]

function ToolsMenu({ label }: { label: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          padding: '0.3125rem 0.6875rem',
          backgroundColor: open ? 'var(--bg3)' : 'transparent',
          border: `1px solid ${open ? 'var(--bd)' : 'transparent'}`,
          borderRadius: '5px',
          color: open ? 'var(--t1)' : 'var(--t2)',
          fontSize: '0.8125rem',
          fontWeight: open ? 600 : 400,
          cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: '0.25rem',
          transition: 'color 0.15s',
        }}
      >
        {label}
        <span style={{
          fontSize: '0.625rem', color: 'var(--t3)',
          transform: open ? 'rotate(180deg)' : 'none',
          transition: 'transform 0.15s',
          display: 'inline-block',
        }}>▾</span>
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 6px)', left: 0,
          backgroundColor: 'var(--bg2)',
          border: '1px solid var(--bd)',
          borderRadius: '7px',
          boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
          minWidth: '200px',
          zIndex: 100,
          overflow: 'hidden',
          padding: '0.25rem',
        }}>
          {TOOLS.map((tool) => (
            <a
              key={tool.href}
              href={tool.href}
              onClick={() => setOpen(false)}
              style={{
                display: 'flex', alignItems: 'center', gap: '0.625rem',
                padding: '0.5rem 0.75rem',
                borderRadius: '5px',
                color: 'var(--t1)',
                fontSize: '0.8125rem',
                textDecoration: 'none',
                transition: 'background-color 0.1s',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'var(--bg3)' }}
              onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent' }}
            >
              <span style={{ fontSize: '1rem', width: '20px', textAlign: 'center' }}>{tool.icon}</span>
              <span>{tool.label}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

export default function StudioApp() {
  const { state } = useStudio()
  const { t, toggleLang } = useLang()
  const [tab, setTab] = useState<Tab>('studio')

  function handleLogout() {
    clearToken()
    clearStudioState()
    // Full reload để wipe cả state trong bộ nhớ; lịch sử server-side vẫn giữ
    window.location.href = '/login'
  }

  const hasOutline = Boolean(state.outline)

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--bg0)', overflow: 'hidden' }}>
      {/* Top bar */}
      <header style={{
        height: '50px', backgroundColor: 'var(--bg1)',
        borderBottom: '1px solid var(--bd)',
        display: 'flex', alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 1rem', flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
          <span style={{ fontWeight: 700, color: 'var(--t1)', letterSpacing: '-0.01em', fontSize: '0.9375rem' }}>
            {t.studioTitle}
          </span>
          <nav style={{ display: 'flex', gap: '0.25rem' }}>
            {(['studio', 'history'] as Tab[]).map((tabKey) => {
              const label = tabKey === 'studio' ? t.studio : t.history
              return (
                <button
                  key={tabKey}
                  onClick={() => setTab(tabKey)}
                  style={{
                    padding: '0.3125rem 0.6875rem',
                    backgroundColor: tab === tabKey ? 'var(--bg3)' : 'transparent',
                    border: `1px solid ${tab === tabKey ? 'var(--bd)' : 'transparent'}`,
                    borderRadius: '5px',
                    color: tab === tabKey ? 'var(--t1)' : 'var(--t2)',
                    fontSize: '0.8125rem',
                    fontWeight: tab === tabKey ? 600 : 400,
                    cursor: 'pointer',
                    transition: 'color 0.15s',
                  }}
                >
                  {label}
                </button>
              )
            })}
          </nav>

          <ToolsMenu label={t.tools} />

          <a
            href="/affiliate"
            style={{
              padding: '0.3125rem 0.6875rem',
              backgroundColor: 'var(--amber-m)',
              border: '1px solid var(--amber)',
              borderRadius: '5px',
              color: 'var(--amber)',
              fontSize: '0.8125rem',
              fontWeight: 600,
              textDecoration: 'none',
              display: 'flex', alignItems: 'center', gap: '0.3rem',
            }}
          >
            🎬 Affiliate
          </a>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          {/* EN/VI toggle */}
          <button
            onClick={toggleLang}
            style={{
              padding: '0.25rem 0.5rem',
              backgroundColor: 'var(--bg3)',
              border: '1px solid var(--bd)',
              borderRadius: '4px',
              color: 'var(--t2)',
              fontSize: '0.75rem',
              fontWeight: 600,
              cursor: 'pointer',
              letterSpacing: '0.03em',
            }}
            title="Switch language"
          >
            {t.langLabel}
          </button>

          <button
            onClick={handleLogout}
            style={{
              padding: '0.3125rem 0.6875rem',
              backgroundColor: 'transparent',
              border: '1px solid var(--bd)',
              borderRadius: '5px',
              color: 'var(--t2)',
              fontSize: '0.8125rem',
              cursor: 'pointer',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--t1)' }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--t2)' }}
          >
            {t.signOut}
          </button>
        </div>
      </header>

      {/* Body */}
      <main style={{ flex: 1, minHeight: 0, display: 'flex', overflow: 'hidden' }}>

        {/* ── Studio tab ── */}
        {tab === 'studio' && (
          <>
            <ConfigRail />
            <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', overflow: 'hidden' }}>
              {hasOutline ? <PartList /> : <EmptyState />}
            </div>
            <SettingsRail />
          </>
        )}

        {/* ── History tab ── */}
        {tab === 'history' && <HistoryPanel onOpenOutline={() => setTab('studio')} />}
      </main>
    </div>
  )
}

function EmptyState() {
  const { t } = useLang()
  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      color: 'var(--t3)', gap: '0.75rem', padding: '2rem',
    }}>
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
        <circle cx="24" cy="24" r="20" stroke="currentColor" strokeWidth="1.5" strokeDasharray="4 3" />
        <path d="M19 24a5 5 0 0 1 10 0v4a5 5 0 0 1-10 0v-4Z" stroke="currentColor" strokeWidth="1.5" />
        <path d="M16 28c0 4.418 3.582 8 8 8s8-3.582 8-8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <line x1="24" y1="36" x2="24" y2="40" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <div style={{ textAlign: 'center' }}>
        <p style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--t2)', marginBottom: '0.375rem' }}>
          {t.noOutlineYet}
        </p>
        <p style={{ fontSize: '0.8125rem', lineHeight: 1.6 }}>
          {t.noOutlineHint}<br />
          <strong style={{ color: 'var(--accent)' }}>{t.generateLink}</strong>
        </p>
      </div>
    </div>
  )
}
