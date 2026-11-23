/**
 * Plain-language copy: the single source of truth for every phrase the user reads (design/ui-react.md §3).
 * Rule: no internal terms (claim, faithfulness, contradicted, HHEM, span, clause ids) on the main surface.
 */
import { monthName, t } from './i18n'
import type { AnswerStatus, Checks, ClauseStatus, DisagreementSide } from './types'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-01-01" -> "1 Jan 2026" (no timezone surprises: parsed as plain numbers). */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  return m ? `${Number(m[3])} ${monthName(Number(m[2]) - 1, MONTHS)} ${m[1]}` : iso
}

/** Today's date in the user's own timezone as ISO (the API also uses local time; UTC would be off by a day near midnight). */
export function localToday(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** The day before an ISO date ("2025-04-01" -> "2025-03-31"): validity ranges end the day before the next rule starts. */
export function dayBefore(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() - 1)
  return d.toISOString().slice(0, 10)
}

const STATUS_BASE: Record<AnswerStatus, { label: string; tone: 'ok' | 'warn' | 'clash' | 'calm'; blurb: string }> = {
  answered: { label: 'Answer found', tone: 'ok', blurb: 'Every statement below was checked against your documents.' },
  partial: { label: 'Partly answered', tone: 'warn', blurb: 'Some parts are answered; the rest could not be proven.' },
  conflict: { label: 'Documents disagree', tone: 'clash', blurb: 'Your documents give different answers. Both are shown.' },
  abstained: { label: 'No proof found', tone: 'calm', blurb: "I couldn't find proof for this in your documents." },
}

const CLAUSE_BASE: Record<ClauseStatus, { label: string; tone: 'ok' | 'warn' | 'calm' }> = {
  in_force: { label: 'Applies today', tone: 'ok' },
  superseded: { label: 'Replaced', tone: 'warn' },
  future: { label: 'Not yet in effect', tone: 'calm' },
  deleted: { label: 'Removed', tone: 'calm' },
}

/** Status copy in the interface language (a Proxy keeps `STATUS_COPY[status]` working and reads `t()` at use time). */
export const STATUS_COPY = new Proxy(STATUS_BASE, {
  get: (o, k: string) => (k in o ? { ...o[k as AnswerStatus], label: t(o[k as AnswerStatus].label), blurb: t(o[k as AnswerStatus].blurb) } : undefined),
}) as typeof STATUS_BASE

export const CLAUSE_STATUS_COPY = new Proxy(CLAUSE_BASE, {
  get: (o, k: string) => (k in o ? { ...o[k as ClauseStatus], label: t(o[k as ClauseStatus].label) } : undefined),
}) as typeof CLAUSE_BASE

/** Wording of the status relative to the chosen date, e.g. "Applies on 1 Jan 2026". */
export function statusLabel(status: ClauseStatus, asOf: string, today: string): string {
  const base = CLAUSE_STATUS_COPY[status].label
  if (asOf === today) return base
  return status === 'in_force' ? t('Applied on {date}', { date: fmtDate(asOf) }) : base
}

export function plainReason(reason: string | null): string {
  if (!reason) return t('It could not be verified.')
  const r = reason.toLowerCase()
  const nums = /^(.+) not found in cited text$/i.exec(reason)
  if (nums) return `The figure ${nums[1]} does not appear in the cited text.`
  if (r.includes('quoted text')) return 'A quotation did not match the document.'
  if (r.includes("wasn't retrieved")) return 'It pointed at text that was not part of the evidence.'
  if (r.includes('superseded')) return 'It relied on a rule that has since been replaced.'
  if (r.includes('not entailed')) return 'The cited text does not clearly support this statement.'
  if (r.includes('model unavailable')) return 'The checking model was unavailable.'
  if (r.includes('disagree')) return t('The documents disagree on this.')
  return t('It could not be verified.')
}

export function supportStrength(score: number | null): { label: string; tone: 'ok' | 'warn' | 'calm' } {
  if (score === null) return { label: t('Not scored'), tone: 'calm' }
  if (score >= 0.8) return { label: t('Strong'), tone: 'ok' }
  if (score >= 0.5) return { label: t('Adequate'), tone: 'warn' }
  return { label: t('Weak'), tone: 'calm' }
}

/** The four checks every shown statement passed, in plain words. */
export function checkRows(c: Checks): { ok: boolean; label: string }[] {
  return [
    { ok: c.spans_valid, label: t('Points at text that was actually retrieved') },
    { ok: c.numbers_ok, label: t('Every number and date matches the source text') },
    { ok: c.quote_ok, label: t('Quotations match the source word for word') },
    { ok: c.version_ok, label: t('The rule applies on the chosen date') },
  ]
}

