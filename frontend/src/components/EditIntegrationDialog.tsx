/**
 * Изменение подключённой системы без повторного подключения:
 * аккаунт (доступ) и избранные цели GA4/Метрики.
 *
 * Ресурс (сайт, счётчик, проект) не меняется: накопленная история относится
 * к нему. Для другого ресурса подключение создаётся заново.
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import type { Credential, Goal, Integration } from '../api/types';
import { ErrorNotice, Modal, systemShort } from './ui';

const ANALYTICS = new Set(['ga4', 'metrika']);

export function EditIntegrationDialog({ integration, onClose }: { integration: Integration; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [credentialId, setCredentialId] = useState(integration.credential_id);
  const [goalIds, setGoalIds] = useState(() => new Set(integration.goals.map((g) => g.external_goal_id)));

  const credentials = useQuery({
    queryKey: ['credentials', integration.system_code],
    queryFn: () => api.get<Credential[]>('/credentials', { system_code: integration.system_code }),
  });
  const goals = useQuery({
    queryKey: ['goals', credentialId, integration.external_id],
    queryFn: () => api.get<Goal[]>(`/credentials/${credentialId}/goals`, { external_id: integration.external_id }),
    enabled: ANALYTICS.has(integration.system_code),
  });

  // Цели, которых больше нет в системе, остаются в списке, чтобы их можно было снять.
  const goalOptions = [
    ...(goals.data ?? []),
    ...integration.goals.filter((g) => !goals.data?.some((x) => x.external_goal_id === g.external_goal_id)),
  ];

  const save = useMutation({
    mutationFn: () =>
      api.patch(`/integrations/${integration.id}`, {
        credential_id: credentialId,
        ...(ANALYTICS.has(integration.system_code) && {
          goals: goalOptions.filter((g) => goalIds.has(g.external_goal_id)).map((g) => ({ external_goal_id: g.external_goal_id, name: g.name })),
        }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['integrations', integration.project_id] });
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      onClose();
    },
  });

  return (
    <Modal
      title={`Изменить подключение: ${systemShort(integration.system_code)}`}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Отмена</button>
          <button className="primary" onClick={() => save.mutate()} disabled={save.isPending}>
            Сохранить
          </button>
        </>
      }
    >
      <div className="field">
        Ресурс
        <div style={{ color: 'var(--text-primary)' }}>
          {integration.external_name ?? integration.external_id}
          <div className="small muted mono">{integration.external_id}</div>
        </div>
        <span className="field-hint">Ресурс не меняется: история собрана по нему. Для другого ресурса подключите систему заново.</span>
      </div>

      <label className="field">
        Аккаунт
        <select value={credentialId} onChange={(e) => setCredentialId(Number(e.target.value))}>
          {credentials.data?.map((credential) => (
            <option key={credential.id} value={credential.id}>
              {credential.label}
              {credential.status === 'error' ? ' (ошибка доступа)' : ''}
            </option>
          ))}
        </select>
        <span className="field-hint">Например, если ресурс перенесли в другой Google-аккаунт или доступ переподключили.</span>
      </label>

      {ANALYTICS.has(integration.system_code) && (
        <div className="field">
          Избранные цели
          {goals.isPending ? (
            <span className="muted small">Загрузка целей…</span>
          ) : (
            goalOptions.map((goal) => (
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
          <ErrorNotice error={goals.error} />
        </div>
      )}

      <ErrorNotice error={save.error} />
    </Modal>
  );
}
