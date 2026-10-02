/** Мастер подключения системы к проекту: система → аккаунт → ресурс → настройки → проба. */
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import { useUser } from '../auth/AuthContext';
import type { Credential, Goal, Integration, Resource, SystemInfo, TestResult } from '../api/types';
import { SearchSelect } from './SearchSelect';
import { ErrorNotice, Modal, StatusBadge } from './ui';

const ANALYTICS = new Set(['ga4', 'metrika']);
const RANK_TRACKERS = new Set(['topvisor', 'seranking']);

export function ConnectSystemDialog({
  projectId,
  connected,
  onClose,
}: {
  projectId: number;
  connected: Integration[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const isAdmin = useUser().role === 'admin';
  const [systemCode, setSystemCode] = useState('');
  const [credentialId, setCredentialId] = useState<number | null>(null);
  const [externalId, setExternalId] = useState('');
  const [goalIds, setGoalIds] = useState<Set<string>>(new Set());
  const [test, setTest] = useState<TestResult | null>(null);
  const [historyDays, setHistoryDays] = useState(0);

  const systems = useQuery({ queryKey: ['systems'], queryFn: () => api.get<SystemInfo[]>('/systems') });
  const credentials = useQuery({
    queryKey: ['credentials', systemCode],
    queryFn: () => api.get<Credential[]>('/credentials', { system_code: systemCode }),
    enabled: !!systemCode,
  });
  const resources = useQuery({
    queryKey: ['resources', credentialId, projectId],
    // Для PSI и CrUX ресурсы строятся из домена проекта.
    queryFn: () => api.get<Resource[]>(`/credentials/${credentialId}/resources`, { project_id: projectId }),
    enabled: credentialId !== null,
  });
  const goals = useQuery({
    queryKey: ['goals', credentialId, externalId],
    queryFn: () => api.get<Goal[]>(`/credentials/${credentialId}/goals`, { external_id: externalId }),
    enabled: credentialId !== null && !!externalId && ANALYTICS.has(systemCode),
  });

  // Смена шага выше сбрасывает выбор ниже и результат пробного запроса.
  useEffect(() => {
    setCredentialId(null);
    setExternalId('');
  }, [systemCode]);
  useEffect(() => setExternalId(''), [credentialId]);
  useEffect(() => {
    setGoalIds(new Set());
    setTest(null);
  }, [externalId]);

  const connectedIds = useMemo(
    () => new Set(connected.filter((i) => !i.disabled_at && i.system_code === systemCode).map((i) => i.external_id)),
    [connected, systemCode],
  );
  const resource = resources.data?.find((r) => r.external_id === externalId);

  const payload = () => ({
    system_code: systemCode,
    credential_id: credentialId,
    external_id: externalId,
    external_name: resource?.name ?? null,
    timezone: resource?.timezone ?? 'UTC',
    settings: RANK_TRACKERS.has(systemCode) ? { history_days: historyDays } : {},
    goals: (goals.data ?? []).filter((g) => goalIds.has(g.external_goal_id)),
  });

  const runTest = useMutation({
    mutationFn: () => api.post<TestResult>(`/projects/${projectId}/integrations/test`, payload()),
    onSuccess: setTest,
  });
  const save = useMutation({
    mutationFn: () => api.post<Integration>(`/projects/${projectId}/integrations`, payload()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['integrations', projectId] });
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      onClose();
    },
  });

  const ready = !!systemCode && credentialId !== null && !!externalId;

  return (
    <Modal
      title="Подключить систему"
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Отмена</button>
          <button onClick={() => runTest.mutate()} disabled={!ready || runTest.isPending}>
            {runTest.isPending ? 'Проверка…' : 'Пробный запрос'}
          </button>
          <button className="primary" onClick={() => save.mutate()} disabled={!ready || save.isPending}>
            Сохранить
          </button>
        </>
      }
    >
      <label className="field">
        1. Система
        <select value={systemCode} onChange={(e) => setSystemCode(e.target.value)}>
          <option value="">— выберите —</option>
          {systems.data?.map((system) => {
            const already = connected.some((i) => i.system_code === system.code && !i.disabled_at);
            return (
              <option key={system.code} value={system.code}>
                {system.name}
                {already ? ' (уже подключена)' : ''}
              </option>
            );
          })}
        </select>
      </label>

      {systemCode && (
        <label className="field">
          2. Аккаунт
          <select value={credentialId ?? ''} onChange={(e) => setCredentialId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">— выберите —</option>
            {credentials.data?.map((credential) => (
              <option key={credential.id} value={credential.id}>
                {credential.label}
                {credential.status === 'error' ? ' (ошибка доступа)' : ''}
              </option>
            ))}
          </select>
          <span className="field-hint">
            Нет нужного аккаунта?{' '}
            {isAdmin ? <Link to="/credentials">Добавьте его в разделе «Подключения»</Link> : 'Попросите администратора добавить его в разделе «Подключения»'}.
          </span>
        </label>
      )}

      {credentialId !== null && (
        <div className="field">
          3. Ресурс
          {resources.isError ? (
            <ErrorNotice error={resources.error} />
          ) : (
            <SearchSelect
              ariaLabel="Ресурс"
              disabled={resources.isPending}
              placeholder={resources.isPending ? 'Загрузка списка…' : '— выберите —'}
              value={externalId}
              onChange={setExternalId}
              options={(resources.data ?? []).map((item) => ({
                value: item.external_id,
                label: item.name + (connectedIds.has(item.external_id) ? ' (уже подключён)' : ''),
                hint: item.external_id,
                disabled: connectedIds.has(item.external_id),
              }))}
            />
          )}
          <span className="field-hint">Если ресурса нет в списке, он находится в другом аккаунте.</span>
        </div>
      )}

      {externalId && ANALYTICS.has(systemCode) && (
        <div className="field">
          4. Избранные цели
          {goals.isPending ? (
            <span className="muted small">Загрузка целей…</span>
          ) : (
            goals.data?.map((goal) => (
              <label key={goal.external_goal_id} className="row" style={{ color: 'var(--text-primary)' }}>
                <input
                  type="checkbox"
                  checked={goalIds.has(goal.external_goal_id)}
                  onChange={(e) => {
                    const next = new Set(goalIds);
                    if (e.target.checked) next.add(goal.external_goal_id);
                    else next.delete(goal.external_goal_id);
                    setGoalIds(next);
                  }}
                />
                {goal.name}
              </label>
            ))
          )}
        </div>
      )}

      {externalId && RANK_TRACKERS.has(systemCode) && (
        <div className="notice info">
          Поисковики и регионы берутся из настроек проекта в {systemCode === 'topvisor' ? 'Топвизоре' : 'SE Ranking'}
          {Array.isArray(resource?.extra.regions) && (resource?.extra.regions as string[]).length > 0 &&
            `: ${(resource?.extra.regions as string[]).join(', ')}`}
          . Позиции не проверяются заново — забираются результаты уже сделанных съёмов.
        </div>
      )}

      {externalId && RANK_TRACKERS.has(systemCode) && (
        <label className="field">
          4. История позиций при подключении
          <select value={historyDays} onChange={(e) => setHistoryDays(Number(e.target.value))}>
            <option value={0}>Только последний съём</option>
            <option value={30}>За 30 дней</option>
            <option value={90}>За 90 дней</option>
            <option value={180}>За полгода</option>
            <option value={365}>За год</option>
          </select>
          <span className="field-hint">
            История берётся из уже сделанных съёмов сервиса и ничего не стоит. Большой период загружается дольше: до нескольких минут на проект.
          </span>
        </label>
      )}

      {test && (
        <div className={`notice ${test.ok ? 'info' : 'error'}`}>
          <div>
            <StatusBadge status={test.ok ? 'ok' : 'error'} label={test.ok ? 'Пробный запрос прошёл' : 'Пробный запрос не прошёл'} />
            <div style={{ marginTop: 4 }}>{test.message}</div>
            {Object.keys(test.sample).length > 0 && (
              <div className="mono" style={{ marginTop: 4 }}>
                {Object.entries(test.sample)
                  .map(([key, value]) => `${key} = ${String(value)}`)
                  .join(' · ')}
              </div>
            )}
            {!test.ok && (
              <div className="small" style={{ marginTop: 4 }}>
                Сохранить можно, но подключение получит статус «ошибка» и попадёт на экран ошибок.
              </div>
            )}
          </div>
        </div>
      )}
      <ErrorNotice error={runTest.error ?? save.error} />
    </Modal>
  );
}
