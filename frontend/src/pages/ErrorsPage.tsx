import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import type { ErrorsResponse } from '../api/types';
import { useConfirm } from '../components/ConfirmDialog';
import { ErrorNotice, PageHeader, QueryState, StatusBadge } from '../components/ui';
import { formatDate, formatDateTime } from '../lib/format';

interface SchedulerState {
  enabled: boolean;
  jobs: { id: string; next_run_time: string | null }[];
}

/** Экран ошибок сбора и доступов: что сломалось и как перезапустить. */
export function ErrorsPage() {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const errors = useQuery({ queryKey: ['errors'], queryFn: () => api.get<ErrorsResponse>('/admin/errors'), refetchInterval: 15000 });
  const scheduler = useQuery({ queryKey: ['scheduler'], queryFn: () => api.get<SchedulerState>('/admin/scheduler') });
  const syncAll = useMutation({
    mutationFn: () => api.post('/admin/sync-all'),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['scheduler'] }),
  });
  const backfill = useMutation({
    mutationFn: (integrationId: number) => api.post(`/integrations/${integrationId}/backfill`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['errors'] }),
  });
  const nextDaily = scheduler.data?.jobs.find((job) => job.id === 'daily_sync')?.next_run_time;

  return (
    <>
      <PageHeader
        title="Ошибки сбора и доступов"
        subtitle={
          scheduler.data &&
          (scheduler.data.enabled ? `Следующий ежедневный сбор: ${formatDateTime(nextDaily)}` : 'Планировщик отключён (SCHEDULER_ENABLED=false)')
        }
      >
        <button
          disabled={syncAll.isPending}
          onClick={async () => {
            const ok = await confirm({
              title: 'Запустить сбор сейчас?',
              message: 'Сбор пройдёт по всем активным подключениям и перезапишет данные за последние 5 дней.',
              confirmLabel: 'Запустить',
            });
            if (ok) syncAll.mutate();
          }}
        >
          Запустить сбор сейчас
        </button>
      </PageHeader>
      <ErrorNotice error={syncAll.error ?? backfill.error} />
      {syncAll.isSuccess && <div className="notice info">Сбор поставлен в очередь. Результаты появятся в журнале запусков.</div>}
      <QueryState query={errors}>
        {(data) => (
          <div className="stack" style={{ marginTop: 12 }}>
            <div className="panel">
              <div className="panel-header">
                <h2>Доступы с ошибкой: {data.credentials.length}</h2>
                <Link className="small" to="/credentials">
                  Все доступы →
                </Link>
              </div>
              {data.credentials.length === 0 ? (
                <div className="empty">Все доступы работают.</div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <tbody>
                      {data.credentials.map((credential) => (
                        <tr key={credential.id}>
                          <td className="nowrap">{credential.system_name}</td>
                          <td>
                            <b>{credential.label}</b>
                          </td>
                          <td style={{ width: '100%' }}>{credential.status_message}</td>
                          <td className="nowrap muted">{formatDateTime(credential.last_checked_at)}</td>
                          <td>
                            <Link to="/credentials">
                              <button className="small">Переподключить</button>
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="panel">
              <div className="panel-header">
                <h2>Подключения с ошибкой: {data.integrations.length}</h2>
              </div>
              {data.integrations.length === 0 ? (
                <div className="empty">Все подключения собираются без ошибок.</div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Проект</th>
                        <th>Система</th>
                        <th>Ошибка</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {data.integrations.map((integration) => (
                        <tr key={integration.id}>
                          <td className="nowrap">
                            <Link to={`/projects/${integration.project_slug}/settings`}>{integration.project_name}</Link>
                          </td>
                          <td className="nowrap">
                            {integration.system_name}
                            <div className="small muted mono">{integration.external_id}</div>
                          </td>
                          <td style={{ width: '100%' }}>{integration.last_error}</td>
                          <td>
                            <button className="small" onClick={() => backfill.mutate(integration.id)} disabled={backfill.isPending}>
                              Перезапустить сбор
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="panel">
              <div className="panel-header">
                <h2>Последние неуспешные запуски</h2>
              </div>
              {data.runs.length === 0 ? (
                <div className="empty">Неуспешных запусков нет.</div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Начат</th>
                        <th>Проект</th>
                        <th>Система</th>
                        <th>Период</th>
                        <th>Статус</th>
                        <th>Сообщение</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.runs.map((run) => (
                        <tr key={run.id}>
                          <td className="nowrap">{formatDateTime(run.started_at)}</td>
                          <td className="nowrap">{run.project_name}</td>
                          <td className="nowrap">{run.system_name}</td>
                          <td className="nowrap small">
                            {run.date_from && run.date_to ? `${formatDate(run.date_from)} – ${formatDate(run.date_to)}` : '—'}
                          </td>
                          <td>
                            <StatusBadge status={run.status} />
                          </td>
                          <td>{run.error_message}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
      </QueryState>
    </>
  );
}
