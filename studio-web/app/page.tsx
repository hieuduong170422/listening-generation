'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { getToken } from '@/lib/api'
import { StudioProvider } from '@/lib/store'
import StudioApp from '@/components/StudioApp'

export default function HomePage() {
  const router = useRouter()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const token = getToken()
    if (!token) {
      router.replace('/login')
      return
    }
    setReady(true)
  }, [router])

  if (!ready) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: 'var(--bg0)',
          color: 'var(--t2)',
          fontSize: '0.875rem',
        }}
      >
        Loading...
      </div>
    )
  }

  return (
    <StudioProvider>
      <StudioApp />
    </StudioProvider>
  )
}
