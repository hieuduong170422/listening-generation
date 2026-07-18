import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Podcast Studio',
  description: 'AI-powered podcast production studio',
}

interface RootLayoutProps {
  children: React.ReactNode
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
