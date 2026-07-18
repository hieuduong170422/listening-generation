/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  // Proxy /api/* → FastAPI at runtime; API_TARGET_URL is a server-side env var
  // so it is NOT baked at build time (unlike NEXT_PUBLIC_*).
  // Dev: set API_TARGET_URL=http://localhost:8000 in .env.local
  // Prod (Docker): set API_TARGET_URL=http://podcast-api:8000 in compose
  async rewrites() {
    const target = process.env.API_TARGET_URL ?? 'http://localhost:8000'
    return [
      {
        source: '/api/:path*',
        destination: `${target}/api/:path*`,
      },
    ]
  },
}
export default nextConfig
