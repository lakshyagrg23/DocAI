import { useQuery } from '@tanstack/react-query'
import { CalendarDays, CheckCircle2 } from 'lucide-react'
import { useState } from 'react'
import { DisagreementBlock } from '@/chat/blocks'
import { PageShell } from '@/layout/PageShell'
import { api } from '@/lib/api'
import { fmtDate, localToday } from '@/lib/plain'
import type { DisagreementSide } from '@/lib/types'
import { useWorkspaceId } from '@/state/workspace'
import { Skeleton } from '@/ui/primitives'
import { SourceDialog, type ViewSource } from '@/ui/SourceDialog'

export function DateField({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <label className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm shadow-card">
      <CalendarDays className="h-4 w-4 text-muted" aria-hidden />
      <span className="text-muted">{label}</span>
      <input type="date" value={value} onChange={(e) => e.target.value && onChange(e.target.value)} className="bg-transparent font-medium outline-none" />
    </label>
  )
}

export function ConflictsPage() {
  const wid = useWorkspaceId()
  const [asOf, setAsOf] = useState(localToday)
  const [view, setView] = useState<ViewSource | null>(null)
  const { data, isLoading } = useQuery({ queryKey: ['conflicts', wid, asOf], queryFn: () => api.conflicts(wid, asOf) })

  const open = (side: DisagreementSide & { pages?: number | null; bboxes?: number[][]; page_width?: number | null; page_height?: number | null }) =>
    setView({ doc_id: side.doc, doc_name: side.doc_name ?? side.doc_title ?? side.doc, clause_label: side.clause_label ?? side.clause_id, page: side.page ?? 1,
      pages: side.pages ?? null, bboxes: side.bboxes ?? [], page_width: side.page_width ?? null, page_height: side.page_height ?? null, ocr: side.ocr })

  return (
    <PageShell
      title="Conflicts"
      subtitle="Places where the documents in this workspace give different answers to the same question. Only rules that apply on the chosen date are compared."
      actions={<DateField label="Rules as of" value={asOf} onChange={setAsOf} />}
    >
      {isLoading && <Skeleton className="h-48" />}
      {data && data.cards.length === 0 && (
        <div className="rounded-2xl border border-line bg-surface px-6 py-10 text-center">
          <CheckCircle2 className="mx-auto mb-2 h-7 w-7 text-ok" />
          <p className="font-medium">No disagreements on {fmtDate(asOf)}</p>
          <p className="text-sm text-muted">Nothing in your documents contradicts anything else for this date.</p>
        </div>
      )}
      <div className="space-y-6">
        {data?.cards.map((card) => (
          <DisagreementBlock key={card.conflict_id} card={card} onOpen={(id) => { const s = card.sides.find((x) => x.span_id === id); if (s) open(s) }} />
        ))}
      </div>
      <SourceDialog source={view} onClose={() => setView(null)} />
    </PageShell>
  )
}
