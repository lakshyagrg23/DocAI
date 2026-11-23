import { ArrowUp, CalendarDays } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Tooltip } from '@/ui/primitives'
import { cn } from '@/lib/cn'
import { fmtDate } from '@/lib/plain'
import { ScopeMenu } from './ScopeMenu'

interface Props {
  onSend: (question: string) => void
  busy: boolean
  asOf: string
  onAsOf: (iso: string) => void
  today: string
  offline?: boolean
  autoFocus?: boolean
  scope: string[] | null
  onScope: (scope: string[] | null) => void
}

export function Composer({ onSend, busy, asOf, onAsOf, today, offline, autoFocus, scope, onScope }: Props) {
  const [text, setText] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
    el.style.overflowY = el.scrollHeight > 200 ? 'auto' : 'hidden'
  }, [text])
  useEffect(() => { if (autoFocus) ref.current?.focus() }, [autoFocus])

  const send = () => {
    const q = text.trim()
    if (!q || busy) return
    onSend(q)
    setText('')
  }
  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-4">
      {offline && <p className="mb-2 rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">The model is warming up or offline, so answers may fail for a few minutes. Your documents are still available.</p>}
      <div className="rounded-2xl border border-line bg-surface shadow-card transition-colors focus-within:border-accent">
        <textarea
          ref={ref}
          value={text}
          rows={1}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() } }}
          placeholder="Ask a question about your documents…"
          aria-label="Your question"
          className="block max-h-[200px] w-full resize-none overflow-y-auto bg-transparent px-4 pb-1 pt-3.5 text-[15px] outline-none placeholder:text-muted focus-visible:ring-0 focus-visible:ring-offset-0"
        />
        <div className="flex items-center justify-between px-3 pb-2.5">
          <Tooltip content="Answers use the rules as they applied on this date. Change it to see an older or future rule.">
            <label className={cn('flex cursor-pointer items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted hover:bg-sunken', asOf !== today && 'bg-accent-soft text-accent-ink')}>
              <CalendarDays className="h-3.5 w-3.5" />
              {asOf === today ? 'Rules as of today' : `Rules as of ${fmtDate(asOf)}`}
              <input type="date" value={asOf} onChange={(e) => e.target.value && onAsOf(e.target.value)} aria-label="Rules as of date" className="sr-only" />
            </label>
          </Tooltip>
          <div className="flex-1" />
          <ScopeMenu scope={scope} onChange={onScope} />
          <button
            type="button"
            onClick={send}
            disabled={!text.trim() || busy}
            aria-label="Send question"
            className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-white transition-opacity disabled:opacity-30 dark:text-bg"
          >
            <ArrowUp className="h-4 w-4" />
          </button>
        </div>
      </div>
      <p className="mt-2 text-center text-xs text-muted">Every statement is checked against your documents before it is shown. Press Enter to send.</p>
    </div>
  )
}
