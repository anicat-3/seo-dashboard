import { useEffect, useState, type ReactNode } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { api } from '../api/client';
import type { ErrorsResponse, Signal } from '../api/types';
import { useAuth, useUser } from '../auth/AuthContext';
import { useTheme } from '../lib/theme';
import { FeedbackForm } from './FeedbackForm';
import { BackToTop } from './ui';

const COLLAPSED_KEY = 'seo-dashboard-sidebar-collapsed';

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

/** Контурные значки пунктов меню (видны и в свёрнутой панели). */
const ICONS: Record<string, ReactNode> = {
  overview: <path d="M2 13V7m4 6V3m4 10V8m4 5V5" />,
  signals: <path d="M8 2.5a4 4 0 0 0-4 4c0 3-1.5 4-1.5 4h11S12 9.5 12 6.5a4 4 0 0 0-4-4zM6.5 13a1.5 1.5 0 0 0 3 0" />,
  projects: <path d="M2 4.5h4l1.5 1.5H14v7H2z" />,
  credentials: <path d="M10.5 2a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM8 8l-6 6m2-2 1.5 1.5M6 10l1.5 1.5" />,
  rules: <path d="M2 4h12M2 8h12M2 12h12M5 2.5v3M11 6.5v3M7 10.5v3" />,
  errors: <path d="M8 2 1.5 13.5h13zM8 6.5v3.5M8 12v.2" />,
  audit: <path d="M4 2h8v12H4zM6 5h4M6 8h4M6 11h2" />,
  accounts: <path d="M8 8a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM3 14c0-2.5 2.2-4 5-4s5 1.5 5 4" />,
  team: <path d="M6 7.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM11 7.5a2 2 0 1 0 0-4M2 13c0-2 1.8-3.5 4-3.5s4 1.5 4 3.5M11 9.5c1.8 0 3 1.4 3 3.5" />,
  activity: <path d="M1.5 8h3l2-5 3 10 2-5h3" />,
  feedback: <path d="M2 3h12v8H7l-3 2.5V11H2zM5 6h6M5 8.5h4" />,
  menu: <path d="M2 4h12M2 8h12M2 12h12" />,
  collapse: <path d="M10 3 5 8l5 5" />,
  expand: <path d="m6 3 5 5-5 5" />,
  theme: <path d="M13 9.5A5.5 5.5 0 0 1 6.5 3 5.5 5.5 0 1 0 13 9.5z" />,
  logout: <path d="M6 2H3v12h3M7 8h7m-2.5-2.5L14 8l-2.5 2.5" />,
};

function Icon({ name }: { name: string }) {
  return (
    <svg className="nav-icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}

function Item({ to, icon, children, count, end }: { to: string; icon: string; children: string; count?: number; end?: boolean }) {
  return (
    <NavLink to={to} end={end} title={children} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
      <span className="nav-label">
        <Icon name={icon} />
        <span className="nav-text">{children}</span>
      </span>
      {count ? <span className="badge signal">{count}</span> : null}
    </NavLink>
  );
}

function Logo() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="1" y="9" width="3" height="6" rx="1" fill="var(--accent)" />
      <rect x="6.5" y="5" width="3" height="10" rx="1" fill="var(--accent)" />
      <rect x="12" y="1" width="3" height="14" rx="1" fill="var(--accent)" />
    </svg>
  );
}

/**
 * Каркас приложения: боковое меню со счётчиками сигналов и ошибок и область страницы.
 *
 * На десктопе панель сворачивается до узкой полосы со значками (состояние
 * запоминается в браузере); на узких экранах она выезжает поверх страницы.
 */
