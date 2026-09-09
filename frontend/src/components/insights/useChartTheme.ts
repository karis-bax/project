import { useEffect, useState } from 'react'

export interface ChartTheme {
  fg: string
  muted: string
  subtle: string
  grid: string
  accent: string
  accentWeak: string
  info: string
  warn: string
  panel: string
}

function read(): ChartTheme {
  const s = getComputedStyle(document.documentElement)
  const v = (name: string) => s.getPropertyValue(name).trim() || '#888'
  return {
    fg: v('--fg'),
    muted: v('--fg-muted'),
    subtle: v('--fg-subtle'),
    grid: v('--border'),
    accent: v('--accent'),
    accentWeak: v('--accent-weak'),
    info: v('--info'),
    warn: v('--warn'),
    panel: v('--panel-raised'),
  }
}

/** Read chart colors from the CSS custom properties, updating with the theme. */
export function useChartTheme(): ChartTheme {
  const [theme, setTheme] = useState<ChartTheme>(read)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setTheme(read())
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return theme
}
