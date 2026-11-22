import type {
  AmendmentsResponse, AskResult, Chat, ConflictsResponse, Doc, Example, Health, Message, OutlineClause, Source, StageEvent,
} from './types'

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : detail
    } catch { /* not JSON */ }
    throw new ApiError(detail, res.status)
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

export const api = {
  health: () => request<Health>('/health'),
  examples: () => request<Example[]>('/examples'),
  chats: () => request<Chat[]>('/chats'),
  createChat: () => request<Chat>('/chats', json('POST')),
  patchChat: (id: string, body: Partial<Pick<Chat, 'title' | 'as_of_date' | 'language'>>) =>
    request<Chat>(`/chats/${id}`, json('PATCH', body)),
  deleteChat: (id: string) => request<void>(`/chats/${id}`, json('DELETE')),
  messages: (id: string) => request<Message[]>(`/chats/${id}/messages`),
  documents: () => request<Doc[]>('/documents'),
  outline: (id: string, asOf?: string) => request<OutlineClause[]>(`/documents/${id}/outline${asOf ? `?as_of=${asOf}` : ''}`),
  upload: (files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return request<Doc[]>('/documents', { method: 'POST', body: form })
  },
  span: (id: string, asOf?: string) => request<Source>(`/spans/${encodeURIComponent(id)}${asOf ? `?as_of=${asOf}` : ''}`),
  conflicts: (asOf?: string) => request<ConflictsResponse>(`/conflicts${asOf ? `?as_of=${asOf}` : ''}`),
  amendments: (asOf?: string) => request<AmendmentsResponse>(`/amendments${asOf ? `?as_of=${asOf}` : ''}`),
  pageImageUrl: (docId: string, page: number, dpi = 130) => `/api/documents/${docId}/pages/${page}/image?dpi=${dpi}`,
}

/** Parse a server-sent-event stream body into (event, data) pairs. Exported for tests. */
export function parseSse(chunk: string): { event: string; data: unknown }[] {
  return chunk
    .split('\n\n')
    .map((b) => b.trim())
    .filter(Boolean)
    .map((block) => {
      const lines = block.split('\n')
      const event = lines.find((l) => l.startsWith('event: '))?.slice(7) ?? 'message'
      const data = lines.find((l) => l.startsWith('data: '))?.slice(6) ?? 'null'
      return { event, data: JSON.parse(data) }
    })
}

/** Ask a question. Resolves with the stored user + assistant messages; `onStage` reports live progress. */
export async function ask(chatId: string, question: string, onStage: (s: StageEvent) => void, signal?: AbortSignal): Promise<AskResult> {
  const res = await fetch(`/api/chats/${chatId}/ask`, { ...json('POST', { question }), signal })
  if (!res.ok || !res.body) throw new ApiError((await res.text()) || res.statusText, res.status)
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: AskResult | null = null
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const cut = buffer.lastIndexOf('\n\n')
    if (cut < 0) continue
    const ready = buffer.slice(0, cut + 2)
    buffer = buffer.slice(cut + 2)
    for (const ev of parseSse(ready)) {
      if (ev.event === 'stage') onStage(ev.data as StageEvent)
      else if (ev.event === 'answer') result = ev.data as AskResult
      else if (ev.event === 'error') throw new ApiError((ev.data as { message: string }).message, 500)
    }
  }
  if (!result) throw new ApiError('The answer did not arrive. Please try again.', 500)
  return result
}
