import type {
  AmendmentsResponse, AskResult, Chat, ConflictsResponse, Doc, Example, Health, Message, OutlineClause, Source, StageEvent, Workspace,
} from './types'

/** Fired when any request is answered with 401 (the access code is missing or expired), so the gate can ask again. */
export const AUTH_EVENT = 'docai-auth'

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message)
  }
}

async function failure(res: Response, path: string): Promise<ApiError> {
  let detail = res.statusText
  try {
    const body = await res.json()
    detail = typeof body.detail === 'string' ? body.detail : detail
  } catch { /* not JSON */ }
  if (res.status === 401 && path !== '/login' && path !== '/session') window.dispatchEvent(new Event(AUTH_EVENT))
  return new ApiError(detail, res.status)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init)
  if (!res.ok) throw await failure(res, path)
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

export const api = {
  session: () => request<{ required: boolean; ok: boolean }>('/session'),
  login: (code: string) => request<{ ok: boolean }>('/login', json('POST', { code })),
  health: () => request<Health>('/health'),
  examples: () => request<Example[]>('/examples'),
  workspaces: () => request<Workspace[]>('/workspaces'),
  createWorkspace: (name: string) => request<Workspace>('/workspaces', json('POST', { name })),
  renameWorkspace: (id: string, name: string) => request<Workspace>(`/workspaces/${id}`, json('PATCH', { name })),
  deleteWorkspace: (id: string) => request<void>(`/workspaces/${id}`, json('DELETE')),
  chats: (workspaceId: string) => request<Chat[]>(`/chats?workspace_id=${encodeURIComponent(workspaceId)}`),
  createChat: (workspaceId: string) => request<Chat>('/chats', json('POST', { workspace_id: workspaceId })),
  patchChat: (id: string, body: Partial<Pick<Chat, 'title' | 'as_of_date' | 'language'>> & { doc_scope?: string[] }) =>
    request<Chat>(`/chats/${id}`, json('PATCH', body)),
  exportUrl: (id: string) => `/api/chats/${id}/export`,
  deleteChat: (id: string) => request<void>(`/chats/${id}`, json('DELETE')),
  messages: (id: string) => request<Message[]>(`/chats/${id}/messages`),
  documents: (workspaceId: string) => request<Doc[]>(`/documents?workspace_id=${encodeURIComponent(workspaceId)}`),
  outline: (id: string, asOf?: string) => request<OutlineClause[]>(`/documents/${id}/outline${asOf ? `?as_of=${asOf}` : ''}`),
  upload: (workspaceId: string, files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return request<Doc[]>(`/documents?workspace_id=${encodeURIComponent(workspaceId)}`, { method: 'POST', body: form })
  },
  span: (id: string, asOf?: string) => request<Source>(`/spans/${encodeURIComponent(id)}${asOf ? `?as_of=${asOf}` : ''}`),
  conflicts: (workspaceId: string, asOf?: string) =>
    request<ConflictsResponse>(`/conflicts?workspace_id=${encodeURIComponent(workspaceId)}${asOf ? `&as_of=${asOf}` : ''}`),
  amendments: (workspaceId: string, asOf?: string) =>
    request<AmendmentsResponse>(`/amendments?workspace_id=${encodeURIComponent(workspaceId)}${asOf ? `&as_of=${asOf}` : ''}`),
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
  if (!res.ok) throw await failure(res, `/chats/${chatId}/ask`)
  if (!res.body) throw new ApiError('The answer did not arrive. Please try again.', 500)
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
