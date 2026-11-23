import { Calculator, CheckCircle2, CircleHelp, Scale } from 'lucide-react'
import { ACTION_COPY, CLAUSE_STATUS_COPY, conflictNotes, describeSide, disagreementSentence, fmtDate, localToday, periodLabel, snippet, statusLabel, subjectLabel, unquote } from '@/lib/plain'
import { t } from '@/lib/i18n'
import type { Answer, Calculation, Chain, Disagreement } from '@/lib/types'
import { cn } from '@/lib/cn'
import { Badge, Card, Kicker } from '@/ui/primitives'
import { CitationChip } from './CitationChip'

const today = localToday

/** "Your documents give different answers about X" + a comparison table + plain notes. Used in chat and on the Conflicts page. */
export function DisagreementBlock({ card, answer, onOpen }: { card: Disagreement; answer?: Answer; onOpen?: (spanId: string) => void }) {
  const named = card.sides.map((s) => ({ ...s, name: s.doc_name ?? s.doc_title ?? s.doc }))
  const notes = conflictNotes(named)
  return (
    <Card className="overflow-hidden border-clash/30">
      <div className="flex items-start gap-3 bg-clash-soft px-4 py-3">
        <Scale className="mt-0.5 h-5 w-5 shrink-0 text-clash" aria-hidden />
        <div>
          <p className="font-medium text-ink">{disagreementSentence(card.subject)}</p>
          <p className="text-sm text-muted">{t('Here is what each document says. Nothing was guessed or averaged.')}</p>
        </div>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
            <th className="px-4 py-2 font-semibold">{t('Document')}</th>
            <th className="px-4 py-2 font-semibold">{t('What it says')}</th>
          </tr>
        </thead>
        <tbody>
          {named.map((s) => (
            <tr key={s.span_id} className="border-b border-line last:border-0 align-top">
              <td className="px-4 py-3">
                <p className="font-medium">{s.name}</p>
                <p className="text-xs text-muted">{s.clause_label ?? s.clause_id} · {t('page {n}', { n: s.page ?? '' })}</p>
              </td>
              <td className="px-4 py-3">
                <p className="num text-base font-semibold">{describeSide(s)}</p>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  {s.status !== 'in_force' && <Badge tone={CLAUSE_STATUS_COPY[s.status].tone}>{CLAUSE_STATUS_COPY[s.status].label}</Badge>}
                  {answer ? <CitationChip answer={answer} spanId={s.span_id} /> : onOpen && (
                    <button className="text-xs font-medium text-accent-ink hover:underline" onClick={() => onOpen(s.span_id)}>{t('View source')}</button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {notes.length > 0 && (
        <ul className="space-y-1 border-t border-line bg-sunken/60 px-4 py-3 text-sm">
          {notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
    </Card>
  )
}

/** "How this rule changed": a vertical timeline in plain words; the step that applies on the chosen date is highlighted. */
export function RuleTimeline({ chain, answer, asOf, title = t('How this rule changed'), onOpen }:
  { chain: Chain; answer?: Answer; asOf: string; title?: string; onOpen?: (spanId: string) => void }) {
  return (
    <Card className="p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <Kicker>{title}</Kicker>
          {chain.label && <p className="font-medium">{chain.label}</p>}
        </div>
        <p className="text-xs text-muted">{t('Showing {what}', { what: asOf === today() ? t('today') : fmtDate(asOf) })}</p>
      </div>
      <ol className="relative space-y-4 border-l border-line pl-5">
        {chain.steps.map((s, i) => {
          const current = i === chain.in_force_step
          const status = current ? 'in_force' : (s.valid_to && s.valid_to <= asOf ? 'superseded' : 'future')
          const text = s.text ? snippet(s.text, 220) : s.action === 'deleted' ? t('This rule was removed.') : ''
          return (
            <li key={`${s.clause_id}-${i}`} className="relative">
              <span className={cn('absolute -left-[26px] top-1.5 h-3 w-3 rounded-full border-2 border-surface', current ? 'bg-ok' : 'bg-line')} aria-hidden />
              <div className="flex flex-wrap items-center gap-2">
                <p className="num text-sm font-semibold">{periodLabel(s.valid_from, s.valid_to)}</p>
                {current && <Badge tone="ok" icon={<CheckCircle2 className="h-3 w-3" />}>{statusLabel('in_force', asOf, today())}</Badge>}
                {!current && <Badge tone={CLAUSE_STATUS_COPY[status].tone}>{CLAUSE_STATUS_COPY[status].label}</Badge>}
              </div>
              <p className="text-sm text-muted">{s.action === 'original' ? `${ACTION_COPY.original} · ${s.doc_name ?? ''}` : `${ACTION_COPY[s.action]} ${s.doc_name ?? ''}`}</p>
              {text && (
                <blockquote className={cn('mt-1 border-l-2 pl-3 text-sm', current ? 'border-ok text-ink' : 'border-line text-muted')}>
                  {unquote(text)}{' '}
                  {s.span_id && (answer ? <CitationChip answer={answer} spanId={s.span_id} /> : onOpen && (
                    <button className="text-xs font-medium text-accent-ink hover:underline" onClick={() => onOpen(s.span_id!)}>{t('View source')}</button>
                  ))}
                </blockquote>
              )}
            </li>
          )
        })}
      </ol>
    </Card>
  )
}

export function CalculationCard({ calc, answer }: { calc: Calculation; answer: Answer }) {
  return (
    <Card className="p-4">
      <div className="mb-2 flex items-center gap-2"><Calculator className="h-4 w-4 text-accent-ink" /><Kicker>{t('Calculation')}</Kicker></div>
      <table className="mb-3 w-full text-sm">
        <tbody>
          {calc.inputs.map((i) => (
            <tr key={i.name} className="border-b border-line last:border-0">
              <td className="py-1.5 pr-4 text-muted">{(i.name_local ?? i.name).replace(/_/g, ' ')}</td>
              <td className="num py-1.5 font-medium">{i.value.toLocaleString('en-IN')}</td>
              <td className="py-1.5 text-right text-xs text-muted">
                {i.span_id ? <CitationChip answer={answer} spanId={i.span_id} /> : t('from your question')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className="mb-3 space-y-1 text-sm text-muted">{(calc.steps_local ?? calc.steps).map((s) => <li key={s} className="num">{s}</li>)}</ul>
      {calc.result !== null && <p className="num text-2xl font-semibold">{calc.unit === 'INR' ? '₹' : ''}{calc.result.toLocaleString('en-IN')}</p>}
    </Card>
  )
}

export function MissingList({ items, abstained }: { items: string[]; abstained: boolean }) {
  if (!items.length) return null
  return (
    <div className="rounded-xl border border-dashed border-line bg-sunken/50 px-4 py-3">
      <div className="mb-1 flex items-center gap-2 text-sm font-medium"><CircleHelp className="h-4 w-4 text-muted" aria-hidden />
        {abstained ? t('What I was looking for') : t("What I couldn't find")}
      </div>
      <ul className="list-disc space-y-0.5 pl-9 text-sm text-muted">{items.map((m) => <li key={m}>{m}</li>)}</ul>
    </div>
  )
}

export { subjectLabel }
