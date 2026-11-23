import { describe, expect, it } from 'vitest'
import { parseSse } from './api'
import type { DisagreementSide } from './types'
import {
  conflictNotes, dayBefore, describeSide, fmtDate, groupByDay, localToday, periodLabel, plainReason, plural, snippet, statusLabel,
  supportStrength, unquote, verifiedSummary,
} from './plain'

describe('dates', () => {
  it('formats ISO dates without timezone drift', () => {
    expect(fmtDate('2026-01-01')).toBe('1 Jan 2026')
    expect(fmtDate('2025-12-31')).toBe('31 Dec 2025')
    expect(fmtDate(null)).toBe('')
  })
  it('ends a validity range the day before the next rule starts', () => {
    expect(dayBefore('2025-04-01')).toBe('2025-03-31')
    expect(dayBefore('2026-01-01')).toBe('2025-12-31')
    expect(periodLabel('2024-01-15', '2025-04-01')).toBe('15 Jan 2024 – 31 Mar 2025')
    expect(periodLabel('2026-01-01', null)).toBe('From 1 Jan 2026')
  })
  it('uses the local calendar day', () => {
    expect(localToday()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
  it('words the status relative to the chosen date', () => {
    expect(statusLabel('in_force', '2026-11-23', '2026-11-23')).toBe('Applies today')
    expect(statusLabel('in_force', '2025-06-01', '2026-11-23')).toBe('Applied on 1 Jun 2025')
    expect(statusLabel('superseded', '2025-06-01', '2026-11-23')).toBe('Replaced')
  })
})

describe('counts', () => {
  it('pluralises nouns', () => {
    expect([plural(0, 'chat'), plural(1, 'chat'), plural(2, 'document')]).toEqual(['0 chats', '1 chat', '2 documents'])
  })
})

describe('plain wording', () => {
  it('turns verifier reasons into sentences a person can read', () => {
    expect(plainReason('₹900 not found in cited text')).toBe('The figure ₹900 does not appear in the cited text.')
    expect(plainReason('cites a superseded clause')).toBe('It relied on a rule that has since been replaced.')
    expect(plainReason('not entailed by the cited text (0.21)')).toBe('The cited text does not clearly support this statement.')
    expect(plainReason(null)).toBe('It could not be verified.')
    for (const r of ['quoted text doesn\'t match the source', "cites evidence that wasn't retrieved", 'zzz']) {
      expect(plainReason(r)).not.toMatch(/hhem|entail|span|clause id/i)
    }
  })
  it('summarises verification without jargon', () => {
    expect(verifiedSummary(2, 2)).toBe('All 2 statements were checked against the documents')
    expect(verifiedSummary(1, 1)).toBe('The statement was checked against the documents')
    expect(verifiedSummary(2, 3)).toBe('2 of 3 statements were verified; 1 left out')
    expect(supportStrength(0.95).label).toBe('Strong')
    expect(supportStrength(0.6).label).toBe('Adequate')
    expect(supportStrength(0.2).label).toBe('Weak')
  })
  it('trims quotes and long text', () => {
    expect(unquote('"7.2 No charge."')).toBe('7.2 No charge.')
    expect(snippet('a'.repeat(300), 50)).toHaveLength(50)
  })
})

describe('disagreements', () => {
  const sides: (Pick<DisagreementSide, 'op' | 'value' | 'scope'> & { name: string })[] = [
    { name: 'Loan Agreement', op: 'eq', value: '₹500', scope: { per: 'instalment' } },
    { name: 'Schedule of Charges', op: 'eq', value: '₹750 per instalment', scope: { per: 'instalment' } },
    { name: 'Circular FCB/2025/17', op: 'max', value: '₹600', scope: {} },
  ]
  it('describes what a document says, without repeating the unit', () => {
    expect(describeSide(sides[0])).toBe('₹500 per instalment')
    expect(describeSide(sides[1])).toBe('₹750 per instalment')
    expect(describeSide(sides[2])).toBe('at most ₹600')
    expect(describeSide({ op: 'bool', value: 'Nil', scope: {} })).toBe('no charge')
  })
  it('explains differences and cap violations in plain sentences', () => {
    const notes = conflictNotes(sides)
    expect(notes[0]).toBe('Loan Agreement says ₹500 per instalment, but Schedule of Charges says ₹750 per instalment.')
    expect(notes[1]).toBe('Schedule of Charges charges ₹750 per instalment, which is above the ₹600 limit in Circular FCB/2025/17.')
    expect(conflictNotes([sides[0], sides[2]])).toEqual([])  // ₹500 is within the ₹600 cap: nothing to flag
  })
})

describe('chat history grouping', () => {
  it('groups by recency', () => {
    const now = new Date(2026, 10, 23, 12)
    const iso = (d: number) => new Date(2026, 10, 23 - d, 9).toISOString()
    const groups = groupByDay([{ chat_id: 'a', created_at: iso(0) }, { chat_id: 'b', created_at: iso(1) }, { chat_id: 'c', created_at: iso(4) }, { chat_id: 'd', created_at: iso(30) }], now)
    expect(groups.map(([k]) => k)).toEqual(['Today', 'Yesterday', 'Previous 7 days', 'Older'])
  })
})

describe('server-sent events', () => {
  it('parses stage and answer events', () => {
    const out = parseSse('event: stage\ndata: {"step":1}\n\nevent: answer\ndata: {"ok":true}\n\n')
    expect(out).toEqual([{ event: 'stage', data: { step: 1 } }, { event: 'answer', data: { ok: true } }])
  })
})
