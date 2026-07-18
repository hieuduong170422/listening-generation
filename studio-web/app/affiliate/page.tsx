'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { getToken } from '@/lib/api'
import { LangProvider } from '@/lib/lang'
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
    <LangProvider>
      <div style={{ minHeight: '100vh', backgroundColor: 'var(--bg0)' }}>
        <header style={{
          height: '50px', backgroundColor: 'var(--bg1)',
          borderBottom: '1px solid var(--bd)',
          display: 'flex', alignItems: 'center',
          padding: '0 1rem', gap: '1rem',
          position: 'sticky', top: 0, zIndex: 50,
        }}>
          <a href="/" style={{
            fontSize: '0.8125rem', color: 'var(--t3)',
            textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '0.25rem',
          }}>
            ← Studio
          </a>
          <span style={{ color: 'var(--bd)' }}>|</span>
          <span style={{ fontWeight: 700, color: 'var(--t1)', fontSize: '0.9375rem' }}>
            🎬 Video Affiliate
          </span>
        </header>
        <AffiliateApp />
      </div>
    </LangProvider>
  )
}
