import * as Tabs from '@radix-ui/react-tabs'
import { CheckCircle2, CircleSlash, X } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { CLAUSE_STATUS_COPY, checkRows, fmtDate, plainReason, snippet, supportStrength, verifiedSummary } from '@/lib/plain'
import type { Answer, Source } from '@/lib/types'
import { useUi, type PanelTab } from '@/state/ui'
import { Badge, Button, Kicker } from '@/ui/primitives'
import { PageViewer, highlightOf } from './PageViewer'

const MIN = 340
const MAX = 720

function Quote({ src }: { src: Source }) {
  if (src.row) {
    return (
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-lg bg-sunken px-3 py-2 text-sm">
        {Object.entries(src.row).map(([k, v]) => (<div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="font-medium">{v}</dd></div>))}
      </dl>
    )
  }
  return <blockquote className="mt-2 border-l-2 border-mark pl-3 text-sm">{snippet(src.text, 320)}</blockquote>
}

function SourceCard({ src, selected, onSelect }: { src: Source; selected: boolean; onSelect: () => void }) {
  const st = CLAUSE_STATUS_COPY[src.status]
  return (
    <button
      onClick={onSelect}
      aria-current={selected}
      className={cn('w-full rounded-xl border bg-surface p-3 text-left shadow-card transition hover:border-accent', selected ? 'border-accent ring-1 ring-accent' : 'border-line')}
    >
      <div className="flex items-start gap-3">
        <span className="num grid h-6 w-6 shrink-0 place-items-center rounded-md bg-accent-soft text-xs font-semibold text-accent-ink">{src.n}</span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{src.doc_name}</p>
          <p className="text-xs text-muted">{src.clause_label} · page {src.page}{src.effective ? ` · effective ${fmtDate(src.effective)}` : ''}</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <Badge tone={st.tone}>{st.label}</Badge>
            {src.ocr && <Badge tone="warn">Scanned page</Badge>}
          </div>
        </div>
      </div>
      <Quote src={src} />
    </button>
  )
}

function SourcesTab({ answer, selected, onSelect }: { answer: Answer; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <div className="h-full space-y-3 overflow-y-auto p-4">
      <p className="text-sm text-muted">These are the passages the answer relies on. Select one to see it on the original page.</p>
      {answer.citations.map((id) => <SourceCard key={id} src={answer.sources[id]} selected={id === selected} onSelect={() => onSelect(id)} />)}
    </div>
  )
}

