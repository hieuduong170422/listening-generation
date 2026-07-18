'use client'

import { useState, type FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { login, setToken } from '@/lib/api'

export default function LoginPage() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!username.trim() || !password) return

    setError(null)
    setLoading(true)

    try {
      const res = await login(username.trim(), password)
      setToken(res.token)
      router.replace('/')
    } catch (err) {
      const message =
        err instanceof Error ? err.message : 'Login failed. Please try again.'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'var(--bg0)',
        padding: '1rem',
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '400px',
          backgroundColor: 'var(--bg1)',
          border: '1px solid var(--bd)',
          borderRadius: '12px',
          padding: '2rem',
        }}
      >
        {/* Header */}
        <div style={{ marginBottom: '2rem', textAlign: 'center' }}>
          <h1
            style={{
              fontSize: '1.5rem',
              fontWeight: 700,
              color: 'var(--t1)',
              marginBottom: '0.25rem',
            }}
          >
            Podcast Studio
          </h1>
          <p style={{ color: 'var(--t2)', fontSize: '0.875rem' }}>
            Sign in to continue
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
            <label
              htmlFor="username"
              style={{ fontSize: '0.8125rem', color: 'var(--t2)', fontWeight: 500 }}
            >
              Username
            </label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              disabled={loading}
              style={{
                padding: '0.625rem 0.75rem',
                backgroundColor: 'var(--bg2)',
                border: '1px solid var(--bd)',
                borderRadius: '6px',
                color: 'var(--t1)',
                fontSize: '0.875rem',
                outline: 'none',
                transition: 'border-color 0.15s',
              }}
              onFocus={(e) => {
                e.currentTarget.style.borderColor = 'var(--accent)'
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = 'var(--bd)'
              }}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
            <label
              htmlFor="password"
              style={{ fontSize: '0.8125rem', color: 'var(--t2)', fontWeight: 500 }}
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={loading}
              style={{
                padding: '0.625rem 0.75rem',
                backgroundColor: 'var(--bg2)',
                border: '1px solid var(--bd)',
                borderRadius: '6px',
                color: 'var(--t1)',
                fontSize: '0.875rem',
                outline: 'none',
                transition: 'border-color 0.15s',
              }}
              onFocus={(e) => {
                e.currentTarget.style.borderColor = 'var(--accent)'
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = 'var(--bd)'
              }}
            />
          </div>

          {/* Error message */}
          {error && (
            <p
              role="alert"
              style={{
                fontSize: '0.8125rem',
                color: '#E5534B',
                backgroundColor: 'rgba(229, 83, 75, 0.1)',
                border: '1px solid rgba(229, 83, 75, 0.25)',
                borderRadius: '6px',
                padding: '0.5rem 0.75rem',
              }}
            >
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading || !username.trim() || !password}
            style={{
              marginTop: '0.5rem',
              padding: '0.625rem 1rem',
              backgroundColor: loading || !username.trim() || !password
                ? 'var(--bg3)'
                : 'var(--accent)',
              color: loading || !username.trim() || !password
                ? 'var(--t3)'
                : '#fff',
              border: 'none',
              borderRadius: '6px',
              fontSize: '0.875rem',
              fontWeight: 600,
              cursor: loading || !username.trim() || !password ? 'not-allowed' : 'pointer',
              transition: 'background-color 0.15s',
            }}
            onMouseEnter={(e) => {
              if (!loading && username.trim() && password) {
                e.currentTarget.style.backgroundColor = 'var(--accent-h)'
              }
            }}
            onMouseLeave={(e) => {
              if (!loading && username.trim() && password) {
                e.currentTarget.style.backgroundColor = 'var(--accent)'
              }
            }}
          >
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
      </div>
    </main>
  )
}
