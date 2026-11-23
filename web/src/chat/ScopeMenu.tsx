import { useQuery } from '@tanstack/react-query'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import { Check, FileText } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'

interface Props {
  /** The workspace whose documents can be chosen. */
  workspaceId: string
  /** Selected document ids; null means every document. */
  scope: string[] | null
  onChange: (scope: string[] | null) => void
}

/** Lets the user narrow a chat to some documents of its workspace. Nothing selected = every document in the workspace. */
export function ScopeMenu({ workspaceId, scope, onChange }: Props) {
  const { data: docs = [] } = useQuery({ queryKey: ['documents', workspaceId], queryFn: () => api.documents(workspaceId) })
  const ready = docs.filter((d) => d.status === 'Ready')
  const chosen = new Set(scope ?? [])
  const label = !scope || scope.length === 0 ? 'All documents' : `${scope.length} of ${ready.length} documents`

  const toggle = (id: string) => {
    const next = new Set(chosen.size ? chosen : ready.map((d) => d.doc_id))
    if (next.has(id)) next.delete(id)
    else next.add(id)
    if (next.size === 0) return // at least one document must stay selected
    onChange(next.size === ready.length ? null : ready.map((d) => d.doc_id).filter((d) => next.has(d)))
  }

  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <button
          aria-label="Choose which documents this chat uses"
          className={cn('flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted hover:bg-sunken', scope && scope.length > 0 && 'bg-accent-soft text-accent-ink')}
        >
          <FileText className="h-3.5 w-3.5" /> {label}
        </button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align="end" className="z-50 max-h-80 min-w-64 overflow-y-auto rounded-xl border border-line bg-surface p-1 shadow-pop animate-fade-in">
          <p className="px-3 py-2 text-xs text-muted">Answers in this chat use only the ticked documents.</p>
          {ready.map((d) => {
            const on = chosen.size === 0 || chosen.has(d.doc_id)
            return (
              <Dropdown.CheckboxItem
                key={d.doc_id}
                checked={on}
                onSelect={(e) => { e.preventDefault(); toggle(d.doc_id) }}
                className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm outline-none data-[highlighted]:bg-sunken"
              >
                <span className={cn('grid h-4 w-4 shrink-0 place-items-center rounded border', on ? 'border-accent bg-accent text-white dark:text-bg' : 'border-line')}>
                  {on && <Check className="h-3 w-3" />}
                </span>
                <span className="min-w-0"><span className="block truncate">{d.name}</span><span className="block truncate text-xs text-muted">{d.sub}</span></span>
              </Dropdown.CheckboxItem>
            )
          })}
          {scope && scope.length > 0 && (
            <Dropdown.Item onSelect={() => onChange(null)} className="mt-1 cursor-pointer rounded-lg px-3 py-2 text-sm text-accent-ink outline-none data-[highlighted]:bg-sunken">
              Use all documents
            </Dropdown.Item>
          )}
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  )
}
