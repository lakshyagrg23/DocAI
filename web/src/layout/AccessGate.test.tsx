import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '@/lib/api'
import { AccessGate } from './AccessGate'

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AccessGate><p>the app</p></AccessGate>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('AccessGate', () => {
  it('shows the app straight away when no code is required', async () => {
    vi.spyOn(api, 'session').mockResolvedValue({ required: false, ok: true })
    mount()
    expect(await screen.findByText('the app')).toBeInTheDocument()
  })

  it('asks for the code, rejects a wrong one, then lets the visitor in', async () => {
    const session = vi.spyOn(api, 'session').mockResolvedValue({ required: true, ok: false })
    const login = vi.spyOn(api, 'login')
      .mockRejectedValueOnce(new ApiError('That code is not right.', 401))
      .mockResolvedValueOnce({ ok: true })
    mount()
    expect(await screen.findByLabelText('Access code')).toBeInTheDocument()
    expect(screen.queryByText('the app')).not.toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('Access code'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('That code is not right.')

    session.mockResolvedValue({ required: true, ok: true })
    await userEvent.clear(screen.getByLabelText('Access code'))
    await userEvent.type(screen.getByLabelText('Access code'), 'right')
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await waitFor(() => expect(screen.getByText('the app')).toBeInTheDocument())
    expect(login).toHaveBeenCalledTimes(2)
  })
})
