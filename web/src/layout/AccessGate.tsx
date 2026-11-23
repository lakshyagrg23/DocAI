import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Lock } from 'lucide-react'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { api, AUTH_EVENT, ApiError } from '@/lib/api'
import { Button, Card } from '@/ui/primitives'

/** Shows the app only after the visitor has entered the access code (when the server asks for one). */
export function AccessGate({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['session'], queryFn: api.session, staleTime: Infinity, retry: 1 })

  useEffect(() => {
    const again = () => void qc.invalidateQueries({ queryKey: ['session'] })
    window.addEventListener(AUTH_EVENT, again)
    return () => window.removeEventListener(AUTH_EVENT, again)
  }, [qc])

  if (isLoading) return <div className="min-h-screen" aria-busy="true" />
  if (data?.required && !data.ok) return <LoginForm onDone={() => void qc.invalidateQueries()} />
  return <>{children}</>
}

function LoginForm({ onDone }: { onDone: () => void }) {
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!code.trim()) return
    setBusy(true)
    setError(null)
    try {
      await api.login(code)
      onDone()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="grid min-h-screen place-items-center px-4">
      <Card className="w-full max-w-sm p-6">
        <div className="mb-4 flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-accent-soft text-accent-ink"><Lock className="h-4 w-4" aria-hidden /></span>
          <h1 className="text-lg font-semibold tracking-tight">Verifiable DocAI</h1>
        </div>
        <p className="mb-4 text-sm text-muted">This demo is private. Enter the access code you were given to continue.</p>
        <form onSubmit={submit} className="space-y-3">
          <label className="block text-sm font-medium" htmlFor="access-code">Access code</label>
          <input
            id="access-code"
            type="password"
            autoComplete="current-password"
            autoFocus
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm outline-none focus:border-accent"
          />
          {error && <p role="alert" className="text-sm text-clash">{error}</p>}
          <Button type="submit" variant="primary" className="w-full" loading={busy}>Continue</Button>
        </form>
      </Card>
    </main>
  )
}
