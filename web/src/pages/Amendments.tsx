import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, History } from 'lucide-react'
import { useState } from 'react'
import { RuleTimeline } from '@/chat/blocks'
import { PageShell } from '@/layout/PageShell'
import { api } from '@/lib/api'
import { fmtDate, localToday, unquote } from '@/lib/plain'
import type { Source } from '@/lib/types'
import { Card, Kicker, Skeleton } from '@/ui/primitives'
import { SourceDialog, type ViewSource } from '@/ui/SourceDialog'
import { DateField } from './Conflicts'

export function AmendmentsPage() {
  const [asOf, setAsOf] = useState(localToday)
  const [view, setView] = useState<ViewSource | null>(null)
  const { data, isLoading } = useQuery({ queryKey: ['amendments', asOf], queryFn: () => api.amendments(asOf) })
  const toView = (s: Source): ViewSource => ({ doc_id: s.doc_id, doc_name: s.doc_name, clause_label: s.clause_label, page: s.page, pages: s.pages,
    bboxes: s.bboxes, page_width: s.page_width, page_height: s.page_height, ocr: s.ocr })

  return (
    <PageShell
      title="Amendments"
      subtitle="Rules that have been changed by later documents, and which version applies on a given date."
      actions={<DateField label="Rules as of" value={asOf} onChange={setAsOf} />}
    >
      {isLoading && <Skeleton className="h-64" />}
      {data && data.timelines.length === 0 && (
        <div className="rounded-2xl border border-line bg-surface px-6 py-10 text-center">
          <History className="mx-auto mb-2 h-7 w-7 text-muted" />
          <p className="font-medium">No rule has been amended</p>
          <p className="text-sm text-muted">When an amendment is uploaded, the history of the rule it changes appears here.</p>
        </div>
      )}
      <div className="space-y-6">
        {data?.timelines.map((t) => (
          <div key={t.version_key} className="space-y-3">
            <RuleTimeline
              chain={t}
              asOf={asOf}
              title="How this rule changed"
              onOpen={(id) => { const s = t.steps.find((x) => x.span_id === id)?.source; if (s) setView(toView(s)) }}
            />
            <Card className="border-ok/30 p-4">
              <Kicker>{`Wording that applies on ${fmtDate(asOf)}`}</Kicker>
              {t.current ? (
                <>
                  <p className="mt-1 text-sm text-muted">From {t.current.doc_name}</p>
                  <blockquote className="mt-2 border-l-2 border-ok pl-3">{unquote(t.current.text)}</blockquote>
                </>
              ) : <p className="mt-1 text-sm text-muted">No version of this rule applies on that date (it has not started yet, or it was removed).</p>}
            </Card>
          </div>
        ))}
      </div>
      {data && data.unresolved.length > 0 && (
        <div className="mt-8 space-y-2">
          <Kicker>Amendments pointing at missing documents</Kicker>
          {data.unresolved.map((u) => (
            <div key={`${u.doc_id}-${u.target}`} className="flex items-start gap-3 rounded-xl bg-warn-soft px-4 py-3 text-sm text-warn">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> A document you uploaded changes “{u.target}”, which is not in your library yet.
            </div>
          ))}
        </div>
      )}
      <SourceDialog source={view} onClose={() => setView(null)} />
    </PageShell>
  )
}
