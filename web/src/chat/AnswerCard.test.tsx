import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Answer, Source } from '@/lib/types'
import { UiProvider, useUi } from '@/state/ui'
import { TooltipProvider } from '@/ui/primitives'
import { AnswerCard } from './AnswerCard'
import { Composer } from './Composer'

const src = (n: number, id: string, doc: string, label: string, page: number): Source => ({
  n, span_id: id, clause_id: id.split('#')[0], doc_id: doc, doc_name: doc === 'D1' ? 'Personal Loan Agreement' : doc === 'D2' ? 'Schedule of Charges' : 'Circular FCB/2025/17',
  doc_sub: '', clause_label: label, page, pages: 6, page_width: 595, page_height: 842, bboxes: [[50, 100, 300, 120]], text: 'text', row: null,
  ocr: false, ocr_conf: null, status: 'in_force', effective: '2024-01-15',
})
const side = (id: string, doc: string, op: string, value: string, label: string) => ({
  span_id: id, clause_id: id.split('#')[0], doc, doc_name: src(1, id, doc, label, 1).doc_name, clause_label: label, page: 1, status: 'in_force' as const,
  value, op, attribute: 'amount', scope: { per: 'instalment' }, text: 'x',
})

const conflict: Answer = {
  status: 'conflict', question: 'What fees apply if I pay an EMI late?', as_of_date: '2026-11-23', intent: 'multi',
  claims: [{ text: 'A late payment fee of ₹500 per instalment applies.', span_ids: ['D1:8.1#s1'], verdict: 'contradicted', reason: 'the documents disagree on this',
    checks: { spans_valid: true, numbers_ok: true, quote_ok: true, version_ok: true, hhem: 0.95, conflict_ids: ['c1'] } }],
  blocked_claims: [], missing_evidence: [], chains: [], calculation: null, faithfulness_pct: 100, drafted: 2, passed: 2,
  disagreements: [{ conflict_id: 'c1', conflict_ids: ['c1'], subject: 'late_payment_fee', type: 'numeric', severity: 'high', explanation: 'raw explanation',
    sides: [side('D1:8.1#s1', 'D1', 'eq', '₹500', 'Clause 8.1'), side('D2:table1.row2#s1', 'D2', 'eq', '₹750 per instalment', 'Table row: Late payment fee'),
      side('D5:1#s1', 'D5', 'max', '₹600', 'Clause 1')] }],
  sources: { 'D1:8.1#s1': src(1, 'D1:8.1#s1', 'D1', 'Clause 8.1', 4), 'D2:table1.row2#s1': src(2, 'D2:table1.row2#s1', 'D2', 'Table row: Late payment fee', 1),
    'D5:1#s1': src(3, 'D5:1#s1', 'D5', 'Clause 1', 1) },
  citations: ['D1:8.1#s1', 'D2:table1.row2#s1', 'D5:1#s1'],
}

function PanelProbe() {
  const { panel } = useUi()
  return <output data-testid="panel">{panel.open ? `${panel.tab}:${panel.selected}` : 'closed'}</output>
}
const wrap = (ui: React.ReactElement) => render(<UiProvider><TooltipProvider>{ui}<PanelProbe /></TooltipProvider></UiProvider>)

describe('AnswerCard (conflict)', () => {
  it('reads in plain language: headline, comparison table, notes, sources', () => {
    wrap(<AnswerCard answer={conflict} />)
    expect(screen.getByText('Documents disagree')).toBeInTheDocument()
    expect(screen.getByText('Your documents give different answers about the late payment fee.')).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getByText('Personal Loan Agreement')).toBeInTheDocument()
    expect(within(table).getByText('Table row: Late payment fee · page 1')).toBeInTheDocument()
    expect(within(table).getByText('at most ₹600 per instalment')).toBeInTheDocument()
    expect(within(table).getByText('₹750 per instalment')).toBeInTheDocument()
    expect(screen.getByText(/which is above the ₹600 limit/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Sources \(3\)/ })).toBeInTheDocument()
    expect(screen.getByText('All 2 statements were checked against the documents')).toBeInTheDocument()
  })
  it('shows no internal jargon and no raw ids', () => {
    const { container } = wrap(<AnswerCard answer={conflict} />)
    const text = container.textContent ?? ''
    for (const bad of [/faithfulness/i, /contradicted/i, /hhem/i, /drafted/i, /D\d:\S+#s\d/, /D2:table1/, /raw explanation/]) expect(text).not.toMatch(bad)
  })
  it('does not repeat a fact that is already in the comparison table', () => {
    wrap(<AnswerCard answer={conflict} />)
    expect(screen.queryByText('A late payment fee of ₹500 per instalment applies.')).not.toBeInTheDocument()
  })
  it('opens the side panel on the clicked citation', async () => {
    wrap(<AnswerCard answer={conflict} />)
    await userEvent.click(screen.getByRole('button', { name: /Source 2: Schedule of Charges/ }))
    expect(screen.getByTestId('panel')).toHaveTextContent('page:D2:table1.row2#s1')
  })
  it('opens the checks tab from the footer', async () => {
    wrap(<AnswerCard answer={conflict} />)
    await userEvent.click(screen.getByRole('button', { name: /How we checked/ }))
    expect(screen.getByTestId('panel')).toHaveTextContent(/^checks:/)
  })
})

describe('AnswerCard (no proof)', () => {
  it('is calm and explains what to do', () => {
    const a: Answer = { ...conflict, status: 'abstained', claims: [], disagreements: [], sources: {}, citations: [], drafted: 0, passed: 0,
      missing_evidence: ['The GST rate on the processing fee.'] }
    wrap(<AnswerCard answer={a} />)
    expect(screen.getByText('No proof found')).toBeInTheDocument()
    expect(screen.getByText("I couldn't find proof for this in your documents.")).toBeInTheDocument()
    expect(screen.getByText('What I was looking for')).toBeInTheDocument()
    expect(screen.getByText('The GST rate on the processing fee.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Sources/ })).not.toBeInTheDocument()
  })
})

describe('Composer', () => {
  const setup = (busy = false) => {
    const onSend = vi.fn()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <TooltipProvider><Composer workspaceId="ws1" onSend={onSend} busy={busy} asOf="2026-11-23" today="2026-11-23" onAsOf={() => {}} scope={null} onScope={() => {}} /></TooltipProvider>
      </QueryClientProvider>,
    )
    return onSend
  }
  it('sends on Enter and keeps Shift+Enter for new lines', async () => {
    const onSend = setup()
    const box = screen.getByLabelText('Your question')
    await userEvent.type(box, 'hello{Shift>}{Enter}{/Shift}there')
    expect(onSend).not.toHaveBeenCalled()
    await userEvent.type(box, '{Enter}')
    expect(onSend).toHaveBeenCalledWith('hello\nthere')
  })
  it('will not send an empty question or while an answer is being produced', async () => {
    const onSend = setup(true)
    await userEvent.type(screen.getByLabelText('Your question'), 'x{Enter}')
    expect(onSend).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Send question' })).toBeDisabled()
  })
})
