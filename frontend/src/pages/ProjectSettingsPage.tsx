import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import { useUser } from '../auth/AuthContext';
import type { Integration, MonitoredUrl, Project, SyncRun } from '../api/types';
import { useConfirm } from '../components/ConfirmDialog';
import { ConnectSystemDialog } from '../components/ConnectSystemDialog';
import { EditIntegrationDialog } from '../components/EditIntegrationDialog';
import { RulesPanel } from '../components/RulesPanel';
import { ErrorNotice, Modal, PageHeader, QueryState, StatusBadge, systemShort } from '../components/ui';
import { formatDate, formatDateTime } from '../lib/format';
import { PRESETS } from '../lib/period';

const JOB_LABELS: Record<string, string> = { daily: 'Ежедневный', backfill: 'История', manual: 'Вручную', period: 'Итоги периода' };

function integrationState(integration: Integration): string {
  if (integration.disabled_at) return 'disabled';
  if (!integration.is_active) return 'paused';
  return integration.status;
}

/** Ручной перезапуск сбора за период и журнал запусков подключения. */
function SyncDialog({ integration, onClose }: { integration: Integration; onClose: () => void }) {
  const initial = PRESETS[0].range();
  const [from, setFrom] = useState(initial.from);
  const [to, setTo] = useState(initial.to);
  const queryClient = useQueryClient();
  const runs = useQuery({
    queryKey: ['runs', integration.id],
    queryFn: () => api.get<SyncRun[]>(`/integrations/${integration.id}/runs`),
    refetchInterval: 4000,
  });
  const sync = useMutation({
    mutationFn: () => api.post(`/integrations/${integration.id}/sync`, { date_from: from, date_to: to }),
    onSuccess: () => {
      void runs.refetch();
      void queryClient.invalidateQueries({ queryKey: ['integrations', integration.project_id] });
    },
  });

  return (
    <Modal title={`Сбор данных: ${systemShort(integration.system_code)}`} onClose={onClose}>
      <div className="row">
        <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} aria-label="Начало периода" />
        <span className="muted">–</span>
        <input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} aria-label="Конец периода" />
        <button className="primary" onClick={() => sync.mutate()} disabled={sync.isPending}>
          Перезапустить сбор
        </button>
      </div>
      <div className="field-hint">Данные за выбранный период будут перезаписаны. Снимки состояния задним числом не восстанавливаются.</div>
      <ErrorNotice error={sync.error} />
      <h3>Последние запуски</h3>
      <QueryState query={runs}>
        {(data) => (
          <div className="table-wrap" style={{ maxHeight: 320, overflowY: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Начат</th>
                  <th>Тип</th>
                  <th>Период</th>
                  <th>Статус</th>
                  <th className="num">Строк</th>
                </tr>
              </thead>
              <tbody>
                {data.map((run) => (
                  <tr key={run.id}>
                    <td className="nowrap">{formatDateTime(run.started_at)}</td>
                    <td>
                      {JOB_LABELS[run.job_type] ?? run.job_type}
                      {run.started_by_name && <div className="small muted">{run.started_by_name}</div>}
                    </td>
                    <td className="nowrap small">
                      {run.date_from ?? '—'} … {run.date_to ?? '—'}
                    </td>
                    <td>
                      <StatusBadge status={run.status} />
                      {run.error_message && <div className="small muted">{run.error_message}</div>}
                    </td>
                    <td className="num">{run.rows_written}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </QueryState>
    </Modal>
  );
}

function IntegrationsSection({ projectId }: { projectId: number }) {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const isAdmin = useUser().role === 'admin';
  const [connecting, setConnecting] = useState(false);
  const [syncing, setSyncing] = useState<Integration | null>(null);
  const [editing, setEditing] = useState<Integration | null>(null);
  const integrations = useQuery({
    queryKey: ['integrations', projectId],
    queryFn: () => api.get<Integration[]>(`/projects/${projectId}/integrations`),
    // Пока идёт загрузка истории, статус обновляется автоматически.
    refetchInterval: (query) => (query.state.data?.some((i) => i.status === 'pending' && i.is_active) ? 3000 : false),
  });
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['integrations', projectId] });
    void queryClient.invalidateQueries({ queryKey: ['projects'] });
  };
  const toggle = useMutation({
    mutationFn: (integration: Integration) => api.patch(`/integrations/${integration.id}`, { is_active: !integration.is_active }),
    onSuccess: invalidate,
  });
  const disable = useMutation({
    mutationFn: (integration: Integration) => api.post(`/integrations/${integration.id}/disable`),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (integration: Integration) => api.delete(`/integrations/${integration.id}`),
    onSuccess: invalidate,
  });

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Подключённые системы</h2>
        <button className="primary" onClick={() => setConnecting(true)}>
          + Подключить систему
        </button>
      </div>
      <ErrorNotice error={toggle.error ?? disable.error ?? remove.error} />
      <QueryState query={integrations}>
        {(data) =>
          data.length === 0 ? (
            <div className="empty">Системы не подключены. Неподключённые системы не собираются и не показываются.</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Система</th>
                    <th>Ресурс</th>
                    <th>Статус</th>
                    <th>Последний сбор</th>
                    <th>Подключил</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.map((integration) => (
                    <tr key={integration.id}>
                      <td className="nowrap">
                        <b>{systemShort(integration.system_code)}</b>
                      </td>
                      <td>
                        {integration.external_name ?? integration.external_id}
                        <div className="small muted mono">{integration.external_id}</div>
                        {integration.goals.length > 0 && (
                          <div className="small muted">Цели: {integration.goals.map((g) => g.name).join(', ')}</div>
                        )}
                      </td>
                      <td>
                        <StatusBadge status={integrationState(integration)} />
                        {integration.last_error && !integration.disabled_at && (
                          <div className="small muted" style={{ maxWidth: 260 }}>
                            {integration.last_error}
                          </div>
                        )}
                      </td>
                      <td className="nowrap">
                        {integration.last_run ? (
                          <>
                            {formatDateTime(integration.last_run.started_at)}
                            <div className="small muted">
                              {JOB_LABELS[integration.last_run.job_type]} · {integration.last_run.rows_written} строк
                            </div>
                          </>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td className="nowrap">
                        {integration.created_by_name}
                        <div className="small muted">{formatDate(integration.created_at)}</div>
                      </td>
                      <td>
                        <div className="row" style={{ justifyContent: 'flex-end' }}>
                          {!integration.disabled_at && (
                            <>
                              <button className="small" onClick={() => setEditing(integration)}>
                                Изменить
                              </button>
                              <button className="small" onClick={() => setSyncing(integration)}>
                                Сбор и журнал
                              </button>
                              <button className="small" onClick={() => toggle.mutate(integration)} disabled={toggle.isPending}>
                                {integration.is_active ? 'Пауза' : 'Возобновить'}
                              </button>
                              <button
                                className="small danger"
                                onClick={async () => {
                                  const ok = await confirm({
                                    title: `Отключить ${systemShort(integration.system_code)} от проекта?`,
                                    message: 'Сбор остановится, блок исчезнет с дашборда. Накопленная история сохранится, систему можно подключить снова.',
                                    confirmLabel: 'Отключить',
                                    danger: true,
                                  });
                                  if (ok) disable.mutate(integration);
                                }}
                              >
                                Отключить
                              </button>
                            </>
                          )}
                          {integration.disabled_at && (
                            <button className="small" onClick={() => toggle.mutate(integration)}>
                              Подключить снова
                            </button>
                          )}
                          {integration.disabled_at && isAdmin && (
                            <button
                              className="small danger"
                              disabled={remove.isPending}
                              onClick={async () => {
                                const ok = await confirm({
                                  title: `Удалить ${systemShort(integration.system_code)} из проекта?`,
                                  message:
                                    'Подключение и вся собранная по нему история будут удалены безвозвратно. Чтобы снова собирать данные, систему придётся подключить заново.',
                                  confirmLabel: 'Удалить',
                                  danger: true,
                                });
                                if (ok) remove.mutate(integration);
                              }}
                            >
                              Удалить
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </QueryState>
      {connecting && <ConnectSystemDialog projectId={projectId} connected={integrations.data ?? []} onClose={() => setConnecting(false)} />}
      {syncing && <SyncDialog integration={syncing} onClose={() => setSyncing(null)} />}
      {editing && <EditIntegrationDialog integration={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

/** URL для проверки в PageSpeed Insights. */
function UrlsSection({ projectId }: { projectId: number }) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState('');
  const [template, setTemplate] = useState('');
  const urls = useQuery({ queryKey: ['urls', projectId], queryFn: () => api.get<MonitoredUrl[]>(`/projects/${projectId}/urls`) });
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['urls', projectId] });
  const add = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/urls`, { url, template_name: template || null }),
    onSuccess: () => {
      setUrl('');
      setTemplate('');
      invalidate();
    },
  });
  const toggle = useMutation({
    mutationFn: (item: MonitoredUrl) => api.patch(`/urls/${item.id}`, {}, { is_active: !item.is_active }),
    onSuccess: invalidate,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>URL для PageSpeed Insights</h2>
      </div>
      <QueryState query={urls}>
        {(data) => (
          <div className="table-wrap">
            <table>
              <tbody>
                {data.map((item) => (
                  <tr key={item.id}>
                    <td className="mono" style={{ width: '100%' }}>
                      {item.url}
                    </td>
                    <td className="nowrap muted">{item.template_name ?? '—'}</td>
                    <td>
                      <StatusBadge status={item.is_active ? 'ok' : 'disabled'} label={item.is_active ? 'Проверяется' : 'Выключен'} />
                    </td>
                    <td>
                      <button className="small" onClick={() => toggle.mutate(item)}>
                        {item.is_active ? 'Выключить' : 'Включить'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </QueryState>
      <form className="panel-body row" onSubmit={submit}>
        <input style={{ flex: 2, minWidth: 240 }} type="url" placeholder="https://site.by/catalog/" value={url} onChange={(e) => setUrl(e.target.value)} required />
        <input style={{ flex: 1, minWidth: 140 }} placeholder="Шаблон: каталог, карточка…" value={template} onChange={(e) => setTemplate(e.target.value)} />
        <button type="submit" disabled={add.isPending}>
          Добавить URL
        </button>
      </form>
      <ErrorNotice error={add.error ?? toggle.error} />
    </div>
  );
}

function ProjectForm({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState(project.name);
  const [domain, setDomain] = useState(project.domain);
  const save = useMutation({
    mutationFn: () => api.patch<Project>(`/projects/${project.id}`, { name, domain }),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({ queryKey: ['project'] });
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      // Адрес проекта строится из домена: при смене домена переходим на новый адрес.
      if (updated.slug !== project.slug) navigate(`/projects/${updated.slug}/settings`, { replace: true });
    },
  });
  const changed = name !== project.name || domain !== project.domain;

  return (
    <form
      className="panel panel-body row"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <label className="field" style={{ flex: 1, minWidth: 200 }}>
        Название
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label className="field" style={{ flex: 1, minWidth: 200 }}>
        Домен
        <input value={domain} onChange={(e) => setDomain(e.target.value)} required />
      </label>
      <button type="submit" className="primary" disabled={!changed || save.isPending} style={{ alignSelf: 'flex-end' }}>
        Сохранить
      </button>
      <ErrorNotice error={save.error} />
    </form>
  );
}

/** Настройки проекта: подключения, URL для PSI, пороги подсветки. */
export function ProjectSettingsPage() {
  const projectRef = useParams().projectRef ?? '';
  const isAdmin = useUser().role === 'admin';
  const project = useQuery({ queryKey: ['project', projectRef], queryFn: () => api.get<Project>(`/projects/${projectRef}`) });

  return (
    <>
      <PageHeader title={`Настройки: ${project.data?.name ?? '…'}`} subtitle={project.data?.domain}>
        <Link to={`/projects/${projectRef}`}>
          <button>← К дашборду</button>
        </Link>
      </PageHeader>
      <QueryState query={project}>
        {(data) => (
          <div className="stack">
            <ProjectForm key={`${data.id}-${data.slug}`} project={data} />
            <IntegrationsSection projectId={data.id} />
            <UrlsSection projectId={data.id} />
            {isAdmin && (
              <div className="panel">
                <div className="panel-header">
                  <h2>Пороги подсветки для проекта</h2>
                  <span className="small muted">По умолчанию действует общий порог; для проекта можно задать свой.</span>
                </div>
                <RulesPanel projectId={data.id} />
              </div>
            )}
          </div>
        )}
      </QueryState>
    </>
  );
}
