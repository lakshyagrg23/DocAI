import { Check, Loader2 } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { StageEvent } from '@/lib/types'

const STEPS = [
  'Understanding your question',
  'Finding relevant passages',
  'Writing the answer',
  'Checking every statement against the documents',
  'Comparing documents for disagreements',
]

/** Live progress while the answer is produced. There is no typing effect on purpose: nothing is shown before it is verified. */
export function StageProgress({ stage }: { stage: StageEvent | null }) {
  const current = Math.max((stage?.step ?? 1) - 1, 0)
  return (
    <div className="animate-fade-in rounded-xl border border-line bg-surface p-4 shadow-card" role="status" aria-live="polite">
      <p className="mb-3 text-sm font-medium">{stage?.step === 0 ? 'Waiting for the model…' : 'Working on your answer…'}</p>
      <ol className="space-y-2">
        {STEPS.map((label, i) => {
          const done = i < current
          const active = i === current
          return (
            <li key={label} className={cn('flex items-center gap-3 text-sm', done ? 'text-muted' : active ? 'text-ink' : 'text-muted/60')}>
              <span className={cn('grid h-5 w-5 place-items-center rounded-full', done ? 'bg-ok-soft text-ok' : active ? 'bg-accent-soft text-accent-ink' : 'bg-sunken')}>
                {done ? <Check className="h-3 w-3" /> : active ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              </span>
              {label}
            </li>
          )
        })}
      </ol>
      <p className="mt-3 text-xs text-muted">Answers appear only after every statement has been checked, so this can take up to a minute.</p>
    </div>
  )
}
