import { BadgeCheck, Check, ChevronRight, Copy, FileText, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/cn'
import { STATUS_COPY, fmtDate, localToday, verifiedSummary } from '@/lib/plain'
import type { Answer } from '@/lib/types'
import { useUi } from '@/state/ui'
import { Badge, Button, Tooltip } from '@/ui/primitives'
import { CalculationCard, DisagreementBlock, MissingList, RuleTimeline } from './blocks'
import { CitationChip } from './CitationChip'

const today = localToday

function plainText(answer: Answer): string {
  const lines = answer.claims.map((c) => c.text)
  answer.disagreements.forEach((d) => d.sides.forEach((s) => lines.push(`${s.doc_name ?? s.doc}: ${s.value}`)))
  return lines.join('\n') || STATUS_COPY[answer.status].blurb
}

export function AnswerCard({ answer }: { answer: Answer }) {
  const { openTab } = useUi()
  const [copied, setCopied] = useState(false)
  const copy = Boolean(navigator.clipboard)
  const status = STATUS_COPY[answer.status]
  const abstained = answer.status === 'abstained'
  // Facts already shown in a disagreement table are not repeated as separate statements.
  const inTables = new Set(answer.disagreements.flatMap((d) => d.sides.map((s) => s.span_id)))
  const statements = answer.claims.filter((c) => !c.span_ids.some((id) => inTables.has(id)))
  const nSources = answer.citations.length
  const asOfNote = answer.as_of_date === today() ? 'the rules that apply today' : `the rules as they applied on ${fmtDate(answer.as_of_date)}`

  return (
    <article className="animate-fade-in space-y-4" aria-label="Answer">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Badge tone={status.tone} icon={answer.status === 'answered' ? <BadgeCheck className="h-3.5 w-3.5" /> : undefined} className="px-2.5 py-1 text-sm">
          {status.label}
        </Badge>
        <span className="text-xs text-muted">Using {asOfNote}</span>
      </header>

      {abstained && (
        <div className="rounded-xl bg-calm-soft px-4 py-3 text-calm">
          <p className="font-medium">I couldn&apos;t find proof for this in your documents.</p>
          <p className="text-sm opacity-90">Rather than guess, I&apos;m leaving it unanswered. You can rephrase the question or upload the document that covers it.</p>
        </div>
      )}

      {answer.disagreements.map((d) => <DisagreementBlock key={d.conflict_id} card={d} answer={answer} />)}

      {statements.length > 0 && (
        <div className={cn('space-y-3', answer.disagreements.length > 0 && 'pt-1')}>
          {answer.disagreements.length > 0 && <p className="text-xs font-semibold uppercase tracking-wide text-muted">Also found</p>}
          {statements.map((c) => (
            <p key={c.text} className="text-[15.5px] leading-relaxed">
              {c.text}
              {c.span_ids.map((id) => <CitationChip key={id} answer={answer} spanId={id} />)}
            </p>
          ))}
        </div>
      )}

      {answer.chains.map((ch) => <RuleTimeline key={ch.version_key} chain={ch} answer={answer} asOf={answer.as_of_date} />)}
      {answer.calculation && <CalculationCard calc={answer.calculation} answer={answer} />}
      <MissingList items={answer.missing_evidence} abstained={abstained} />

      <footer className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-3">
        {nSources > 0 && (
          <Button size="sm" variant="secondary" onClick={() => openTab(answer, 'sources')}>
            <FileText className="h-4 w-4" /> Sources ({nSources}) <ChevronRight className="h-3.5 w-3.5 text-muted" />
          </Button>
        )}
        {answer.drafted > 0 && (
          <button onClick={() => openTab(answer, 'checks')} className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
            <ShieldCheck className="h-4 w-4 text-ok" aria-hidden /> {verifiedSummary(answer.passed, answer.drafted)}
            <span className="text-accent-ink underline-offset-2 hover:underline">How we checked</span>
          </button>
        )}
        {copy && (
          <Tooltip content={copied ? 'Copied' : 'Copy the answer as text'}>
            <Button
              size="icon"
              variant="ghost"
              className="ml-auto"
              aria-label="Copy answer"
              onClick={() => { void navigator.clipboard.writeText(plainText(answer)); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
            >
              {copied ? <Check className="h-4 w-4 text-ok" /> : <Copy className="h-4 w-4" />}
            </Button>
          </Tooltip>
        )}
      </footer>
    </article>
  )
}
