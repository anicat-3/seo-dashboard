/** Светлая/тёмная тема: по умолчанию — как в системе, выбор пользователя хранится локально. */
import { useCallback, useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'seo-dashboard-theme';
const listeners = new Set<() => void>();

function stored(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === 'light' || value === 'dark' ? value : null;
  } catch {
    return null;
  }
}

export function currentTheme(): Theme {
  const applied = document.documentElement.dataset.theme;
  if (applied === 'light' || applied === 'dark') return applied;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/**
 * Временно включить тему (например, светлую на время печати) или вернуть
 * выбранную пользователем (`null`). Графики перерисовываются в новых цветах.
 */
export function forceTheme(theme: Theme | null): void {
  const next = theme ?? stored();
  if (next) document.documentElement.dataset.theme = next;
  else delete document.documentElement.dataset.theme;
  listeners.forEach((listener) => listener());
}

export function applyStoredTheme(): void {
  const theme = stored();
  if (theme) document.documentElement.dataset.theme = theme;
}

/** Текущая тема и переключатель; графики подписываются, чтобы перечитать цвета. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(currentTheme);

  useEffect(() => {
    const sync = () => setTheme(currentTheme());
    listeners.add(sync);
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    media.addEventListener('change', sync);
    return () => {
      listeners.delete(sync);
      media.removeEventListener('change', sync);
    };
  }, []);

  const toggle = useCallback(() => {
    const next: Theme = currentTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* хранилище недоступно — тема действует до перезагрузки */
    }
    listeners.forEach((listener) => listener());
  }, []);

  return [theme, toggle];
}

/** Прочитать значение CSS-переменной темы (для canvas-графиков). */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
