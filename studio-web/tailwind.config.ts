import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.tsx',
    './components/**/*.tsx',
    './lib/**/*.tsx',
  ],
  theme: {
    extend: {
      colors: {
        bg0: '#07090F',
        bg1: '#0D1020',
        bg2: '#13172A',
        bg3: '#1A1F35',
        bd: '#1F2540',
        'bd-s': '#151930',
        accent: '#6B5FE3',
        'accent-h': '#7D73EB',
        amber: '#C97A48',
        ok: '#3BAD75',
        t1: '#D5D9F0',
        t2: '#6A7299',
        t3: '#323854',
      },
    },
  },
  plugins: [],
}

export default config
