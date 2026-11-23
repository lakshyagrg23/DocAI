import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import type { Doc } from '@/lib/types'
import { ScopeMenu } from './ScopeMenu'

const doc = (id: string, name: string, status = 'Ready'): Doc => ({
  doc_id: id, name, sub: '', type: null, ref_no: null, issued: null, effective: null, pages: 1, ocr: false, clauses: 1, facts: 1,
  status, status_label: status, busy: false, detail: null, needs_ocr: false,
})

describe('ScopeMenu', () => {
  beforeEach(() => {
    vi.spyOn(api, 'documents').mockResolvedValue([doc('D1', 'Loan Agreement'), doc('D2', 'Schedule of Charges'), doc('D3', 'Still Parsing', 'Parsing')])
  })
  const setup = (scope: string[] | null) => {
    const onChange = vi.fn()
    render(<QueryClientProvider client={new QueryClient()}><ScopeMenu scope={scope} onChange={onChange} /></QueryClientProvider>)
    return onChange
  }

  it('says "All documents" when nothing is selected', async () => {
    setup(null)
    expect(await screen.findByRole('button', { name: /Choose which documents/ })).toHaveTextContent('All documents')
  })

  it('unticking one document narrows the scope to the others', async () => {
    const onChange = setup(null)
    await userEvent.click(await screen.findByRole('button', { name: /Choose which documents/ }))
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: /Schedule of Charges/ }))
    expect(onChange).toHaveBeenCalledWith(['D1'])
    expect(screen.queryByText('Still Parsing')).not.toBeInTheDocument() // only finished documents can be chosen
  })

  it('never lets the last document be unticked, and ticking everything returns to "all"', async () => {
    const onChange = setup(['D1'])
    await userEvent.click(await screen.findByRole('button', { name: /Choose which documents/ }))
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: /Loan Agreement/ }))
    expect(onChange).not.toHaveBeenCalled()
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: /Schedule of Charges/ }))
    expect(onChange).toHaveBeenCalledWith(null)
  })
})
