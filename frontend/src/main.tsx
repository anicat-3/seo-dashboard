import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Корпоративные шрифты подключены локально (с кириллицей), без обращения к внешним CDN.
import '@fontsource-variable/montserrat';
import '@fontsource-variable/oswald';

import { App } from './App';
import { AuthProvider } from './auth/AuthContext';
import { ApiError } from './api/client';
import { ConfirmProvider } from './components/ConfirmDialog';
import { applyStoredTheme } from './lib/theme';
import './styles.css';

applyStoredTheme();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      // Ошибки авторизации и «не найдено» повторять бессмысленно.
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <ConfirmProvider>
            <App />
          </ConfirmProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
