import type { Config } from 'tailwindcss'

const config: Config = {
  darkMode: 'class',
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        chassis: '#121417',
        surface: '#1A1D23',
        'surface-raised': '#262B34',
        'border-subtle': 'rgba(255, 255, 255, 0.08)',
        'border-strong': 'rgba(255, 255, 255, 0.16)',
        accent: '#E58E26',
        'accent-muted': 'rgba(229, 142, 38, 0.15)',
        'accent-glow': 'rgba(229, 142, 38, 0.15)',
        'status-ok': '#10B981',
        'status-active': '#10B981',
        'status-warn': '#F59E0B',
        'status-warning': '#F59E0B',
        'status-err': '#EF4444',
        'status-error': '#EF4444',
        // Backward-compatible teal palette
        teal: {
          50: '#F0FDFA',
          100: '#CCFBF1',
          200: '#99F6E4',
          300: '#5EEAD4',
          400: '#2DD4BF',
          500: '#14B8A6',
          600: '#0D7377',
          700: '#0F766E',
          800: '#115E59',
          900: '#134E4A',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'monospace'],
        sans: ['Plus Jakarta Sans', 'sans-serif'],
        display: ['Space Grotesk', 'sans-serif'],
      },
      borderRadius: {
        'sm': '4px',
        'md': '6px',
        'lg': '10px',
        '2xl': '16px',
        '3xl': '20px',
        'full': '9999px',
      },
      boxShadow: {
        'accent-glow': '0 4px 20px -3px rgba(229, 142, 38, 0.25)',
      },
    },
  },
  plugins: [],
}

export default config
