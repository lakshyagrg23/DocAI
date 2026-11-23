import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as Dropdown from '@radix-ui/react-dropdown-menu'
import {
  BookOpen, Check, ChevronsUpDown, FolderOpen, GitCompareArrows, History, LayoutGrid, MoreHorizontal, Moon, PanelLeftClose, PanelLeftOpen,
  Pencil, Plus, Search, ShieldCheck, Sun, Trash2,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { NavLink, useMatch, useNavigate } from 'react-router-dom'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { groupByDay } from '@/lib/plain'
import type { Chat } from '@/lib/types'
import { useUi } from '@/state/ui'
import { workspacePath, workspacesQuery } from '@/state/workspace'
import { Button, Tooltip } from '@/ui/primitives'

/** Pages of the open workspace. */
const navFor = (wid: string) => [
  { to: workspacePath(wid, '/library'), label: 'Documents', icon: BookOpen },
  { to: workspacePath(wid, '/conflicts'), label: 'Conflicts', icon: GitCompareArrows },
  { to: workspacePath(wid, '/amendments'), label: 'Amendments', icon: History },
]

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  cn('flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted hover:bg-sunken hover:text-ink', isActive && 'bg-sunken font-medium text-ink')

function ModelStatus({ compact }: { compact?: boolean }) {
  const { data, isLoading } = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15_000 })
  const state = isLoading ? 'checking' : (data?.state ?? 'offline')
  const dot = state === 'ready' ? 'bg-ok' : state === 'offline' ? 'bg-clash' : state === 'asleep' ? 'bg-calm' : 'bg-warn'
  const text = state === 'ready' ? 'Model ready' : state === 'warming' ? 'Model warming up' : state === 'asleep' ? 'Model asleep: your first question wakes it' : state === 'checking' ? 'Checking model…' : 'Model offline'
  return (
    <Tooltip content={text} side="right">
      <div className="flex items-center gap-2 text-xs text-muted" role="status" aria-label={text}>
        <span className={cn('h-2 w-2 rounded-full', dot, (state === 'warming' || state === 'checking') && 'animate-pulse2')} />
        {!compact && text}
      </div>
    </Tooltip>
  )
}

/** Shows the open workspace and switches to another one. Chats and documents below it belong to it alone. */
function WorkspaceSwitcher({ workspaceId }: { workspaceId: string | null }) {
  const navigate = useNavigate()
  const { data: workspaces = [] } = useQuery(workspacesQuery)
  const current = workspaces.find((w) => w.workspace_id === workspaceId)
  return (
    <Dropdown.Root>
      <Dropdown.Trigger asChild>
        <button
          aria-label="Switch workspace"
          className="flex h-11 w-full items-center gap-2.5 rounded-lg border border-line bg-bg px-3 text-left text-sm hover:bg-sunken data-[state=open]:border-accent"
        >
          <FolderOpen className="h-4 w-4 shrink-0 text-accent-ink" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block text-[11px] leading-none text-muted">Workspace</span>
            <span className="block truncate font-medium leading-tight">{current?.name ?? (workspaceId ? 'Loading…' : 'None selected')}</span>
          </span>
          <ChevronsUpDown className="h-4 w-4 shrink-0 text-muted" aria-hidden />
        </button>
      </Dropdown.Trigger>
      <Dropdown.Portal>
        <Dropdown.Content align="start" className="z-50 max-h-80 w-64 overflow-y-auto rounded-xl border border-line bg-surface p-1 shadow-pop animate-fade-in">
          {workspaces.map((w) => (
            <Dropdown.Item
              key={w.workspace_id}
              onSelect={() => navigate(workspacePath(w.workspace_id))}
              className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm outline-none data-[highlighted]:bg-sunken"
            >
              <span className="min-w-0 flex-1 truncate">{w.name}</span>
              {w.workspace_id === workspaceId && <Check className="h-4 w-4 text-accent-ink" aria-label="Current workspace" />}
            </Dropdown.Item>
          ))}
          {workspaces.length > 0 && <Dropdown.Separator className="my-1 h-px bg-line" />}
          <Dropdown.Item onSelect={() => navigate('/workspaces')} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm outline-none data-[highlighted]:bg-sunken">
            <LayoutGrid className="h-4 w-4" /> All workspaces
          </Dropdown.Item>
        </Dropdown.Content>
      </Dropdown.Portal>
    </Dropdown.Root>
  )
}

