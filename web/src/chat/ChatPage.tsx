import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, PanelLeftOpen, ShieldCheck, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, ask } from '@/lib/api'
import { localToday } from '@/lib/plain'
import type { Example, Message, StageEvent } from '@/lib/types'
import { useUi } from '@/state/ui'
import { Button, Skeleton } from '@/ui/primitives'
import { AnswerCard } from './AnswerCard'
import { Composer } from './Composer'
import { StageProgress } from './StageProgress'

function EmptyState({ examples, onPick }: { examples: Example[]; onPick: (q: string) => void }) {
  return (
    <div className="mx-auto flex max-w-3xl flex-col items-center px-4 pt-[12vh] text-center animate-fade-in">
      <span className="mb-5 grid h-12 w-12 place-items-center rounded-2xl bg-accent text-white dark:text-bg"><ShieldCheck className="h-6 w-6" /></span>
      <h1 className="text-2xl font-semibold tracking-tight">What would you like to verify?</h1>
      <p className="mt-2 max-w-xl text-muted">
        Ask about your documents. You get an answer only when it can be proven from them, with the exact page and wording shown.
        When documents disagree, you see both sides.
      </p>
      <div className="mt-8 grid w-full gap-3 sm:grid-cols-3">
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
    </div>
  )
}

export function ChatPage() {
  const { chatId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { sidebarOpen, setSidebarOpen } = useUi()
  const today = localToday()
  const [pending, setPending] = useState<string | null>(null)
  const [stage, setStage] = useState<StageEvent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [draftAsOf, setDraftAsOf] = useState(today)
  const bottom = useRef<HTMLDivElement>(null)

  const { data: chats = [] } = useQuery({ queryKey: ['chats'], queryFn: api.chats })
  const chat = chats.find((c) => c.chat_id === chatId)
  const messages = useQuery({ queryKey: ['messages', chatId], queryFn: () => api.messages(chatId!), enabled: Boolean(chatId) })
  const { data: examples = [] } = useQuery({ queryKey: ['examples'], queryFn: api.examples, staleTime: Infinity })
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15_000 })
  const asOf = chat?.as_of_date ?? draftAsOf

  const run = async (id: string, question: string) => {
    setPending(question)
    setError(null)
    setStage(null)
    try {
      const res = await ask(id, question, setStage)
      qc.setQueryData<Message[]>(['messages', id], (old) => [...(old ?? []), res.user, res.assistant])
      void qc.invalidateQueries({ queryKey: ['chats'] })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong. Please try again.')
    } finally {
      setPending(null)
      setStage(null)
    }
  }

  const submit = async (question: string) => {
    if (chatId) return run(chatId, question)
    const c = await api.createChat()
    if (draftAsOf !== today) await api.patchChat(c.chat_id, { as_of_date: draftAsOf })
    await qc.invalidateQueries({ queryKey: ['chats'] })
    navigate(`/chat/${c.chat_id}`, { state: { ask: question } })
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
    void qc.invalidateQueries({ queryKey: ['chats'] })
  }

  const list = messages.data ?? []
  const empty = !pending && list.length === 0 && !messages.isLoading

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-4">
        {!sidebarOpen && <Button size="icon" variant="ghost" onClick={() => setSidebarOpen(true)} aria-label="Open sidebar"><PanelLeftOpen className="h-5 w-5" /></Button>}
        <h1 className="truncate text-sm font-medium">{chat?.title ?? 'New chat'}</h1>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {messages.isLoading && chatId && <div className="mx-auto max-w-3xl space-y-4 p-6"><Skeleton className="h-10 w-2/3" /><Skeleton className="h-32 w-full" /></div>}
        {empty && <EmptyState examples={examples} onPick={(q) => void submit(q)} />}
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

      <Composer onSend={(q) => void submit(q)} busy={Boolean(pending)} asOf={asOf} onAsOf={(d) => void changeAsOf(d)} today={today}
        offline={health?.state === 'offline'} autoFocus />
    </div>
  )
}
