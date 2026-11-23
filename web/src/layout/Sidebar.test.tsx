import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import type { Chat, Workspace } from '@/lib/types'
import { UiProvider } from '@/state/ui'
import { TooltipProvider } from '@/ui/primitives'
import { Sidebar } from './Sidebar'

const ws = (id: string, name: string): Workspace => ({ workspace_id: id, name, created_at: 'x', documents: 1, ready: 1, chats: 1, demo: false })
const chat = (id: string, title: string, workspace: string): Chat => ({
  chat_id: id, workspace_id: workspace, title, created_at: new Date().toISOString(), as_of_date: null, language: 'auto', doc_scope: null,
})

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}

function mount(at: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <UiProvider>
        <TooltipProvider>
          <MemoryRouter initialEntries={[at]}>
            <Sidebar />
            <Routes><Route path="*" element={<Where />} /></Routes>
          </MemoryRouter>
        </TooltipProvider>
      </UiProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('Sidebar', () => {
  it('shows only the chats of the open workspace and links its pages inside that workspace', async () => {
    vi.spyOn(api, 'workspaces').mockResolvedValue([ws('a', 'Home loan'), ws('b', 'Car loan')])
    const chats = vi.spyOn(api, 'chats').mockImplementation(async (id) => (id === 'a' ? [chat('c1', 'Late fee question', 'a')] : [chat('c2', 'Other', 'b')]))
    mount('/w/a')
    expect(await screen.findByText('Late fee question')).toBeInTheDocument()
    expect(chats).toHaveBeenCalledWith('a')
    expect(screen.queryByText('Other')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Late fee question' })).toHaveAttribute('href', '/w/a/chat/c1')
    expect(screen.getByRole('link', { name: /Documents/ })).toHaveAttribute('href', '/w/a/library')
    expect(screen.getByRole('link', { name: /Conflicts/ })).toHaveAttribute('href', '/w/a/conflicts')
    expect(screen.getByRole('link', { name: /Amendments/ })).toHaveAttribute('href', '/w/a/amendments')
    expect(await screen.findByRole('button', { name: 'Switch workspace' })).toHaveTextContent('Home loan')
  })

  it('switches workspace from the menu', async () => {
    vi.spyOn(api, 'workspaces').mockResolvedValue([ws('a', 'Home loan'), ws('b', 'Car loan')])
    vi.spyOn(api, 'chats').mockResolvedValue([])
    mount('/w/a')
    await userEvent.click(await screen.findByRole('button', { name: 'Switch workspace' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Car loan' }))
    expect(screen.getByTestId('where')).toHaveTextContent('/w/b')
  })

  it('without a workspace in the address it offers no chats or document pages', async () => {
    vi.spyOn(api, 'workspaces').mockResolvedValue([ws('a', 'Home loan')])
    const chats = vi.spyOn(api, 'chats').mockResolvedValue([])
    mount('/workspaces')
    expect(await screen.findByText('Pick a workspace to see its chats and documents.')).toBeInTheDocument()
    expect(chats).not.toHaveBeenCalled()
    expect(screen.queryByRole('link', { name: /Documents/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Switch workspace' })).toHaveTextContent('None selected')
  })
})
