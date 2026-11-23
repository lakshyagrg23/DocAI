import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Download, FileText, PanelLeftOpen, ShieldCheck, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, ask } from '@/lib/api'
import { localToday } from '@/lib/plain'
import type { Example, Message, StageEvent, Workspace } from '@/lib/types'
import { useUi } from '@/state/ui'
import { useWorkspace, useWorkspaceId, workspacePath } from '@/state/workspace'
import { Button, Skeleton } from '@/ui/primitives'
import { AnswerCard } from './AnswerCard'
import { Composer } from './Composer'
import { StageProgress } from './StageProgress'

function EmptyState({ workspace, examples, onPick }: { workspace: Workspace | undefined; examples: Example[]; onPick: (q: string) => void }) {
  const noDocs = workspace !== undefined && workspace.documents === 0
  return (
    <div className="mx-auto flex max-w-3xl flex-col items-center px-4 pt-[12vh] text-center animate-fade-in">
      <span className="mb-5 grid h-12 w-12 place-items-center rounded-2xl bg-accent text-white dark:text-bg"><ShieldCheck className="h-6 w-6" /></span>
      <h1 className="text-2xl font-semibold tracking-tight">{noDocs ? 'Add documents to get started' : 'What would you like to verify?'}</h1>
      {noDocs ? (
        <>
          <p className="mt-2 max-w-xl text-muted">
            {workspace.name} has no documents yet. Add the PDFs for this matter, and you can ask questions about them here.
            Chats in this workspace only use its own documents.
          </p>
          <Link to={workspacePath(workspace.workspace_id, '/library')} className="mt-6 inline-flex h-10 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-medium text-white hover:bg-accent-ink dark:text-bg">
            <FileText className="h-4 w-4" /> Add documents
          </Link>
        </>
      ) : (
        <p className="mt-2 max-w-xl text-muted">
          Ask about the documents in {workspace ? <strong className="font-medium text-ink">{workspace.name}</strong> : 'this workspace'}. You get an answer only when it can be proven from them, with the exact page and wording shown.
          When documents disagree, you see both sides.
        </p>
      )}
      {!noDocs && workspace?.demo && (
        <div className="mt-8 grid w-full gap-3 sm:grid-cols-2">
          {examples.map((e) => (
            <button
              key={e.question}
              onClick={() => onPick(e.question)}
              className="group rounded-xl border border-line bg-surface p-4 text-left shadow-card transition hover:border-accent hover:shadow-pop"
            >
              <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-accent-ink"><Sparkles className="h-3.5 w-3.5" />{e.title}</p>
              <p className="text-sm font-medium leading-snug">{e.question}</p>
              <p className="mt-2 text-xs text-muted">{e.hint}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function ChatPage() {
  const { chatId } = useParams()
  const wid = useWorkspaceId()
  const workspace = useWorkspace()
  const location = useLocation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { sidebarOpen, setSidebarOpen } = useUi()
  const today = localToday()
  const [pending, setPending] = useState<string | null>(null)
  const [stage, setStage] = useState<StageEvent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [draftAsOf, setDraftAsOf] = useState(today)
  const [draftScope, setDraftScope] = useState<string[] | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const chatsQuery = useQuery({ queryKey: ['chats', wid], queryFn: () => api.chats(wid) })
  const chats = chatsQuery.data ?? []
  const chat = chats.find((c) => c.chat_id === chatId)
  // Only chats of this workspace are opened: a chat id from another workspace in the address bar goes back to the start screen.
  const messages = useQuery({ queryKey: ['messages', chatId], queryFn: () => api.messages(chatId!), enabled: Boolean(chatId) && Boolean(chat) })
  useEffect(() => {
    if (chatId && chatsQuery.isSuccess && !chat) navigate(workspacePath(wid), { replace: true })
  }, [chatId, chat, chatsQuery.isSuccess, wid, navigate])
  const loadingChat = Boolean(chatId) && (chatsQuery.isLoading || messages.isLoading)
  const { data: examples = [] } = useQuery({ queryKey: ['examples'], queryFn: api.examples, staleTime: Infinity })
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15_000 })
  const asOf = chat?.as_of_date ?? draftAsOf
  const scope = chat ? chat.doc_scope : draftScope

  const run = async (id: string, question: string) => {
    setPending(question)
    setError(null)
    setStage(null)
    try {
      const res = await ask(id, question, setStage)
      qc.setQueryData<Message[]>(['messages', id], (old) => [...(old ?? []), res.user, res.assistant])
      void qc.invalidateQueries({ queryKey: ['chats', wid] })
      void qc.invalidateQueries({ queryKey: ['workspaces'] })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong. Please try again.')
    } finally {
      setPending(null)
      setStage(null)
    }
  }

  const submit = async (question: string) => {
    if (chatId) return run(chatId, question)
    const c = await api.createChat(wid)
    if (draftAsOf !== today || draftScope) {
      await api.patchChat(c.chat_id, { ...(draftAsOf !== today && { as_of_date: draftAsOf }), ...(draftScope && { doc_scope: draftScope }) })
    }
    await qc.invalidateQueries({ queryKey: ['chats', wid] })
    void qc.invalidateQueries({ queryKey: ['workspaces'] })
    navigate(workspacePath(wid, `/chat/${c.chat_id}`), { state: { ask: question } })
  }

  // A question typed on the empty screen is asked once the new chat has loaded.
  const asked = useRef<string | null>(null)
  useEffect(() => {
    const q = (location.state as { ask?: string } | null)?.ask
    if (q && chatId && asked.current !== `${chatId}:${q}`) {
      asked.current = `${chatId}:${q}`
      navigate(location.pathname, { replace: true, state: null })
      void run(chatId, q)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, location.state])

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [messages.data?.length, pending, error])

  const changeAsOf = async (iso: string) => {
    if (!chatId) return setDraftAsOf(iso)
    await api.patchChat(chatId, { as_of_date: iso })
    void qc.invalidateQueries({ queryKey: ['chats', wid] })
  }

  const changeScope = async (next: string[] | null) => {
    if (!chatId) return setDraftScope(next)
    await api.patchChat(chatId, { doc_scope: next ?? [] })
    void qc.invalidateQueries({ queryKey: ['chats', wid] })
  }

  const list = messages.data ?? []
  const empty = !pending && list.length === 0 && !loadingChat

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-4">
        {!sidebarOpen && <Button size="icon" variant="ghost" onClick={() => setSidebarOpen(true)} aria-label="Open sidebar"><PanelLeftOpen className="h-5 w-5" /></Button>}
        <h1 className="min-w-0 flex-1 truncate text-sm font-medium">
          {workspace && <span className="font-normal text-muted">{workspace.name} / </span>}
          {chat?.title ?? 'New chat'}
        </h1>
        {chatId && list.length > 0 && (
          <a href={api.exportUrl(chatId)} download className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted hover:bg-sunken" aria-label="Download this chat as Markdown">
            <Download className="h-3.5 w-3.5" /> Export
          </a>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loadingChat && <div className="mx-auto max-w-3xl space-y-4 p-6"><Skeleton className="h-10 w-2/3" /><Skeleton className="h-32 w-full" /></div>}
        {empty && <EmptyState workspace={workspace} examples={examples} onPick={(q) => void submit(q)} />}
        <div className="mx-auto max-w-3xl space-y-8 px-4 py-6">
          {list.map((m) => m.role === 'user' ? (
            <div key={m.msg_id} className="flex justify-end">
              <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent-soft px-4 py-2.5 text-[15px] text-ink">{m.content}</p>
            </div>
          ) : m.answer ? <AnswerCard key={m.msg_id} answer={m.answer} /> : <p key={m.msg_id}>{m.content}</p>)}
          {pending && (
            <>
              <div className="flex justify-end"><p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent-soft px-4 py-2.5 text-[15px]">{pending}</p></div>
              <StageProgress stage={stage} />
            </>
          )}
          {error && (
            <div className="flex items-start gap-3 rounded-xl border border-clash/30 bg-clash-soft px-4 py-3 text-sm text-clash" role="alert">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /> <span>{error}</span>
            </div>
          )}
          <div ref={bottom} />
        </div>
      </div>

      <Composer workspaceId={wid} onSend={(q) => void submit(q)} busy={Boolean(pending)} asOf={asOf} onAsOf={(d) => void changeAsOf(d)} today={today}
        offline={health?.state === 'offline'} autoFocus scope={scope} onScope={(s) => void changeScope(s)} />
    </div>
  )
}