export function Layout({ children }: { children: ReactNode }) {
  const user = useUser();
  const { logout } = useAuth();
  const [theme, toggleTheme] = useTheme();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  const isAdmin = user.role === 'admin';
  const signals = useQuery({ queryKey: ['signals', 'open'], queryFn: () => api.get<Signal[]>('/signals') });
  const errors = useQuery({
    queryKey: ['errors'],
    queryFn: () => api.get<ErrorsResponse>('/admin/errors'),
    enabled: isAdmin,
  });
  const feedback = useQuery({
    queryKey: ['feedback', 'new-count'],
    queryFn: () => api.get<{ count: number }>('/feedback/new-count'),
    enabled: isAdmin,
  });
  const newSignals = signals.data?.filter((s) => s.status === 'new').length ?? 0;
  const errorCount = (errors.data?.credentials.length ?? 0) + (errors.data?.integrations.length ?? 0);

  // Переход по меню закрывает выехавшую панель на мобильном.
  useEffect(() => setMobileOpen(false), [location.pathname]);

  // Журнал действий: каждый открытый раздел (с выбранным периодом) записывается на сервере.
  // Повторы той же страницы в течение пары минут сервер отбрасывает сам.
  useEffect(() => {
    const timer = setTimeout(() => {
      void api.post('/activity', { path: location.pathname + location.search }).catch(() => undefined);
    }, 1500);
    return () => clearTimeout(timer);
  }, [location.pathname, location.search]);

  function toggleCollapsed() {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(COLLAPSED_KEY, next ? '1' : '0');
    } catch {
      /* состояние действует до перезагрузки */
    }
  }

  return (
    <div className={`app${collapsed ? ' sidebar-collapsed' : ''}${mobileOpen ? ' sidebar-open' : ''}`}>
      <div className="sidebar-backdrop" onClick={() => setMobileOpen(false)} />
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-name">
            <Logo />
            SEO-дашборд
          </span>
          <button
            className="icon-btn collapse-toggle"
            onClick={toggleCollapsed}
            title={collapsed ? 'Развернуть панель' : 'Свернуть панель'}
            aria-label={collapsed ? 'Развернуть панель' : 'Свернуть панель'}
            aria-expanded={!collapsed}
          >
            <Icon name={collapsed ? 'expand' : 'collapse'} />
          </button>
        </div>
        <Item to="/" icon="overview" end>
          Сводка
        </Item>
        <Item to="/signals" icon="signals" count={newSignals}>
          Сигналы
        </Item>
        <Item to="/projects" icon="projects">
          Проекты
        </Item>
        {isAdmin && (
          <>
            <div className="nav-section">Настройки</div>
            <Item to="/credentials" icon="credentials">
              Подключения
            </Item>
            <Item to="/rules" icon="rules">
              Правила подсветки
            </Item>
            <Item to="/team" icon="team">
              Команда
            </Item>
            <Item to="/accounts" icon="accounts">
              Учётные записи
            </Item>
            <div className="nav-section">Обслуживание</div>
            <Item to="/errors" icon="errors" count={errorCount}>
              Ошибки сбора
            </Item>
            <Item to="/feedback" icon="feedback" count={feedback.data?.count}>
              Обращения
            </Item>
            <Item to="/activity" icon="activity">
              Журнал действий
            </Item>
            <Item to="/audit" icon="audit">
              Журнал изменений
            </Item>
          </>
        )}
        <div className="sidebar-footer">
          <div className="hide-collapsed">
            <div style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{user.actor_name}</div>
            <div className="small muted">
              {user.role === 'admin' ? 'Администратор' : 'SEO-команда'} · {user.login}
            </div>
          </div>
          <div className="row" style={{ justifyContent: collapsed ? 'center' : 'flex-start' }}>
            <button className="small" onClick={toggleTheme} title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}>
              <Icon name="theme" />
              <span className="nav-text">{theme === 'dark' ? 'Светлая' : 'Тёмная'}</span>
            </button>
            <button className="small" onClick={() => void logout()} title="Выйти">
              <Icon name="logout" />
              <span className="nav-text">Выйти</span>
            </button>
          </div>
        </div>
      </aside>
      <div style={{ minWidth: 0 }}>
        <div className="mobile-bar no-print">
          <button className="icon-btn" onClick={() => setMobileOpen(true)} aria-label="Открыть меню">
            <Icon name="menu" />
          </button>
          <Logo />
          SEO-дашборд
        </div>
        <main className="main">
          {children}
          <FeedbackForm />
        </main>
        <BackToTop />
      </div>
    </div>
  );
}
