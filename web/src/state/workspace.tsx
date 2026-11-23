import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api } from '@/lib/api'
import type { Workspace } from '@/lib/types'

/** Routes under /w/:workspaceId always have a workspace; the guard in WorkspaceGate makes sure it exists. */

const LAST_KEY = 'docai.workspace'

export const lastWorkspace = (): string | null => {
  try { return localStorage.getItem(LAST_KEY) } catch { return null }
}
export const rememberWorkspace = (id: string) => {
  try { localStorage.setItem(LAST_KEY, id) } catch { /* private mode */ }
}

export const workspacePath = (id: string, rest = '') => `/w/${id}${rest}`

/** The id in the URL. Only call inside a /w/:workspaceId route. */
export function useWorkspaceId(): string {
  const { workspaceId } = useParams()
  if (!workspaceId) throw new Error('useWorkspaceId must be used inside a /w/:workspaceId route')
  return workspaceId
}

export const workspacesQuery = { queryKey: ['workspaces'], queryFn: () => api.workspaces() } as const

/** The current workspace (undefined until the list has loaded). */
export function useWorkspace(): Workspace | undefined {
  const id = useParams().workspaceId
  const { data } = useQuery(workspacesQuery)
  return data?.find((w) => w.workspace_id === id)
}
