import { useState, type FormEvent } from 'react';

import type { TeamMemberShort } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { ErrorNotice } from '../components/ui';

const MEMBER_KEY = 'seo-dashboard-member-id';

function rememberedMember(): string {
  try {
    return localStorage.getItem(MEMBER_KEY) ?? '';
  } catch {
    return '';
  }
}

/**
 * Вход в два шага: логин и пароль, затем выбор себя из списка команды.
 * Без выбора сотрудника войти нельзя — имя попадает в журналы и пометки.
 */
export function LoginPage() {
  const { login, chooseMember } = useAuth();
  const [loginName, setLoginName] = useState('');
  const [password, setPassword] = useState('');
  const [members, setMembers] = useState<TeamMemberShort[] | null>(null);
  const [memberId, setMemberId] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submitCredentials(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const list = await login(loginName.trim(), password);
      if (list.length) {
        setMembers(list);
        const remembered = rememberedMember();
        setMemberId(list.some((m) => String(m.id) === remembered) ? remembered : '');
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function submitMember(event: FormEvent) {
    event.preventDefault();
    if (!memberId) return;
    setBusy(true);
    setError(null);
    try {
      await chooseMember(Number(memberId));
      try {
        localStorage.setItem(MEMBER_KEY, memberId);
      } catch {
        /* выбор просто не запомнится */
      }
    } catch (err) {
      setError(err);
      setMembers(null);
      setPassword('');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      {members === null ? (
        <form className="panel login-card" onSubmit={submitCredentials}>
          <div className="panel-header">
            <h1>SEO-дашборд</h1>
          </div>
          <div className="panel-body stack">
            <label className="field">
              Логин
              <input value={loginName} onChange={(e) => setLoginName(e.target.value)} autoComplete="username" required autoFocus />
            </label>
            <label className="field">
              Пароль
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <ErrorNotice error={error} />
            <button className="primary" type="submit" disabled={busy}>
              {busy ? 'Проверка…' : 'Далее'}
            </button>
          </div>
        </form>
      ) : (
        <form className="panel login-card" onSubmit={submitMember}>
          <div className="panel-header">
            <h1>Кто вы?</h1>
          </div>
          <div className="panel-body stack">
            <label className="field">
              Сотрудник
              <select value={memberId} onChange={(e) => setMemberId(e.target.value)} required autoFocus>
                <option value="">— выберите себя из списка —</option>
                {members.map((member) => (
                  <option key={member.id} value={member.id}>
                    {member.full_name}
                  </option>
                ))}
              </select>
              <span className="field-hint">Ваше имя попадёт в журналы и пометки на графиках. Нет в списке — обратитесь к администратору.</span>
            </label>
            <ErrorNotice error={error} />
            <div className="row">
              <button
                type="button"
                onClick={() => {
                  setMembers(null);
                  setPassword('');
                }}
              >
                Назад
              </button>
              <button className="primary" type="submit" disabled={busy || !memberId} style={{ flex: 1, justifyContent: 'center' }}>
                {busy ? 'Вход…' : 'Войти'}
              </button>
            </div>
          </div>
        </form>
      )}
    </div>
  );
}
