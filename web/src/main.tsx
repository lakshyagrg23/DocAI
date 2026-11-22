import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ChatPage } from '@/chat/ChatPage'
import { AppShell } from '@/layout/AppShell'
import { AmendmentsPage } from '@/pages/Amendments'
import { ConflictsPage } from '@/pages/Conflicts'
import { LibraryPage } from '@/pages/Library'
import { UiProvider } from '@/state/ui'
import { TooltipProvider } from '@/ui/primitives'
import './index.css'

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: false } } })

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <UiProvider>
        <TooltipProvider delayDuration={150}>
          <BrowserRouter>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<ChatPage />} />
                <Route path="chat/:chatId" element={<ChatPage />} />
                <Route path="library" element={<LibraryPage />} />
                <Route path="conflicts" element={<ConflictsPage />} />
                <Route path="amendments" element={<AmendmentsPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </TooltipProvider>
      </UiProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
