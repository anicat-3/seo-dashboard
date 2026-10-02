import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import type { Account } from '../api/types';
import { ErrorNotice, Modal, PageHeader, QueryState } from '../components/ui';
import { formatDateTime } from '../lib/format';

const MIN_LENGTH = 10;

function PasswordDialog({ account, onClose }: { account: Account; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');
  const change = useMutation({
    mutationFn: () => api.post(`/accounts/${account.id}/password`, { new_password: password }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['accounts'] });
      onClose();
    },
  });
  const mismatch = repeat.length > 0 && password !== repeat;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!mismatch) change.mutate();
  }

  return (
    <Modal
      title={`Новый пароль: ${account.login}`}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Отмена</button>
          <button className="primary" type="submit" form="password-form" disabled={change.isPending || mismatch || password.length < MIN_LENGTH}>
            Сменить пароль
          </button>
        </>
      }
    >
      <form id="password-form" className="stack" onSubmit={submit}>
        <label className="field">
          Новый пароль (не короче {MIN_LENGTH} символов)
          <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={MIN_LENGTH} required autoFocus />
        </label>
        <label className="field">
          Повторите пароль
          <input type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} required />
        </label>
        {mismatch && <div className="notice warn">Пароли не совпадают.</div>}
        <div className="field-hint">Все активные сессии этой учётной записи будут завершены — сотрудникам потребуется войти заново.</div>
        <ErrorNotice error={change.error} />
      </form>
    </Modal>
  );
}

/** Смена паролей учётных записей — только администратор. */
export function AccountsPage() {
  const [editing, setEditing] = useState<Account | null>(null);
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api.get<Account[]>('/accounts') });

  return (
    <>
      <PageHeader title="Учётные записи" subtitle="Администратор и общая учётная запись SEO-команды. Роли не меняются через интерфейс." />
      <QueryState query={accounts}>
        {(data) => (
          <div className="panel table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Логин</th>
                  <th>Роль</th>
                  <th>Пароль изменён</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.map((account) => (
                  <tr key={account.id}>
                    <td>
                      <b>{account.login}</b>
                    </td>
                    <td>{account.role === 'admin' ? 'Администратор' : 'SEO-команда'}</td>
                    <td>{formatDateTime(account.password_changed_at)}</td>
                    <td style={{ textAlign: 'right' }}>
                      <button className="small" onClick={() => setEditing(account)}>
                        Сменить пароль
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </QueryState>
      {editing && <PasswordDialog account={editing} onClose={() => setEditing(null)} />}
    </>
  );
}
