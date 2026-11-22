import { cn } from '@/lib/cn'
import { snippet } from '@/lib/plain'
import type { Answer } from '@/lib/types'
import { useUi } from '@/state/ui'
import { Tooltip } from '@/ui/primitives'

/** A numbered citation [1]. Hover: where it comes from and the exact words. Click: opens the page in the side panel. */
export function CitationChip({ answer, spanId }: { answer: Answer; spanId: string }) {
  const { openSource, panel } = useUi()
  const src = answer.sources[spanId]
  if (!src) return null
  const active = panel.open && panel.answer === answer && panel.selected === spanId
  return (
    <Tooltip
      content={
        <div className="space-y-1">
          <p className="font-medium">{src.doc_name}</p>
          <p className="text-xs text-muted">{src.clause_label} · page {src.page}</p>
          <p className="text-xs italic text-muted">“{snippet(src.row ? Object.values(src.row).join(' · ') : src.text, 140)}”</p>
        </div>
      }
    >
      <button
        type="button"
        onClick={() => openSource(answer, spanId)}
        aria-label={`Source ${src.n}: ${src.doc_name}, ${src.clause_label}, page ${src.page}`}
        className={cn(
          'num mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md px-1 align-text-top text-[11px] font-semibold transition-colors',
          active ? 'bg-accent text-white dark:text-bg' : 'bg-accent-soft text-accent-ink hover:bg-accent hover:text-white dark:hover:text-bg',
        )}
      >
        {src.n}
      </button>
    </Tooltip>
  )
}
