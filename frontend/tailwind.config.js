/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Landing page dark theme
        dark: {
          bg: '#0B0B10',
          card: '#12121A',
          border: 'rgba(255,255,255,0.06)',
          glow: '#6D28FF',
        },
        // Keep existing Slack-style colors for the app
        primary: {
          DEFAULT: '#4a154b',
          deep: '#3a103b',
          press: '#611f69',
          glow: '#7b2d85',
        },
        accent: {
          teal: '#00b4d8',
          coral: '#ff6b6b',
        },
        canvas: {
          DEFAULT: '#faf8f5',
          cream: '#f4ede4',
          lavender: '#f9f0ff',
          warm: '#faf8f5',
        },
        surface: {
          DEFAULT: '#ffffff',
          hover: '#f5f3f0',
          active: '#ede8f0',
          aubergine: '#4a154b',
        },
        ink: {
          DEFAULT: '#1d1d1d',
          mute: '#5c5c5c',
          faint: '#9ca3af',
        },
        hairline: {
          DEFAULT: '#e8e4df',
          strong: '#d4cfc7',
        },
        semantic: {
          error: '#cc4117',
          success: '#007a5a',
          warning: '#e8913a',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'SFMono-Regular', 'Consolas', 'monospace'],
      },
      borderRadius: {
        pill: '9999px',
      },
      boxShadow: {
        'glow-teal': '0 0 12px rgba(0, 180, 216, 0.25)',
        'glow-aubergine': '0 0 16px rgba(74, 21, 75, 0.2)',
        'glow-purple': '0 0 20px rgba(109, 40, 255, 0.3)',
        'card': '0 2px 8px rgba(0,0,0,0.06)',
        'card-lg': '0 4px 16px rgba(0,0,0,0.08)',
      },
      animation: {
        'pulse-glow': 'pulse-glow 2s ease-in-out infinite',
        'slide-up': 'slide-up 0.3s ease-out',
        'fade-in': 'fade-in 0.2s ease-out',
      },
      keyframes: {
        'pulse-glow': {
          '0%, 100%': { boxShadow: '0 0 4px rgba(109, 40, 255, 0.2)' },
          '50%': { boxShadow: '0 0 16px rgba(109, 40, 255, 0.4)' },
        },
        'slide-up': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
};
