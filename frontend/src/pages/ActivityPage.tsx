import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { api } from '../api/client';
import type { ActivityEntry, ActivitySummary, TeamMember } from '../api/types';
import { PageHeader, QueryState } from '../components/ui';
import { formatDateTime } from '../lib/format';

const EVENTS: Record<ActivityEntry['event'], string> = {
  login: 'Вход',
  logout: 'Выход',
  view: 'Просмотр',
};

/** Журнал действий сотрудников: когда входили и что смотрели (только администратор). */
export function ActivityPage() {
  const [memberId, setMemberId] = useState('');
  const [event, setEvent] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const team = useQuery({ queryKey: ['team'], queryFn: () => api.get<TeamMember[]>('/team') });
  const summary = useQuery({ queryKey: ['activity-summary'], queryFn: () => api.get<ActivitySummary[]>('/activity/summary') });
  const filters = { member_id: memberId, event, date_from: dateFrom, date_to: dateTo };
  const log = useQuery({
    queryKey: ['activity', filters],
    queryFn: () => api.get<ActivityEntry[]>('/activity', filters),
    placeholderData: (previous) => previous,
  });

  return (
    <>
      <PageHeader title="Журнал действий" subtitle="Когда сотрудники входили в систему и какие страницы открывали" />
      <div className="stack">
        <div className="panel">
          <div className="panel-header">
            <h2>Сотрудники за последние 7 дней</h2>
          </div>
          <QueryState query={summary}>
            {(rows) =>
              rows.length === 0 ? (
                <div className="empty">
                  Список команды пуст. <Link to="/team">Добавьте сотрудников</Link>.
                </div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Сотрудник</th>
                        <th>Последний вход</th>
                        <th>Последнее действие</th>
                        <th className="num">Входов</th>
                        <th className="num">Просмотров страниц</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={row.member_id}>
                          <td>
                            <button className="ghost small" style={{ padding: 0, fontWeight: 600 }} onClick={() => setMemberId(String(row.member_id))}>
                              {row.full_name}
                            </button>
                            {!row.is_active && <div className="small muted">выключен</div>}
                          </td>
                          <td className="nowrap">{formatDateTime(row.last_login)}</td>
                          <td className="nowrap">{formatDateTime(row.last_activity)}</td>
                          <td className="num">{row.logins}</td>
                          <td className="num">{row.views}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            }
          </QueryState>
        </div>

        <div className="panel">
          <div className="panel-header">
            <h2>События</h2>
            <div className="row">
              <select value={memberId} onChange={(e) => setMemberId(e.target.value)} aria-label="Сотрудник">
                <option value="">Все сотрудники</option>
                {team.data?.map((member) => (
                  <option key={member.id} value={member.id}>
                    {member.full_name}
                  </option>
                ))}
              </select>
              <select value={event} onChange={(e) => setEvent(e.target.value)} aria-label="Событие">
                <option value="">Все события</option>
                <option value="login">Входы</option>
                <option value="logout">Выходы</option>
                <option value="view">Просмотры</option>
              </select>
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} aria-label="С даты" />
              <span className="muted">–</span>
              <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} aria-label="По дату" />
            </div>
          </div>
          <QueryState query={log}>
            {(rows) => (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Когда</th>
                      <th>Сотрудник</th>
                      <th>Событие</th>
                      <th>Страница</th>
                      <th>Проект</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.id}>
                        <td className="nowrap">{formatDateTime(row.created_at)}</td>
                        <td>{row.actor_name}</td>
                        <td>{EVENTS[row.event]}</td>
                        <td>{row.page ?? '—'}</td>
                        <td>{row.project_name ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {rows.length === 0 && <div className="empty">Событий по выбранным условиям нет.</div>}
              </div>
            )}
          </QueryState>
        </div>
      </div>
    </>
  );
}