function ChecksTab({ answer, onSelect }: { answer: Answer; onSelect: (id: string) => void }) {
  return (
    <div className="h-full space-y-5 overflow-y-auto p-4">
      <div>
        <p className="font-medium">{verifiedSummary(answer.passed, answer.drafted)}</p>
        <p className="text-sm text-muted">Before anything is shown, each statement is compared with the exact words of the documents it cites.</p>
      </div>
      {answer.claims.map((c) => {
        const strength = supportStrength(c.checks.hhem)
        return (
          <section key={c.text} className="rounded-xl border border-line bg-surface p-3 shadow-card">
            <p className="text-sm font-medium">{c.text}</p>
            <ul className="mt-2 space-y-1">
              {checkRows(c.checks).map((r) => (
                <li key={r.label} className="flex items-start gap-2 text-sm text-muted">
                  {r.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" /> : <CircleSlash className="mt-0.5 h-4 w-4 shrink-0 text-clash" />}{r.label}
                </li>
              ))}
              <li className="flex items-start gap-2 text-sm text-muted">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" />
                Source text supports the statement <Badge tone={strength.tone}>{strength.label}</Badge>
              </li>
            </ul>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {c.span_ids.map((id) => answer.sources[id] && (
                <button key={id} onClick={() => onSelect(id)} className="rounded-md bg-accent-soft px-2 py-0.5 text-left text-xs font-medium text-accent-ink hover:underline">
                  {answer.sources[id].n}. {answer.sources[id].doc_name}, {answer.sources[id].clause_label}
                </button>
              ))}
            </div>
          </section>
        )
      })}
      {answer.blocked_claims.length > 0 && (
        <div>
          <Kicker>Left out of the answer ({answer.blocked_claims.length})</Kicker>
          <p className="mb-2 text-sm text-muted">These statements were drafted but could not be verified, so they are not shown as answers.</p>
          <ul className="space-y-2">
            {answer.blocked_claims.map((c) => (
              <li key={c.text} className="rounded-xl border border-line bg-sunken/50 p-3">
                <p className="text-sm text-muted line-through decoration-muted/50">{c.text}</p>
                <p className="mt-1 text-sm text-clash">{plainReason(c.reason)}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function Resizer({ onDrag }: { onDrag: (dx: number) => void }) {
  const start = useRef<number | null>(null)
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize panel"
      onPointerDown={(e) => { start.current = e.clientX; e.currentTarget.setPointerCapture(e.pointerId) }}
      onPointerMove={(e) => { if (start.current !== null) { onDrag(start.current - e.clientX); start.current = e.clientX } }}
      onPointerUp={() => { start.current = null }}
      className="absolute inset-y-0 -left-1 z-10 hidden w-2 cursor-col-resize hover:bg-accent/20 md:block"
    />
  )
}

/** Right-hand panel: Sources | Page | How we checked. Opens from a citation or the "Sources" button; Esc closes it. */
export function SourcesPanel() {
  const { panel, closePanel, setTab, setPage, openSource } = useUi()
  const [width, setWidth] = useState(() => Number(localStorage.getItem('docai.panel') ?? 460))
  useEffect(() => { localStorage.setItem('docai.panel', String(width)) }, [width])
  if (!panel.open || !panel.answer) return null

  const answer = panel.answer
  const src = panel.selected ? answer.sources[panel.selected] : null
  const narrow = window.innerWidth < 900
  const page = panel.page ?? src?.page ?? 1

  const tab = (value: PanelTab, label: string, count?: number): ReactNode => (
    <Tabs.Trigger
      value={value}
      className="relative px-3 py-2.5 text-sm font-medium text-muted outline-none transition-colors hover:text-ink data-[state=active]:text-ink data-[state=active]:after:absolute data-[state=active]:after:inset-x-3 data-[state=active]:after:bottom-0 data-[state=active]:after:h-0.5 data-[state=active]:after:rounded-full data-[state=active]:after:bg-accent"
    >
      {label}{count !== undefined && <span className="num ml-1.5 rounded-full bg-sunken px-1.5 text-xs">{count}</span>}
    </Tabs.Trigger>
  )

  return (
    <aside
      className={cn('relative flex shrink-0 flex-col border-l border-line bg-surface', narrow && 'fixed inset-y-0 right-0 z-40 shadow-pop')}
      style={{ width: narrow ? 'min(94vw, 460px)' : width }}
      aria-label="Sources and checks"
    >
      <Resizer onDrag={(dx) => setWidth((w) => Math.min(MAX, Math.max(MIN, w + dx)))} />
      <Tabs.Root value={panel.tab} onValueChange={(v) => setTab(v as PanelTab)} className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-line pl-2 pr-2">
          <Tabs.List className="flex" aria-label="Panel sections">
            {tab('sources', 'Sources', answer.citations.length)}
            {tab('page', 'Page')}
            {tab('checks', 'How we checked')}
          </Tabs.List>
          <Button size="icon" variant="ghost" onClick={closePanel} aria-label="Close panel"><X className="h-4 w-4" /></Button>
        </div>
        <Tabs.Content value="sources" className="min-h-0 flex-1 overflow-hidden outline-none">
          <SourcesTab answer={answer} selected={panel.selected} onSelect={(id) => openSource(answer, id)} />
        </Tabs.Content>
        <Tabs.Content value="page" className="flex min-h-0 flex-1 flex-col outline-none data-[state=inactive]:hidden">
          {src ? (
            <>
              <div className="border-b border-line px-4 py-3">
                <p className="font-medium">{src.doc_name}</p>
                <p className="text-sm text-muted">{src.clause_label} · page {src.page}{src.ocr ? ' · scanned' : ''}</p>
                <Quote src={src} />
              </div>
              <PageViewer docId={src.doc_id} page={page} pages={src.pages} highlight={highlightOf(src)} onPage={setPage} />
            </>
          ) : <p className="p-6 text-sm text-muted">Select a source to see it on the original page.</p>}
        </Tabs.Content>
        <Tabs.Content value="checks" className="min-h-0 flex-1 overflow-hidden outline-none">
          <ChecksTab answer={answer} onSelect={(id) => openSource(answer, id)} />
        </Tabs.Content>
      </Tabs.Root>
    </aside>
  )
}
