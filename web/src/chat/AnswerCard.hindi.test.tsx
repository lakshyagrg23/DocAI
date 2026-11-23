import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { setLangValue, t } from '@/lib/i18n'
import { STATUS_COPY, fmtDate, verifiedSummary } from '@/lib/plain'
import type { Answer } from '@/lib/types'
import { UiProvider } from '@/state/ui'
import { TooltipProvider } from '@/ui/primitives'
import { AnswerCard } from './AnswerCard'

const check = { spans_valid: true, numbers_ok: true, quote_ok: true, version_ok: true, hhem: 0.95, conflict_ids: [] }
const answer = (over: Partial<Answer> = {}): Answer => ({
  status: 'answered', question: 'व्यक्तिगत ऋण पर ब्याज दर क्या है?', language: 'hi', as_of_date: '2026-01-01', intent: 'lookup',
  claims: [{ text: 'The interest rate is 13.5% per annum.', text_local: 'ब्याज दर 13.5% प्रति वर्ष है।', span_ids: ['D1:5.1#s1'], verdict: 'supported', reason: null, checks: check }],
  blocked_claims: [], disagreements: [], missing_evidence: ['the processing fee'], missing_local: ['प्रोसेसिंग शुल्क'], chains: [], calculation: null,
  faithfulness_pct: 100, drafted: 1, passed: 1, sources: {}, citations: [], ...over,
})
const view = (a: Answer) => render(<UiProvider><TooltipProvider><AnswerCard answer={a} /></TooltipProvider></UiProvider>)

afterEach(() => setLangValue('en'))

describe('Hindi interface', () => {
  it('shows the number-guarded Hindi claim and missing item, with the Hindi chrome', () => {
    setLangValue('hi')
    view(answer())
    expect(screen.getByText('ब्याज दर 13.5% प्रति वर्ष है।')).toBeInTheDocument()
    expect(screen.queryByText('The interest rate is 13.5% per annum.')).not.toBeInTheDocument()
    expect(screen.getByText('प्रोसेसिंग शुल्क')).toBeInTheDocument()
    expect(screen.getByText('उत्तर मिला')).toBeInTheDocument()  // status badge
    expect(screen.getByText('हमने कैसे जाँचा')).toBeInTheDocument()
  })

  it('falls back to the verified English claim when no Hindi wording exists', () => {
    setLangValue('hi')
    const a = answer()
    a.claims[0].text_local = null
    view(a)
    expect(screen.getByText('The interest rate is 13.5% per annum.')).toBeInTheDocument()
  })

  it('stays fully English when the answer language is English', () => {
    view(answer({ language: 'en' }))
    expect(screen.getByText('The interest rate is 13.5% per annum.')).toBeInTheDocument()
    expect(screen.getByText('Answer found')).toBeInTheDocument()
  })

  it('translates the helpers, leaves unknown strings alone and fills placeholders', () => {
    setLangValue('hi')
    expect(STATUS_COPY.abstained.label).toBe('कोई प्रमाण नहीं मिला')
    expect(verifiedSummary(3, 4)).toBe('4 में से 3 कथन सत्यापित हुए; 1 छोड़ दिए गए')
    expect(fmtDate('2026-03-05')).toBe('5 मार्च 2026')
    expect(t('A sentence nobody translated')).toBe('A sentence nobody translated')
  })
})
