import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Navigate, Outlet, useParams } from 'react-router-dom'
import { useUi } from '@/state/ui'
import { lastWorkspace, rememberWorkspace, workspacePath, workspacesQuery } from '@/state/workspace'
import { Skeleton } from '@/ui/primitives'

function Loading() {
  return <div className="mx-auto w-full max-w-3xl space-y-4 p-8"><Skeleton className="h-10 w-1/2" /><Skeleton className="h-40" /></div>
}

/** "/" opens the workspace used last (or the first one); with no workspace at all it opens the Workspaces page. */
export function HomeRedirect() {
  const { data, isLoading, isError } = useQuery(workspacesQuery)
  if (isLoading) return <Loading />
  if (isError || !data?.length) return <Navigate to="/workspaces" replace />
  const remembered = data.find((w) => w.workspace_id === lastWorkspace())
  return <Navigate to={workspacePath((remembered ?? data[0]).workspace_id)} replace />
}

/** Wraps every /w/:workspaceId page: unknown or deleted workspaces go back to the list, and the open
 *  Sources panel is closed when you move to another workspace (its answer belongs to the old one). */
export function WorkspaceGate() {
  const { workspaceId } = useParams()
  const { closePanel } = useUi()
  const { data, isLoading, isFetching } = useQuery(workspacesQuery)
  const known = data?.some((w) => w.workspace_id === workspaceId)

  useEffect(() => {
    if (workspaceId && known) rememberWorkspace(workspaceId)
  }, [workspaceId, known])
  useEffect(() => { closePanel() }, [workspaceId, closePanel])

  if (isLoading || (!known && isFetching)) return <Loading />  // a refetch may be about to add this workspace
  if (!known) return <Navigate to="/workspaces" replace />
  return <Outlet />
}
