'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { getToken } from '@/lib/api'
import AffiliateApp from '@/components/affiliate/AffiliateApp'

export default function AffiliatePage() {
  const router = useRouter()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login')
    } else {
      setReady(true)
    }
  }, [router])

  if (!ready) return null

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--bg0)' }}>
      {/* Header — same 50px style as Studio */}
      <header style={{
        height: '50px', backgroundColor: 'var(--bg1)',
        borderBottom: '1px solid var(--bd)',
        display: 'flex', alignItems: 'center',
        padding: '0 1rem', gap: '1rem', flexShrink: 0,
      }}>
        <a href="/" style={{
          padding: '0.3125rem 0.6875rem',
          backgroundColor: 'transparent', border: '1px solid transparent',
          borderRadius: '5px', color: 'var(--t2)', fontSize: '0.8125rem',
          textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '0.25rem',
          transition: 'color 0.15s',
        }}
          onMouseEnter={e => (e.currentTarget.style.color = 'var(--t1)')}
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--t2)')}
        >
          ← Studio
        </a>
        <span style={{ color: 'var(--bd)' }}>|</span>
        <span style={{ fontWeight: 700, color: 'var(--t1)', letterSpacing: '-0.01em', fontSize: '0.9375rem' }}>
          🎬 Video Affiliate
        </span>
      </header>

      {/* Body — flex 1, overflow hidden, same as Studio main */}
      <main style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <AffiliateApp />
      </main>
    </div>
  )
}
