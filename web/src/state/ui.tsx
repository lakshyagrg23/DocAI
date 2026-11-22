import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Answer } from '@/lib/types'

/** Persisted UI preferences (sidebar, theme) and the state of the right-hand Sources panel. */

type Theme = 'light' | 'dark'
export type PanelTab = 'sources' | 'page' | 'checks'

interface PanelState {
  open: boolean
  tab: PanelTab
  answer: Answer | null
  selected: string | null
  page: number | null
}

interface UiContext {
  sidebarOpen: boolean
  toggleSidebar: () => void
  setSidebarOpen: (v: boolean) => void
  theme: Theme
  toggleTheme: () => void
  panel: PanelState
  openSource: (answer: Answer, spanId: string) => void
  openTab: (answer: Answer, tab: PanelTab) => void
  setTab: (tab: PanelTab) => void
  setPage: (page: number | null) => void
  closePanel: () => void
}

const Ctx = createContext<UiContext | null>(null)

function read<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    return v === null ? fallback : (JSON.parse(v) as T)
  } catch {
    return fallback
  }
}
const write = (key: string, value: unknown) => {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* private mode */ }
}

export function UiProvider({ children }: { children: ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() => read('docai.sidebar', window.innerWidth >= 900))
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.classList.contains('dark') ? 'dark' : 'light'))
  const [panel, setPanel] = useState<PanelState>({ open: false, tab: 'sources', answer: null, selected: null, page: null })

  useEffect(() => { write('docai.sidebar', sidebarOpen) }, [sidebarOpen])
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    try { localStorage.setItem('docai.theme', theme) } catch { /* private mode */ }
  }, [theme])

  const openSource = useCallback((answer: Answer, spanId: string) =>
    setPanel({ open: true, tab: 'page', answer, selected: spanId, page: null }), [])
  const openTab = useCallback((answer: Answer, tab: PanelTab) =>
    setPanel((p) => ({ open: true, tab, answer, selected: p.answer === answer ? p.selected : answer.citations[0] ?? null, page: null })), [])
  const closePanel = useCallback(() => setPanel((p) => ({ ...p, open: false })), [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closePanel() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [closePanel])

  const value = useMemo<UiContext>(() => ({
    sidebarOpen,
    toggleSidebar: () => setSidebarOpen((v) => !v),
    setSidebarOpen,
    theme,
    toggleTheme: () => setTheme((t) => (t === 'dark' ? 'light' : 'dark')),
    panel,
    openSource,
    openTab,
    setTab: (tab) => setPanel((p) => ({ ...p, tab })),
    setPage: (page) => setPanel((p) => ({ ...p, page })),
    closePanel,
  }), [sidebarOpen, theme, panel, openSource, openTab, closePanel])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useUi(): UiContext {
  const v = useContext(Ctx)
  if (!v) throw new Error('useUi must be used inside <UiProvider>')
  return v
}
