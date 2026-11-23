/** Design tokens live as CSS variables in src/index.css (light + dark); Tailwind only references them. */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: { sans: ['"Inter Variable"', '"Noto Sans Devanagari"', '"Nirmala UI"', 'Mangal', 'ui-sans-serif', 'system-ui', 'sans-serif'] },
      colors: {
        bg: v('bg'), surface: v('surface'), sunken: v('sunken'), line: v('line'), ink: v('ink'), muted: v('muted'),
        accent: { DEFAULT: v('accent'), soft: v('accent-soft'), ink: v('accent-ink') },
        ok: { DEFAULT: v('ok'), soft: v('ok-soft') },
        warn: { DEFAULT: v('warn'), soft: v('warn-soft') },
        clash: { DEFAULT: v('clash'), soft: v('clash-soft') },
        calm: { DEFAULT: v('calm'), soft: v('calm-soft') },
        mark: v('mark'),
      },
      boxShadow: {
        card: '0 1px 2px rgb(0 0 0 / 0.04), 0 1px 1px rgb(0 0 0 / 0.03)',
        pop: '0 8px 24px rgb(0 0 0 / 0.12), 0 2px 6px rgb(0 0 0 / 0.08)',
      },
      keyframes: {
        'fade-in': { from: { opacity: '0', transform: 'translateY(4px)' }, to: { opacity: '1', transform: 'none' } },
        pulse2: { '0%,100%': { opacity: '1' }, '50%': { opacity: '.45' } },
      },
      animation: { 'fade-in': 'fade-in .25s ease-out both', pulse2: 'pulse2 1.4s ease-in-out infinite' },
    },
  },
  plugins: [],
}
