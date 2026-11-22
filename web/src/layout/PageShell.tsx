import { PanelLeftOpen } from 'lucide-react'
import type { ReactNode } from 'react'
import { useUi } from '@/state/ui'
import { Button } from '@/ui/primitives'

/** Common frame for the Documents / Conflicts / Amendments pages. */
export function PageShell({ title, subtitle, actions, children }: { title: string; subtitle?: string; actions?: ReactNode; children: ReactNode }) {
  const { sidebarOpen, setSidebarOpen } = useUi()
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl px-4 py-8">
        <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-2">
            {!sidebarOpen && <Button size="icon" variant="ghost" onClick={() => setSidebarOpen(true)} aria-label="Open sidebar"><PanelLeftOpen className="h-5 w-5" /></Button>}
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
              {subtitle && <p className="mt-1 max-w-xl text-muted">{subtitle}</p>}
            </div>
          </div>
          {actions}
        </div>
        {children}
      </div>
    </div>
  )
}
