'use client'

import { useState } from 'react'
import { clearToken } from '@/lib/api'
import { useRouter } from 'next/navigation'
import { useStudio } from '@/lib/store'
import ConfigRail from './ConfigRail'
import PartList from './PartList'
import HistoryPanel from './HistoryPanel'

type Tab = 'studio' | 'history'

export default function StudioApp() {
  const router = useRouter()
  const { state } = useStudio()
  const [tab, setTab] = useState<Tab>('studio')

  function handleLogout() {
    clearToken()
    router.replace('/login')
  }

  const hasOutline = Boolean(state.outline)

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--bg0)' }}>
      {/* Top bar */}
      <header style={{
        height: '50px', backgroundColor: 'var(--bg1)',
        borderBottom: '1px solid var(--bd)',
        display: 'flex', alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 1.25rem', flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
          <span style={{ fontWeight: 700, color: 'var(--t1)', letterSpacing: '-0.01em', fontSize: '0.9375rem' }}>
            Podcast Studio
          </span>

          {/* Tabs */}
          <nav style={{ display: 'flex', gap: '0.25rem' }}>
            {(['studio', 'history'] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                style={{
                  padding: '0.3125rem 0.75rem',
                  backgroundColor: tab === t ? 'var(--bg3)' : 'transparent',
                  border: `1px solid ${tab === t ? 'var(--bd)' : 'transparent'}`,
                  borderRadius: '5px',
                  color: tab === t ? 'var(--t1)' : 'var(--t2)',
                  fontSize: '0.8125rem',
                  fontWeight: tab === t ? 600 : 400,
                  cursor: 'pointer',
                  textTransform: 'capitalize',
                  transition: 'color 0.15s',
                }}
              >
                {t}
              </button>
            ))}
          </nav>
        </div>

        <button
          onClick={handleLogout}
          style={{
            padding: '0.3125rem 0.75rem',
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
          Sign out
        </button>
      </header>

      {/* Body */}
      <main style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* ── Studio tab ── */}
        {tab === 'studio' && (
          <>
            {/* Config rail */}
            <ConfigRail />

            {/* Content area */}
            <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
              {hasOutline ? <PartList /> : <EmptyState />}
            </div>
          </>
        )}

        {/* ── History tab ── */}
        {tab === 'history' && <HistoryPanel />}
      </main>
    </div>
  )
}

function EmptyState() {
  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      color: 'var(--t3)', gap: '0.75rem', padding: '2rem',
    }}>
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="24" cy="24" r="20" stroke="currentColor" strokeWidth="1.5" strokeDasharray="4 3" />
        <path d="M19 24a5 5 0 0 1 10 0v4a5 5 0 0 1-10 0v-4Z" stroke="currentColor" strokeWidth="1.5" />
        <path d="M16 28c0 4.418 3.582 8 8 8s8-3.582 8-8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <line x1="24" y1="36" x2="24" y2="40" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <div style={{ textAlign: 'center' }}>
        <p style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--t2)', marginBottom: '0.375rem' }}>
          No outline yet
        </p>
        <p style={{ fontSize: '0.8125rem', lineHeight: 1.6 }}>
          Enter a topic on the left and click<br />
          <strong style={{ color: 'var(--accent)' }}>Generate outline</strong> to start.
        </p>
      </div>
    </div>
  )
}
