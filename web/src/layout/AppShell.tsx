import { Outlet } from 'react-router-dom'
import { SourcesPanel } from '@/panel/SourcesPanel'
import { useUi } from '@/state/ui'
import { Sidebar } from './Sidebar'

/** Sidebar | main | right panel. On narrow screens the sidebar and the panel become overlays. */
export function AppShell() {
  const { sidebarOpen, setSidebarOpen, panel, closePanel } = useUi()
  const narrow = typeof window !== 'undefined' && window.innerWidth < 900
  return (
    <div className="flex h-full overflow-hidden">
      {narrow && sidebarOpen ? (
        <>
          <div className="fixed inset-0 z-30 bg-black/40" onClick={() => setSidebarOpen(false)} aria-hidden />
          <div className="fixed inset-y-0 left-0 z-40 shadow-pop"><Sidebar /></div>
        </>
      ) : (
        <Sidebar />
      )}
      <main className="flex min-w-0 flex-1 flex-col"><Outlet /></main>
      {panel.open && narrow && <div className="fixed inset-0 z-30 bg-black/40" onClick={closePanel} aria-hidden />}
      <SourcesPanel />
    </div>
  )
}
