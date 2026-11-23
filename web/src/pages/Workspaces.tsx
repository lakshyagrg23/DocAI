import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { FileText, FolderOpen, MessageSquare, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageShell } from '@/layout/PageShell'
import { api } from '@/lib/api'
import { plural } from '@/lib/plain'
import type { Workspace } from '@/lib/types'
import { workspacePath, workspacesQuery } from '@/state/workspace'
import { Badge, Button, Card, Skeleton } from '@/ui/primitives'

function NameForm({ initial, submit, cancel, label, busy }: {
  initial: string; submit: (name: string) => void; cancel: () => void; label: string; busy?: boolean
}) {
  const [name, setName] = useState(initial)
  const go = (e: FormEvent) => { e.preventDefault(); if (name.trim()) submit(name.trim()) }
  return (
    <form onSubmit={go} className="flex items-center gap-2">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && cancel()}
        maxLength={60}
        placeholder="e.g. Home loan 2026"
        aria-label={label}
        className="h-10 min-w-0 flex-1 rounded-lg border border-accent bg-surface px-3 text-sm outline-none"
      />
      <Button type="submit" variant="primary" loading={busy} disabled={!name.trim()}>Save</Button>
      <Button type="button" variant="ghost" onClick={cancel}>Cancel</Button>
    </form>
  )
}

function WorkspaceCard({ ws }: { ws: Workspace }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'view' | 'rename' | 'confirm'>('view')
  const refresh = () => qc.invalidateQueries({ queryKey: ['workspaces'] })
  const rename = useMutation({ mutationFn: (name: string) => api.renameWorkspace(ws.workspace_id, name), onSuccess: () => { void refresh(); setMode('view') } })
  const remove = useMutation({ mutationFn: () => api.deleteWorkspace(ws.workspace_id), onSuccess: () => { void refresh(); setMode('view') } })

  if (mode === 'rename') {
    return (
      <Card className="p-4">
        <NameForm initial={ws.name} label="Workspace name" submit={(n) => rename.mutate(n)} cancel={() => setMode('view')} busy={rename.isPending} />
        {rename.isError && <p className="mt-2 text-sm text-clash" role="alert">{(rename.error as Error).message}</p>}
      </Card>
    )
  }
  if (mode === 'confirm') {
    return (
      <Card className="border-clash/30 bg-clash-soft p-4 text-clash">
        <p className="font-medium">Delete “{ws.name}”?</p>
        <p className="mt-1 text-sm">
          This permanently removes its {plural(ws.documents, 'document')} and {plural(ws.chats, 'chat')}. It cannot be undone.
        </p>
        {remove.isError && <p className="mt-2 text-sm" role="alert">{(remove.error as Error).message}</p>}
        <div className="mt-3 flex gap-2">
          <Button size="sm" variant="ghost" onClick={() => setMode('view')}>Keep it</Button>
          <Button size="sm" variant="primary" className="bg-clash hover:bg-clash" loading={remove.isPending} onClick={() => remove.mutate()}>Delete workspace</Button>
        </div>
      </Card>
    )
  }
  return (
    <Card className="group relative transition hover:border-accent hover:shadow-pop">
      <button
        className="flex w-full items-start gap-3 p-4 pr-12 text-left"
        onClick={() => navigate(workspacePath(ws.workspace_id))}
        aria-label={`Open workspace ${ws.name}`}
      >
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent-ink"><FolderOpen className="h-5 w-5" /></span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="truncate font-medium">{ws.name}</span>
            {ws.demo && <Badge tone="accent">Demo</Badge>}
          </span>
          <span className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-sm text-muted">
            <span className="inline-flex items-center gap-1.5"><FileText className="h-3.5 w-3.5" />{plural(ws.documents, 'document')}</span>
            <span className="inline-flex items-center gap-1.5"><MessageSquare className="h-3.5 w-3.5" />{plural(ws.chats, 'chat')}</span>
          </span>
        </span>
      </button>
      <Dropdown.Root>
        <Dropdown.Trigger asChild>
          <button aria-label={`Options for ${ws.name}`} className="absolute right-3 top-3 rounded-md p-1.5 text-muted hover:bg-sunken data-[state=open]:bg-sunken">
            <MoreHorizontal className="h-4 w-4" />
          </button>
        </Dropdown.Trigger>
        <Dropdown.Portal>
          <Dropdown.Content align="end" className="z-50 min-w-40 rounded-xl border border-line bg-surface p-1 shadow-pop animate-fade-in">
            <Dropdown.Item onSelect={() => setMode('rename')} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm outline-none data-[highlighted]:bg-sunken">
              <Pencil className="h-4 w-4" /> Rename
            </Dropdown.Item>
            {!ws.demo && (
              <Dropdown.Item onSelect={() => setMode('confirm')} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-clash outline-none data-[highlighted]:bg-clash-soft">
                <Trash2 className="h-4 w-4" /> Delete
              </Dropdown.Item>
            )}
          </Dropdown.Content>
        </Dropdown.Portal>
      </Dropdown.Root>
    </Card>
  )
}

export function WorkspacesPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { data = [], isLoading } = useQuery(workspacesQuery)
  const [creating, setCreating] = useState(false)
  const create = useMutation({
    mutationFn: (name: string) => api.createWorkspace(name),
    onSuccess: async (ws) => {
      await qc.invalidateQueries({ queryKey: ['workspaces'] }) // the new workspace must be in the list before its pages open
      navigate(workspacePath(ws.workspace_id, '/library'))
    },
  })

  return (
    <PageShell
      title="Workspaces"
      subtitle="A workspace holds the documents for one matter and the chats about them. Answers, conflicts and amendment histories only ever use the documents of their own workspace."
      actions={!creating && <Button variant="primary" onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> New workspace</Button>}
    >
      {creating && (
        <Card className="mb-4 p-4">
          <p className="mb-2 text-sm font-medium">Name your workspace</p>
          <NameForm initial="" label="Workspace name" submit={(n) => create.mutate(n)} cancel={() => { setCreating(false); create.reset() }} busy={create.isPending} />
          {create.isError && <p className="mt-2 text-sm text-clash" role="alert">{(create.error as Error).message}</p>}
        </Card>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {isLoading && <><Skeleton className="h-24" /><Skeleton className="h-24" /></>}
        {data.map((ws) => <WorkspaceCard key={ws.workspace_id} ws={ws} />)}
      </div>
      {!isLoading && data.length === 0 && !creating && (
        <div className="rounded-2xl border border-line bg-surface px-6 py-12 text-center">
          <FolderOpen className="mx-auto mb-3 h-8 w-8 text-muted" aria-hidden />
          <p className="font-medium">Create your first workspace</p>
          <p className="mx-auto mt-1 max-w-sm text-sm text-muted">Add the documents for one matter, such as a loan agreement and its amendments, then ask questions about them.</p>
          <Button variant="primary" className="mt-4" onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> New workspace</Button>
        </div>
      )}
    </PageShell>
  )
}
