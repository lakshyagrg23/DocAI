import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'
import type { Workspace } from '@/lib/types'
import { UiProvider } from '@/state/ui'
import { HomeRedirect, WorkspaceGate } from './WorkspaceGate'

const ws = (id: string, name: string): Workspace => ({ workspace_id: id, name, created_at: 'x', documents: 1, ready: 1, chats: 0, demo: false })

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}

function mount(at: string, seed?: Workspace[]) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (seed) qc.setQueryData(['workspaces'], seed)
  render(
    <QueryClientProvider client={qc}>
      <UiProvider>
        <MemoryRouter initialEntries={[at]}>
          <Routes>
            <Route index element={<HomeRedirect />} />
            <Route path="workspaces" element={<Where />} />
            <Route path="w/:workspaceId" element={<WorkspaceGate />}>
              <Route index element={<p>inside the workspace</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </UiProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('HomeRedirect', () => {
  it('opens the workspace used last', async () => {
    vi.spyOn(api, 'workspaces').mockResolvedValue([ws('a', 'A'), ws('b', 'B')])
    localStorage.setItem('docai.workspace', 'b')
    mount('/')
    expect(await screen.findByText('inside the workspace')).toBeInTheDocument()
  })

  it('falls back to the first workspace when the remembered one is gone', async () => {
    vi.spyOn(api, 'workspaces').mockResolvedValue([ws('a', 'A')])
    localStorage.setItem('docai.workspace', 'deleted')
    mount('/')
    expect(await screen.findByText('inside the workspace')).toBeInTheDocument()
  })

  it('goes to the Workspaces page when there are none', async () => {
    vi.spyOn(api, 'workspaces').mockResolvedValue([])
    mount('/')
    expect(await screen.findByTestId('where')).toHaveTextContent('/workspaces')
  })
})

describe('WorkspaceGate', () => {
  it('shows a known workspace and remembers it', async () => {
    vi.spyOn(api, 'workspaces').mockResolvedValue([ws('a', 'A')])
    mount('/w/a')
    expect(await screen.findByText('inside the workspace')).toBeInTheDocument()
    expect(localStorage.getItem('docai.workspace')).toBe('a')
  })

  it('waits for the list to refresh instead of bouncing a workspace that was just created', async () => {
    // the cache still has the old list; the refetch (as after "create workspace") brings the new one
    vi.spyOn(api, 'workspaces').mockImplementation(() => new Promise((r) => setTimeout(() => r([ws('a', 'A'), ws('new', 'New')]), 50)))
    mount('/w/new', [ws('a', 'A')])
    expect(await screen.findByText('inside the workspace')).toBeInTheDocument()
    expect(screen.queryByTestId('where')).not.toBeInTheDocument()
  })

  it('sends an unknown workspace back to the list and does not remember it', async () => {
    vi.spyOn(api, 'workspaces').mockResolvedValue([ws('a', 'A')])
    mount('/w/nope')
    expect(await screen.findByTestId('where')).toHaveTextContent('/workspaces')
    expect(localStorage.getItem('docai.workspace')).toBeNull()
  })
})