function ChatRow({ chat, workspaceId, active }: { chat: Chat; workspaceId: string; active: boolean }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'view' | 'rename' | 'confirm'>('view')
  const [title, setTitle] = useState(chat.title)
  const rename = useMutation({
    mutationFn: (t: string) => api.patchChat(chat.chat_id, { title: t }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chats', workspaceId] }),
  })
  const remove = useMutation({
    mutationFn: () => api.deleteChat(chat.chat_id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['chats', workspaceId] })
      qc.invalidateQueries({ queryKey: ['workspaces'] })
      if (active) navigate(workspacePath(workspaceId))
    },
  })

  if (mode === 'rename') {
    return (
      <form
        className="px-1"
        onSubmit={(e) => { e.preventDefault(); if (title.trim()) rename.mutate(title.trim()); setMode('view') }}
      >
        <input
          autoFocus
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => setMode('view')}
          onKeyDown={(e) => e.key === 'Escape' && setMode('view')}
          aria-label="Chat name"
          className="h-9 w-full rounded-lg border border-accent bg-surface px-3 text-sm outline-none"
        />
      </form>
    )
  }
  if (mode === 'confirm') {
    return (
      <div className="flex items-center justify-between gap-2 rounded-lg bg-clash-soft px-3 py-1.5 text-sm text-clash">
        <span>Delete this chat?</span>
        <span className="flex gap-1">
          <Button size="sm" variant="ghost" onClick={() => setMode('view')}>Keep</Button>
          <Button size="sm" variant="primary" className="bg-clash hover:bg-clash" onClick={() => remove.mutate()}>Delete</Button>
        </span>
      </div>
    )
  }
  return (
    <div className={cn('group relative flex items-center rounded-lg', active ? 'bg-sunken' : 'hover:bg-sunken/70')}>
      <NavLink to={workspacePath(workspaceId, `/chat/${chat.chat_id}`)} className="min-w-0 flex-1 truncate px-3 py-2 text-sm" title={chat.title}>
        {chat.title}
      </NavLink>
      <Dropdown.Root>
        <Dropdown.Trigger asChild>
          <button
            aria-label={`Options for ${chat.title}`}
            className="mr-1 rounded-md p-1 text-muted opacity-0 hover:bg-line focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100"
          >
            <MoreHorizontal className="h-4 w-4" />
          </button>
        </Dropdown.Trigger>
        <Dropdown.Portal>
          <Dropdown.Content align="end" className="z-50 min-w-36 rounded-xl border border-line bg-surface p-1 shadow-pop animate-fade-in">
            <Dropdown.Item onSelect={() => { setTitle(chat.title); setMode('rename') }} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm outline-none data-[highlighted]:bg-sunken">
              <Pencil className="h-4 w-4" /> Rename
            </Dropdown.Item>
            <Dropdown.Item onSelect={() => setMode('confirm')} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-clash outline-none data-[highlighted]:bg-clash-soft">
              <Trash2 className="h-4 w-4" /> Delete
            </Dropdown.Item>
          </Dropdown.Content>
        </Dropdown.Portal>
      </Dropdown.Root>
    </div>
  )
}

