import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { PageViewer } from '@/panel/PageViewer'
import { Button } from './primitives'

export interface ViewSource {
  doc_id: string
  doc_name: string
  clause_label: string
  page: number
  pages: number | null
  bboxes: number[][]
  page_width: number | null
  page_height: number | null
  ocr?: boolean
}

/** A modal page viewer for screens without the chat side panel (Documents, Conflicts, Amendments). */
export function SourceDialog({ source, onClose }: { source: ViewSource | null; onClose: () => void }) {
  const [page, setPage] = useState(1)
  useEffect(() => { if (source) setPage(source.page) }, [source])
  return (
    <Dialog.Root open={Boolean(source)} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 animate-fade-in" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex h-[88vh] w-[min(92vw,720px)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-pop outline-none">
          {source && (
            <>
              <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
                <div className="min-w-0">
                  <Dialog.Title className="truncate font-medium">{source.doc_name}</Dialog.Title>
                  <Dialog.Description className="text-sm text-muted">{source.clause_label} · page {source.page}</Dialog.Description>
                </div>
                <Dialog.Close asChild><Button size="icon" variant="ghost" aria-label="Close"><X className="h-4 w-4" /></Button></Dialog.Close>
              </div>
              <PageViewer
                docId={source.doc_id}
                page={page}
                pages={source.pages}
                highlight={{ page: source.page, boxes: source.bboxes, width: source.page_width, height: source.page_height, ocr: source.ocr }}
                onPage={setPage}
              />
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
