/** Контекст текущего пользователя: учётная запись и сотрудник, выбранный при входе. */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { api, onUnauthorized } from '../api/client';
import type { LoginStep, Me, TeamMemberShort } from '../api/types';

interface AuthValue {
  /** `undefined` — сессия ещё проверяется, `null` — вход не выполнен. */
  user: Me | null | undefined;
  /**
   * Шаг 1: логин и пароль. Возвращает список сотрудников, если нужно выбрать себя,
   * или пустой список, если вход уже завершён (первый вход администратора).
   */
  login: (login: string, password: string) => Promise<TeamMemberShort[]>;
  /** Шаг 2: выбор сотрудника из списка команды. */
  chooseMember: (memberId: number) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null | undefined>(undefined);
  const queryClient = useQueryClient();

  useEffect(() => {
    api
      .get<Me>('/auth/me')
      .then(setUser)
      .catch(() => setUser(null));
    // Сессия завершена на сервере (смена пароля, сотрудник исключён из команды).
    return onUnauthorized(() => setUser(null));
  }, []);

  const login = useCallback(async (loginName: string, password: string) => {
    const step = await api.post<LoginStep>('/auth/login', { login: loginName, password });
    if (step.status === 'done' && step.me) {
      setUser(step.me);
      return [];
    }
    return step.members;
  }, []);

  const chooseMember = useCallback(async (memberId: number) => {
    setUser(await api.post<Me>('/auth/member', { member_id: memberId }));
  }, []);

  const logout = useCallback(async () => {
    await api.post('/auth/logout');
    queryClient.clear();
    setUser(null);
  }, [queryClient]);

  const value = useMemo(() => ({ user, login, chooseMember, logout }), [user, login, chooseMember, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth вызван вне AuthProvider');
  return value;
}

/** Текущий пользователь; использовать только внутри защищённых страниц. */
export function useUser(): Me {
  const { user } = useAuth();
  if (!user) throw new Error('Пользователь не авторизован');
  return user;
}
