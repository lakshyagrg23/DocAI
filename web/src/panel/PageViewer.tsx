import { ChevronLeft, ChevronRight, ImageOff, Loader2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import type { Source } from '@/lib/types'
import { Button } from '@/ui/primitives'

interface Props {
  docId: string
  /** page being shown (1-based) */
  page: number
  pages: number | null
  /** highlight boxes (PDF points) and the size of the page they refer to; drawn only on the source's own page */
  highlight?: { page: number; boxes: number[][]; width: number | null; height: number | null; ocr?: boolean } | null
  onPage: (page: number) => void
}

/** The actual PDF page with the quote highlighted as a CSS overlay (crisp at any size, scrolls to the quote). */
export function PageViewer({ docId, page, pages, highlight, onPage }: Props) {
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const box = useRef<HTMLDivElement>(null)
  const show = highlight && highlight.page === page && highlight.width && highlight.height ? highlight : null

  useEffect(() => { setState('loading') }, [docId, page])

  const onLoad = () => {
    setState('ready')
    if (show && box.current) {
      const top = Math.min(...show.boxes.map((b) => b[1])) / (show.height as number)
      box.current.scrollTo({ top: Math.max(top * box.current.scrollHeight - 120, 0), behavior: 'smooth' })
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b border-line px-3 py-2 text-sm">
        <Button size="icon" variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page"><ChevronLeft className="h-4 w-4" /></Button>
        <span className="num text-muted">Page {page}{pages ? ` of ${pages}` : ''}</span>
        <Button size="icon" variant="ghost" disabled={Boolean(pages) && page >= (pages as number)} onClick={() => onPage(page + 1)} aria-label="Next page"><ChevronRight className="h-4 w-4" /></Button>
      </div>
      <div ref={box} className="relative min-h-0 flex-1 overflow-auto bg-sunken p-3">
        {state === 'loading' && <div className="absolute inset-0 grid place-items-center text-muted"><Loader2 className="h-5 w-5 animate-spin" aria-label="Loading page" /></div>}
        {state === 'error' && (
          <div className="grid h-full place-items-center text-center text-sm text-muted">
            <div><ImageOff className="mx-auto mb-2 h-6 w-6" />The original page is not available on this server.</div>
          </div>
        )}
        <div className="relative mx-auto w-full max-w-[640px] overflow-hidden rounded-md bg-white shadow-card" hidden={state === 'error'}>
          <img
            key={`${docId}-${page}`}
            src={api.pageImageUrl(docId, page)}
            alt={`Page ${page} of the document`}
            onLoad={onLoad}
            onError={() => setState('error')}
            className="block w-full select-none"
            draggable={false}
          />
          {state === 'ready' && show?.boxes.map((b, i) => (
            <span
              key={i}
              aria-hidden
              className="absolute rounded-sm mix-blend-multiply"
              style={{
                left: `${(b[0] / (show.width as number)) * 100}%`,
                top: `${(b[1] / (show.height as number)) * 100}%`,
                width: `${((b[2] - b[0]) / (show.width as number)) * 100}%`,
                height: `${((b[3] - b[1]) / (show.height as number)) * 100}%`,
                background: show.ocr ? 'rgb(251 146 60 / 0.4)' : 'rgb(250 204 21 / 0.5)',
                outline: `1.5px solid ${show.ocr ? 'rgb(234 88 12 / 0.7)' : 'rgb(202 138 4 / 0.7)'}`,
              }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

export const highlightOf = (s: Source) => ({ page: s.page, boxes: s.bboxes, width: s.page_width, height: s.page_height, ocr: s.ocr })
