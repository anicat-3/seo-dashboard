/**
 * Правила подсветки изменений.
 *
 * Без `projectId` — общие правила для всех проектов. С `projectId` — общие правила
 * и возможность задать для проекта свой порог (правило проекта переопределяет общее).
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import type { MetricInfo, SignalRule } from '../api/types';
import { ErrorNotice, QueryState, StatusBadge } from './ui';

const COMPARISON_LABELS = { wow: 'Неделя к неделе', mom: '30 дней к 30 дням' } as const;

function segmentLabel(segment: string): string {
  return { all: 'все', organic: 'органика', '*': 'каждый сегмент', mobile: 'мобильные', desktop: 'ПК' }[segment] ?? segment;
}

function ThresholdInput({ value, onSave, disabled }: { value: number; onSave: (value: number) => void; disabled?: boolean }) {
  const [draft, setDraft] = useState(String(value));
  const parsed = Number(draft.replace(',', '.'));
  const changed = parsed !== value && parsed > 0 && parsed <= 100;
  return (
    <span className="row" style={{ justifyContent: 'flex-end', flexWrap: 'nowrap' }}>
      <input
        style={{ width: 64, textAlign: 'right' }}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        inputMode="decimal"
        aria-label="Порог, %"
        disabled={disabled}
      />
      %
      {changed && (
        <button className="small primary" onClick={() => onSave(parsed)}>
          Сохранить
        </button>
      )}
    </span>
  );
}

export function RulesPanel({ projectId }: { projectId?: number }) {
  const queryClient = useQueryClient();
  const key = ['rules', projectId ?? 'global'];
  const rules = useQuery({ queryKey: key, queryFn: () => api.get<SignalRule[]>('/signal-rules', { project_id: projectId }) });
  const metrics = useQuery({ queryKey: ['metrics'], queryFn: () => api.get<MetricInfo[]>('/metrics'), staleTime: Infinity });
  const [newMetric, setNewMetric] = useState('');
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['rules'] });

  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Partial<SignalRule>) => api.patch(`/signal-rules/${id}`, body),
    onSuccess: invalidate,
  });
  const create = useMutation({
    mutationFn: (body: Partial<SignalRule>) => api.post('/signal-rules', body),
    onSuccess: () => {
      setNewMetric('');
      invalidate();
    },
  });
  const remove = useMutation({ mutationFn: (id: number) => api.delete(`/signal-rules/${id}`), onSuccess: invalidate });

  const metricByCode = new Map(metrics.data?.map((m) => [m.code, m]));

  return (
    <QueryState query={rules}>
      {(data) => {
        const globals = data.filter((r) => r.project_id === null);
        const overrides = new Map(data.filter((r) => r.project_id !== null).map((r) => [`${r.metric_code}|${r.segment}`, r]));
        // Для проекта показываем общие правила и его собственные; для общего экрана — только общие.
        const orphanOverrides = [...overrides.values()].filter(
          (o) => !globals.some((g) => g.metric_code === o.metric_code && g.segment === o.segment),
        );
        const rows = [...globals, ...orphanOverrides];

        return (
          <>
            <ErrorNotice error={update.error ?? create.error ?? remove.error} />
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Система</th>
                    <th>Метрика</th>
                    <th>Сегмент</th>
                    <th>База сравнения</th>
                    <th className="num">{projectId ? 'Общий порог' : 'Порог ухудшения'}</th>
                    {projectId && <th className="num">Порог проекта</th>}
                    <th>Состояние</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((rule) => {
                    const metric = metricByCode.get(rule.metric_code);
                    const override = projectId ? overrides.get(`${rule.metric_code}|${rule.segment}`) : undefined;
                    const effective = override ?? rule;
                    const editable = projectId ? override : rule;
                    return (
                      <tr key={rule.id}>
                        <td>{metric?.system_name ?? rule.metric_code.split('.')[0]}</td>
                        <td>{metric?.name_ru ?? rule.metric_code}</td>
                        <td>{segmentLabel(rule.segment)}</td>
                        <td>
                          {editable ? (
                            <select
                              value={editable.comparison}
                              onChange={(e) => update.mutate({ id: editable.id, comparison: e.target.value as 'wow' | 'mom' })}
                            >
                              {Object.entries(COMPARISON_LABELS).map(([value, label]) => (
                                <option key={value} value={value}>
                                  {label}
                                </option>
                              ))}
                            </select>
                          ) : (
                            COMPARISON_LABELS[rule.comparison]
                          )}
                        </td>
                        <td className="num">
                          {projectId ? (
                            rule.project_id === null ? `${rule.threshold_pct}%` : '—'
                          ) : (
                            <ThresholdInput
                              key={rule.threshold_pct}
                              value={rule.threshold_pct}
                              onSave={(threshold_pct) => update.mutate({ id: rule.id, threshold_pct })}
                            />
                          )}
                        </td>
                        {projectId && (
                          <td className="num">
                            {override ? (
                              <ThresholdInput
                                key={override.threshold_pct}
                                value={override.threshold_pct}
                                onSave={(threshold_pct) => update.mutate({ id: override.id, threshold_pct })}
                              />
                            ) : (
                              <button
                                className="small"
                                onClick={() =>
                                  create.mutate({
                                    project_id: projectId,
                                    metric_code: rule.metric_code,
                                    segment: rule.segment,
                                    comparison: rule.comparison,
                                    threshold_pct: rule.threshold_pct,
                                  })
                                }
                              >
                                Задать свой
                              </button>
                            )}
                          </td>
                        )}
                        <td>
                          <StatusBadge status={effective.is_active ? 'ok' : 'disabled'} label={effective.is_active ? 'Включено' : 'Выключено'} />
                        </td>
                        <td>
                          <div className="row" style={{ justifyContent: 'flex-end', flexWrap: 'nowrap' }}>
                            {editable && (
                              <button className="small" onClick={() => update.mutate({ id: editable.id, is_active: !editable.is_active })}>
                                {editable.is_active ? 'Выключить' : 'Включить'}
                              </button>
                            )}
                            {override && (
                              <button className="small danger" onClick={() => remove.mutate(override.id)} title="Вернуться к общему правилу">
                                Сбросить
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="panel-body row">
              <select value={newMetric} onChange={(e) => setNewMetric(e.target.value)} aria-label="Метрика для нового правила">
                <option value="">Добавить правило для метрики…</option>
                {metrics.data
                  ?.filter((m) => !rows.some((r) => r.metric_code === m.code))
                  .map((m) => (
                    <option key={m.code} value={m.code}>
                      {m.system_name}: {m.name_ru}
                    </option>
                  ))}
              </select>
              <button
                disabled={!newMetric || create.isPending}
                onClick={() =>
                  create.mutate({
                    project_id: projectId ?? null,
                    metric_code: newMetric,
                    segment: /\.(avg_position|visibility|top\d+)$/.test(newMetric) ? '*' : 'all',
                    comparison: 'wow',
                    threshold_pct: 10,
                  })
                }
              >
                Добавить с порогом 10%
              </button>
            </div>
          </>
        );
      }}
    </QueryState>
  );
}
