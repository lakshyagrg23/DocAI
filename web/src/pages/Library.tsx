import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, FileText, Loader2, ScanLine, UploadCloud } from 'lucide-react'
import { useRef, useState } from 'react'
import { PageShell } from '@/layout/PageShell'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { CLAUSE_STATUS_COPY, fmtDate, snippet } from '@/lib/plain'
import type { Doc } from '@/lib/types'
import { useWorkspace, useWorkspaceId } from '@/state/workspace'
import { Badge, Card, Skeleton } from '@/ui/primitives'
import { SourceDialog, type ViewSource } from '@/ui/SourceDialog'

function Outline({ doc, onView }: { doc: Doc; onView: (s: ViewSource) => void }) {
  const { data = [], isLoading } = useQuery({ queryKey: ['outline', doc.doc_id], queryFn: () => api.outline(doc.doc_id) })
  if (isLoading) return <div className="space-y-2 p-4"><Skeleton className="h-8" /><Skeleton className="h-8" /></div>
  return (
    <ul className="divide-y divide-line border-t border-line">
      {data.map((c) => {
        const st = CLAUSE_STATUS_COPY[c.status]
        return (
          <li key={c.clause_id} className="flex items-start gap-3 px-4 py-2.5">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{c.label} <span className="font-normal text-muted">· page {c.page}</span></p>
              <p className="text-sm text-muted">{snippet(c.text, 200)}</p>
              {c.status !== 'in_force' && <Badge tone={st.tone} className="mt-1">{c.replaced_by ? `${st.label} by a later amendment` : st.label}</Badge>}
            </div>
            <button
              className="shrink-0 text-xs font-medium text-accent-ink hover:underline"
              onClick={() => onView({ doc_id: doc.doc_id, doc_name: doc.name, clause_label: c.label, page: c.page, pages: doc.pages, bboxes: [], page_width: null, page_height: null })}
            >
              View page
            </button>
          </li>
        )
      })}
    </ul>
  )
}

function DocCard({ doc, onView }: { doc: Doc; onView: (s: ViewSource) => void }) {
  const [open, setOpen] = useState(false)
  const tone = doc.status === 'Ready' ? 'ok' : doc.status === 'Failed' ? 'clash' : doc.needs_ocr ? 'warn' : 'accent'
  const label = doc.needs_ocr ? 'Needs a scanned-page reader' : doc.status_label
  return (
    <Card className="overflow-hidden">
      <button className="flex w-full items-center gap-4 p-4 text-left" onClick={() => setOpen((o) => !o)} aria-expanded={open} disabled={!doc.clauses}>
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent-ink">{doc.ocr ? <ScanLine className="h-5 w-5" /> : <FileText className="h-5 w-5" />}</span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{doc.name}</p>
          <p className="truncate text-sm text-muted">{doc.sub || 'Document'}{doc.effective ? ` · effective ${fmtDate(doc.effective)}` : ''}</p>
        </div>
        <div className="hidden text-right text-xs text-muted sm:block">
          {doc.pages ? <p className="num">{doc.pages} {doc.pages === 1 ? 'page' : 'pages'}</p> : null}
          {doc.clauses ? <p className="num">{doc.clauses} sections</p> : null}
        </div>
        <Badge tone={tone as 'ok'} icon={doc.busy ? <Loader2 className="h-3 w-3 animate-spin" /> : undefined}>{label}</Badge>
        {doc.clauses > 0 && <ChevronDown className={cn('h-4 w-4 text-muted transition-transform', open && 'rotate-180')} />}
      </button>
      {doc.busy && <div className="h-1 overflow-hidden bg-sunken"><div className="h-full w-1/3 animate-pulse2 rounded-full bg-accent" /></div>}
      {open && <Outline doc={doc} onView={onView} />}
    </Card>
  )
}

export function LibraryPage() {
  const qc = useQueryClient()
  const wid = useWorkspaceId()
  const workspace = useWorkspace()
  const input = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const [view, setView] = useState<ViewSource | null>(null)
  const { data: docs = [], isLoading } = useQuery({
    queryKey: ['documents', wid],
    queryFn: () => api.documents(wid),
    refetchInterval: (q) => (q.state.data?.some((d) => d.busy) ? 2000 : false),
  })
  const upload = useMutation({
    mutationFn: (files: File[]) => api.upload(wid, files),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['documents', wid] }); void qc.invalidateQueries({ queryKey: ['workspaces'] }) },
  })
  const pick = (files: FileList | null) => { if (files?.length) upload.mutate([...files]) }

  return (
    <PageShell
      title="Documents"
      subtitle={`${workspace ? `Everything the assistant can use as proof in ${workspace.name}.` : 'Everything the assistant can use as proof.'} Add a PDF and it becomes searchable in about a minute.`}
    >
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files) }}
        className={cn('mb-6 rounded-2xl border-2 border-dashed p-8 text-center transition-colors', drag ? 'border-accent bg-accent-soft' : 'border-line bg-surface')}
      >
        <UploadCloud className="mx-auto mb-2 h-7 w-7 text-muted" aria-hidden />
        <p className="font-medium">Drag PDF files here, or <button className="text-accent-ink underline-offset-2 hover:underline" onClick={() => input.current?.click()}>browse</button></p>
        <p className="text-sm text-muted">
          Agreements, schedules of charges, amendments, circulars.{workspace?.demo ? ' Fictional demo files are already loaded.' : ' Amendments are linked to the documents they change in this workspace.'}
        </p>
        <input ref={input} type="file" accept="application/pdf" multiple hidden onChange={(e) => pick(e.target.files)} aria-label="Upload PDF files" />
        {upload.isPending && <p className="mt-2 text-sm text-muted">Uploading…</p>}
        {upload.isError && <p className="mt-2 text-sm text-clash" role="alert">{(upload.error as Error).message}</p>}
      </div>
      <div className="space-y-3">
        {isLoading && <><Skeleton className="h-20" /><Skeleton className="h-20" /></>}
        {docs.map((d) => <DocCard key={d.doc_id} doc={d} onView={setView} />)}
        {!isLoading && docs.length === 0 && <p className="rounded-xl border border-line bg-surface px-4 py-6 text-center text-sm text-muted">No documents in this workspace yet.</p>}
      </div>
      <SourceDialog source={view} onClose={() => setView(null)} />
    </PageShell>
  )
}
