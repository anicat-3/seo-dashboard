import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import type { FeedbackItem, FeedbackStatus } from '../api/types';
import { ErrorNotice, PageHeader, QueryState } from '../components/ui';
import { formatDateTime } from '../lib/format';

const STATUSES: { value: FeedbackStatus; label: string; tone: string }[] = [
  { value: 'new', label: 'Новое', tone: 'error' },
  { value: 'paused', label: 'На паузе', tone: 'warn' },
  { value: 'postponed', label: 'Отложено', tone: 'pending' },
  { value: 'closed', label: 'Закрыто', tone: 'ok' },
  { value: 'rejected', label: 'Отклонено', tone: 'pending' },
];
const STATUS_BY_VALUE = Object.fromEntries(STATUSES.map((s) => [s.value, s]));

function FeedbackCard({ item }: { item: FeedbackItem }) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState(item.admin_note ?? '');
  const update = useMutation({
    mutationFn: (body: { status?: FeedbackStatus; admin_note?: string }) => api.patch(`/feedback/${item.id}`, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['feedback'] }),
  });
  const status = STATUS_BY_VALUE[item.status];

  return (
    <div className="panel feedback-item">
      <div className="feedback-item-head">
        <span className={`badge ${status.tone}`}>
          <span className="dot" />
          {status.label}
        </span>
        <b>{item.author_name}</b>
        <span className="small muted">{formatDateTime(item.created_at)}</span>
      </div>
      <div className="feedback-message">{item.message}</div>
      <label className="field">
        <span className="small muted">Комментарий администратора</span>
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={1} maxLength={2000} placeholder="Необязательно" />
      </label>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div className="segmented" role="group" aria-label="Статус обращения">
          {STATUSES.map((s) => (
            <button
              key={s.value}
              type="button"
              className={item.status === s.value ? 'active' : ''}
              disabled={update.isPending}
              onClick={() => update.mutate({ status: s.value, admin_note: note })}
            >
              {s.label}
            </button>
          ))}
        </div>
        {note !== (item.admin_note ?? '') && (
          <button className="small" onClick={() => update.mutate({ admin_note: note })} disabled={update.isPending}>
            Сохранить комментарий
          </button>
        )}
      </div>
      {item.resolved_by_name && item.updated_at && (
        <div className="small muted">
          Обработал: {item.resolved_by_name}, {formatDateTime(item.updated_at)}
        </div>
      )}
      <ErrorNotice error={update.error} />
    </div>
  );
}

/** Журнал предложений и замечаний команды (только администратор). */
export function FeedbackPage() {
  const [filter, setFilter] = useState<FeedbackStatus | ''>('new');
  const feedback = useQuery({
    queryKey: ['feedback', filter],
    queryFn: () => api.get<FeedbackItem[]>('/feedback', { status_filter: filter }),
    placeholderData: (previous) => previous,
  });

  return (
    <>
      <PageHeader title="Обращения" subtitle="Предложения и замечания команды по работе дашборда" />
      <div className="segmented" style={{ marginBottom: 12 }}>
        <button className={filter === '' ? 'active' : ''} onClick={() => setFilter('')}>
          Все
        </button>
        {STATUSES.map((s) => (
          <button key={s.value} className={filter === s.value ? 'active' : ''} onClick={() => setFilter(s.value)}>
            {s.label}
          </button>
        ))}
      </div>
      <QueryState query={feedback}>
        {(items) =>
          items.length === 0 ? (
            <div className="panel empty">Обращений нет.</div>
          ) : (
            <div className="stack">
              {items.map((item) => (
                <FeedbackCard key={`${item.id}:${item.updated_at ?? ''}`} item={item} />
              ))}
            </div>
          )
        }
      </QueryState>
    </>
  );
}
