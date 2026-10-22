/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        sre: {
          950: '#070a0f',
          900: '#0c121d',
          850: '#111927',
          800: '#172234',
          700: '#23334d',
          600: '#33486a',
          500: '#47638d',
          400: '#6f8ab2',
          300: '#9cb3d3',
          200: '#cddbf0',
          100: '#eef3fa',
        },
        severity: {
          critical: '#ef4444',
          error: '#f97316',
          warning: '#eab308',
          info: '#3b82f6',
          low: '#10b981',
        }
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Menlo', 'Monaco', 'Courier New', 'monospace'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      }
    },
  },
  plugins: [],
}
