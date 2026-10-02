import { useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import type { TeamMember } from '../api/types';
import { useConfirm } from '../components/ConfirmDialog';
import { ErrorNotice, PageHeader, QueryState, StatusBadge } from '../components/ui';
import { formatDate } from '../lib/format';

function MemberRow({ member }: { member: TeamMember }) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(member.full_name);
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['team'] });
  const rename = useMutation({
    mutationFn: () => api.patch<TeamMember>(`/team/${member.id}`, { full_name: name }),
    onSuccess: () => {
      setEditing(false);
      invalidate();
    },
  });
  const toggle = useMutation({
    mutationFn: () => api.post<TeamMember>(`/team/${member.id}/active`, {}, { is_active: !member.is_active }),
    onSuccess: invalidate,
  });

  async function onToggle() {
    if (member.is_active) {
      const ok = await confirm({
        title: `Выключить «${member.full_name}»?`,
        message: 'Сотрудник исчезнет из списка при входе, его текущая сессия завершится. Записи в журналах сохранятся; включить обратно можно в любой момент.',
        confirmLabel: 'Выключить',
        danger: true,
      });
      if (!ok) return;
    }
    toggle.mutate();
  }

  return (
    <tr>
      <td style={{ width: '100%' }}>
        {editing ? (
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault();
              rename.mutate();
            }}
          >
            <input value={name} onChange={(e) => setName(e.target.value)} minLength={3} maxLength={100} required autoFocus />
            <button className="small primary" type="submit" disabled={rename.isPending}>
              Сохранить
            </button>
            <button
              className="small"
              type="button"
              onClick={() => {
                setEditing(false);
                setName(member.full_name);
              }}
            >
              Отмена
            </button>
          </form>
        ) : (
          <b>{member.full_name}</b>
        )}
        <ErrorNotice error={rename.error ?? toggle.error} />
      </td>
      <td>
        <StatusBadge status={member.is_active ? 'ok' : 'disabled'} label={member.is_active ? 'В команде' : 'Выключен'} />
      </td>
      <td className="nowrap">{formatDate(member.created_at)}</td>
      <td>
        <div className="row" style={{ justifyContent: 'flex-end', flexWrap: 'nowrap' }}>
          {!editing && (
            <button className="small" onClick={() => setEditing(true)}>
              Переименовать
            </button>
          )}
          <button className={`small${member.is_active ? ' danger' : ''}`} onClick={() => void onToggle()} disabled={toggle.isPending}>
            {member.is_active ? 'Выключить' : 'Включить'}
          </button>
        </div>
      </td>
    </tr>
  );
}

/** Состав SEO-команды: из этого списка сотрудники выбирают себя при входе (только администратор). */
export function TeamPage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const team = useQuery({ queryKey: ['team'], queryFn: () => api.get<TeamMember[]>('/team') });
  const add = useMutation({
    mutationFn: () => api.post<TeamMember>('/team', { full_name: name }),
    onSuccess: () => {
      setName('');
      void queryClient.invalidateQueries({ queryKey: ['team'] });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <>
      <PageHeader
        title="Команда"
        subtitle="При входе сотрудник выбирает себя из этого списка. Его имя попадает в журналы и пометки на графиках."
      />
      <div className="stack">
        <form className="panel panel-body row" onSubmit={submit}>
          <input
            style={{ flex: 1, minWidth: 220 }}
            placeholder="Фамилия и имя, например: Иванова Анна"
            value={name}
            onChange={(e) => setName(e.target.value)}
            minLength={3}
            maxLength={100}
            required
            aria-label="Фамилия и имя"
          />
          <button className="primary" type="submit" disabled={add.isPending}>
            + Добавить сотрудника
          </button>
          <div style={{ flexBasis: '100%' }}>
            <ErrorNotice error={add.error} />
          </div>
        </form>
        <QueryState query={team}>
          {(members) =>
            members.length === 0 ? (
              <div className="panel empty">
                Список пуст. Пока в нём никого нет, войти может только администратор — добавьте сотрудников, включая себя.
              </div>
            ) : (
              <div className="panel table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Сотрудник</th>
                      <th>Статус</th>
                      <th>Добавлен</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {members.map((member) => (
                      <MemberRow key={member.id} member={member} />
                    ))}
                  </tbody>
                </table>
              </div>
            )
          }
        </QueryState>
      </div>
    </>
  );
}