export function verifiedSummary(passed: number, drafted: number): string {
  if (drafted === 0) return t('No statements were produced')
  if (passed === drafted) return drafted === 1 ? t('The statement was checked against the documents') : t('All {n} statements were checked against the documents', { n: drafted })
  return t('{passed} of {drafted} statements were verified; {left} left out', { passed, drafted, left: drafted - passed })
}

export const subjectLabel = (s: string): string => {
  const t = s.replace(/_/g, ' ')
  return t.charAt(0).toUpperCase() + t.slice(1)
}

const perWords: Record<string, string> = { instalment: 'per instalment', installment: 'per instalment', instance: 'per instance', month: 'per month', annum: 'per year' } // translated when drawn

/** What one document says, in words: "₹750 per instalment", "at most ₹600 per instalment", "no charge". */
export function describeSide(side: Pick<DisagreementSide, 'op' | 'value' | 'scope'>): string {
  const v = side.value
  // The extracted value often already reads "₹750 per instalment"; only add the unit when it is missing.
  const per = side.scope?.per && !/\bper\b/i.test(v) ? ` ${perWords[side.scope.per] ? t(perWords[side.scope.per]) : `per ${side.scope.per}`}` : ''
  if (/^nil$/i.test(v) || /\bno\b.*\b(charge|fee)\b/i.test(v)) return t('no charge')
  if (side.op === 'max') return t('at most {v}', { v: `${v}${per}` })
  if (side.op === 'min') return t('at least {v}', { v: `${v}${per}` })
  return `${v}${per}`
}

/** One sentence that introduces a disagreement. */
export function disagreementSentence(subject: string): string {
  return t('Your documents give different answers about the {subject}.', { subject: subject.replace(/_/g, ' ') })
}

/** Timeline wording: "Until 31 Mar 2025", "From 1 Apr 2025", "From 1 Jan 2026 (applies today)". */
export function periodLabel(from: string | null, to: string | null): string {
  if (from && to) return `${fmtDate(from)} – ${fmtDate(dayBefore(to))}`
  if (to) return t('Until {date}', { date: fmtDate(dayBefore(to)) })
  if (from) return t('From {date}', { date: fmtDate(from) })
  return ''
}

const ACTION_BASE: Record<string, string> = {
  original: 'Original wording',
  substituted: 'Replaced by',
  inserted: 'Added by',
  deleted: 'Removed by',
}

export const ACTION_COPY = new Proxy(ACTION_BASE, { get: (o, k: string) => (k in o ? t(o[k]) : undefined) })

export function groupByDay(chats: { chat_id: string; created_at: string }[], now = new Date()) {
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const today = startOf(now)
  const buckets: Record<string, typeof chats> = { Today: [], Yesterday: [], 'Previous 7 days': [], Older: [] }
  for (const c of chats) {
    const days = Math.round((today - startOf(new Date(c.created_at))) / 86_400_000)
    buckets[days <= 0 ? 'Today' : days === 1 ? 'Yesterday' : days <= 7 ? 'Previous 7 days' : 'Older'].push(c)
  }
  return Object.entries(buckets).filter(([, v]) => v.length)
}

const num = (v: string): number | null => {
  const m = /[\d,]+(?:\.\d+)?/.exec(v)
  return m ? Number(m[0].replace(/,/g, '')) : null
}

/**
 * Plain sentences explaining a disagreement, built only from the sides' own values (no model involved):
 * different exact values, and exact values that exceed a stated maximum.
 */
export function conflictNotes(sides: (Pick<DisagreementSide, 'op' | 'value' | 'scope'> & { name: string })[]): string[] {
  const notes: string[] = []
  const exact = sides.filter((s) => s.op === 'eq')
  const caps = sides.filter((s) => s.op === 'max')
  const distinct = new Set(exact.map((s) => num(s.value)))
  if (exact.length > 1 && distinct.size > 1) {
    notes.push(exact.map((s) => `${s.name} says ${describeSide(s)}`).join(', but ') + '.')
  }
  for (const cap of caps) {
    const limit = num(cap.value)
    for (const e of exact) {
      const v = num(e.value)
      if (limit !== null && v !== null && v > limit) notes.push(`${e.name} charges ${e.value}, which is above the ${cap.value} limit in ${cap.name}.`)
    }
  }
  return notes
}

/** Strip the typographic quotes the documents put around replacement wording. */
export const unquote = (t: string): string => t.replace(/^[\s"“”']+|[\s"“”']+$/g, '')

export function snippet(text: string, max = 160): string {
  const t = unquote(text).replace(/\s+/g, ' ')
  return t.length > max ? `${t.slice(0, max - 1).trimEnd()}…` : t
}

/** "1 document", "3 documents". */
export const plural = (n: number, noun: string): string => `${n} ${noun}${n === 1 ? '' : 's'}`