export function Sidebar() {
  const { sidebarOpen, toggleSidebar, theme, toggleTheme } = useUi()
  const navigate = useNavigate()
  // The sidebar sits above the workspace routes, so it reads the workspace from the URL itself.
  const inWorkspace = useMatch('/w/:workspaceId/*')
  const chatMatch = useMatch('/w/:workspaceId/chat/:chatId')
  const wid = inWorkspace?.params.workspaceId ?? null
  const [query, setQuery] = useState('')
  const { data: chats = [] } = useQuery({ queryKey: ['chats', wid], queryFn: () => api.chats(wid!), enabled: Boolean(wid) })
  const groups = useMemo(
    () => groupByDay(chats.filter((c) => c.title.toLowerCase().includes(query.toLowerCase())) as (Chat & { created_at: string })[]),
    [chats, query],
  )
  const nav = wid ? navFor(wid) : []

  if (!sidebarOpen) {
    return (
      <aside className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-line bg-surface py-3" aria-label="Sidebar (collapsed)">
        <Tooltip content="Open sidebar" side="right"><Button size="icon" variant="ghost" onClick={toggleSidebar} aria-label="Open sidebar"><PanelLeftOpen className="h-5 w-5" /></Button></Tooltip>
        <Tooltip content="All workspaces" side="right">
          <NavLink to="/workspaces" aria-label="All workspaces" className={({ isActive }) => cn('rounded-lg p-2 text-muted hover:bg-sunken hover:text-ink', isActive && 'bg-sunken text-ink')}>
            <LayoutGrid className="h-5 w-5" />
          </NavLink>
        </Tooltip>
        {wid && <Tooltip content="New chat" side="right"><Button size="icon" variant="ghost" onClick={() => navigate(workspacePath(wid))} aria-label="New chat"><Plus className="h-5 w-5" /></Button></Tooltip>}
        <div className="my-2 h-px w-6 bg-line" />
        {nav.map(({ to, label, icon: Icon }) => (
          <Tooltip key={to} content={label} side="right">
            <NavLink to={to} aria-label={label} className={({ isActive }) => cn('rounded-lg p-2 text-muted hover:bg-sunken hover:text-ink', isActive && 'bg-sunken text-ink')}>
              <Icon className="h-5 w-5" />
            </NavLink>
          </Tooltip>
        ))}
        <div className="mt-auto flex flex-col items-center gap-3">
          <ModelStatus compact />
          <Button size="icon" variant="ghost" onClick={toggleTheme} aria-label="Toggle dark mode">{theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}</Button>
        </div>
      </aside>
    )
  }

  return (
    <aside className="flex w-72 shrink-0 flex-col border-r border-line bg-surface" aria-label="Sidebar">
      <div className="flex items-center justify-between px-4 pb-2 pt-4">
        <div className="flex items-center gap-2 font-semibold tracking-tight">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-white dark:text-bg"><ShieldCheck className="h-4 w-4" /></span>
          DocAI
        </div>
        <Tooltip content="Close sidebar"><Button size="icon" variant="ghost" onClick={toggleSidebar} aria-label="Close sidebar"><PanelLeftClose className="h-5 w-5" /></Button></Tooltip>
      </div>
      <p className="px-4 pb-3 text-xs text-muted">Answers only with proof.</p>

      <div className="space-y-2 px-3">
        <WorkspaceSwitcher workspaceId={wid} />
        {wid && (
          <>
            <Button variant="secondary" className="w-full justify-start" onClick={() => navigate(workspacePath(wid))}><Plus className="h-4 w-4" /> New chat</Button>
            <label className="relative block">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search chats"
                aria-label="Search chats"
                className="h-9 w-full rounded-lg border border-line bg-bg pl-9 pr-3 text-sm outline-none placeholder:text-muted focus:border-accent"
              />
            </label>
          </>
        )}
      </div>

      <nav className="mt-3 flex-1 space-y-4 overflow-y-auto px-3 pb-3" aria-label="Chat history">
        {!wid && <p className="px-3 py-6 text-center text-sm text-muted">Pick a workspace to see its chats and documents.</p>}
        {wid && groups.length === 0 && <p className="px-3 py-6 text-center text-sm text-muted">{query ? 'No chats match your search.' : 'Chats in this workspace will appear here.'}</p>}
        {wid && groups.map(([label, items]) => (
          <div key={label}>
            <p className="px-3 pb-1 text-xs font-semibold text-muted">{label}</p>
            <div className="space-y-0.5">
              {(items as Chat[]).map((c) => <ChatRow key={c.chat_id} chat={c} workspaceId={wid} active={chatMatch?.params.chatId === c.chat_id} />)}
            </div>
          </div>
        ))}
      </nav>

      <div className="space-y-1 border-t border-line p-3">
        {nav.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} className={navLinkClass}>
            <Icon className="h-4 w-4" /> {label}
          </NavLink>
        ))}
        <NavLink to="/workspaces" className={navLinkClass}><LayoutGrid className="h-4 w-4" /> All workspaces</NavLink>
        <div className="flex items-center justify-between px-3 pt-2">
          <ModelStatus />
          <Tooltip content={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
            <Button size="icon" variant="ghost" onClick={toggleTheme} aria-label="Toggle dark mode">{theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</Button>
          </Tooltip>
        </div>
      </div>
    </aside>
  )
}
