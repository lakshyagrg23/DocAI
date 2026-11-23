import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import type { Workspace } from '@/lib/types'
import { UiProvider } from '@/state/ui'
import { TooltipProvider } from '@/ui/primitives'
import { WorkspacesPage } from './Workspaces'

const ws = (id: string, name: string, extra: Partial<Workspace> = {}): Workspace => ({
  workspace_id: id, name, created_at: '2026-11-23T00:00:00+00:00', documents: 2, ready: 2, chats: 1, demo: false, ...extra,
})

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <UiProvider>
        <TooltipProvider>
          <MemoryRouter initialEntries={['/workspaces']}>
            <Routes>
              <Route path="/workspaces" element={<WorkspacesPage />} />
              <Route path="*" element={<Where />} />
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </UiProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('Workspaces page', () => {
  it('lists workspaces with their counts and marks the demo one', async () => {
    vi.spyOn(api, 'workspaces').mockResolvedValue([ws('ws_demo', 'Kestrel demo', { demo: true, documents: 6, chats: 3 }), ws('ws_a', 'Home loan', { documents: 1, chats: 0 })])
    mount()
    expect(await screen.findByRole('button', { name: 'Open workspace Kestrel demo' })).toHaveTextContent('6 documents')
    expect(screen.getByRole('button', { name: 'Open workspace Kestrel demo' })).toHaveTextContent('3 chats')
    expect(screen.getByRole('button', { name: 'Open workspace Kestrel demo' })).toHaveTextContent('Demo')
    expect(screen.getByRole('button', { name: 'Open workspace Home loan' })).toHaveTextContent('1 document')
    expect(screen.getByRole('button', { name: 'Open workspace Home loan' })).toHaveTextContent('0 chats')
  })

  it('opens a workspace when its card is clicked', async () => {
    vi.spyOn(api, 'workspaces').mockResolvedValue([ws('ws_a', 'Home loan')])
    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'Open workspace Home loan' }))
    expect(screen.getByTestId('where')).toHaveTextContent('/w/ws_a')
  })

  it('creates a workspace and goes straight to its documents', async () => {
    vi.spyOn(api, 'workspaces').mockResolvedValue([])
    const create = vi.spyOn(api, 'createWorkspace').mockResolvedValue(ws('ws_new', 'Car loan', { documents: 0, chats: 0 }))
    mount()
    expect(await screen.findByText('Create your first workspace')).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: /New workspace/ })[0])
    const save = screen.getByRole('button', { name: 'Save' })
    expect(save).toBeDisabled() // a name is required
    await userEvent.type(screen.getByLabelText('Workspace name'), '  Car loan ')
    await userEvent.click(save)
    await waitFor(() => expect(create).toHaveBeenCalledWith('Car loan'))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/w/ws_new/library'))
  })

  it('shows the server message when a workspace cannot be created', async () => {
    vi.spyOn(api, 'workspaces').mockResolvedValue([ws('ws_a', 'Home loan')])
    vi.spyOn(api, 'createWorkspace').mockRejectedValue(new Error('At most 20 workspaces are allowed.'))
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /New workspace/ }))
    await userEvent.type(screen.getByLabelText('Workspace name'), 'One more')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('At most 20 workspaces')
  })

  it('never offers to delete the demo workspace, and asks before deleting another one', async () => {
    vi.spyOn(api, 'workspaces').mockResolvedValue([ws('ws_demo', 'Kestrel demo', { demo: true }), ws('ws_a', 'Home loan', { documents: 3, chats: 2 })])
    const del = vi.spyOn(api, 'deleteWorkspace').mockResolvedValue(undefined)
    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'Options for Kestrel demo' }))
    expect(await screen.findByRole('menuitem', { name: /Rename/ })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: /Delete/ })).not.toBeInTheDocument()
    await userEvent.keyboard('{Escape}')

    await userEvent.click(screen.getByRole('button', { name: 'Options for Home loan' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: /Delete/ }))
    expect(screen.getByText(/permanently removes its 3 documents and 2 chats/)).toBeInTheDocument()
    expect(del).not.toHaveBeenCalled() // nothing happens until it is confirmed
    await userEvent.click(screen.getByRole('button', { name: 'Delete workspace' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('ws_a'))
  })

  it('renames a workspace', async () => {
    vi.spyOn(api, 'workspaces').mockResolvedValue([ws('ws_a', 'Home loan')])
    const rename = vi.spyOn(api, 'renameWorkspace').mockResolvedValue(ws('ws_a', 'House loan'))
    mount()
    await userEvent.click(await screen.findByRole('button', { name: 'Options for Home loan' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: /Rename/ }))
    const box = screen.getByLabelText('Workspace name')
    await userEvent.clear(box)
    await userEvent.type(box, 'House loan')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(rename).toHaveBeenCalledWith('ws_a', 'House loan'))
  })
})
