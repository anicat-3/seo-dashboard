import { Link, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import type { Project, Signal } from '../api/types';
import { Delta, PageHeader, QueryState, systemShort } from '../components/ui';
import { formatDateTime, formatRange, formatValue, isPositionMetric } from '../lib/format';

/** Строка сигнала: метрика, значение и база сравнения, отметка «просмотрено». */
export function SignalItem({ signal }: { signal: Signal }) {
  const queryClient = useQueryClient();
  const markSeen = useMutation({
    mutationFn: () => api.post(`/signals/${signal.id}/seen`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['signals'] });
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      void queryClient.invalidateQueries({ queryKey: ['overview'] });
    },
  });

  return (
    <div className={`signal-item${signal.status === 'new' ? ' new' : ''}`}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div>
          {signal.kind === 'issue' ? '⚠ ' : ''}
          <b>{signal.message}</b>
        </div>
        <div className="small muted">
          {signal.project_slug && (
            <>
              <Link to={`/projects/${signal.project_slug}`}>{signal.project_name}</Link> ·{' '}
            </>
          )}
          {signal.system_code ? `${systemShort(signal.system_code)} · ` : ''}
          обнаружено {formatDateTime(signal.detected_at)}
          {signal.period_from && signal.period_to && ` · период ${formatRange(signal.period_from, signal.period_to)}`}
          {signal.resolved_at && ` · закрыт ${formatDateTime(signal.resolved_at)}`}
        </div>
      </div>
      {signal.kind === 'metric' && (
        <div className="small nowrap secondary" style={{ textAlign: 'right' }}>
          {formatValue(signal.value)} <span className="muted">против</span> {formatValue(signal.baseline)}
          <div>
            {/* Сигнал — всегда ухудшение: рост плох для метрик, где меньше — лучше. */}
            <Delta changePct={signal.change_pct} higherIsBetter={(signal.change_pct ?? 0) <= 0} position={isPositionMetric(signal.metric_code)} />
          </div>
        </div>
      )}
      {signal.status === 'new' ? (
        <button className="small no-print" onClick={() => markSeen.mutate()} disabled={markSeen.isPending}>
          Просмотрено
        </button>
      ) : (
        <span className="small muted nowrap">✓ {signal.seen_by_name}</span>
      )}
    </div>
  );
}

/** Все сигналы по проектам с фильтром по проекту и истории закрытых. */
export function SignalsPage() {
  const [params, setParams] = useSearchParams();
  const projectId = params.get('project') ?? '';
  const includeResolved = params.get('resolved') === '1';

  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api.get<Project[]>('/projects') });
  const signals = useQuery({
    queryKey: ['signals', projectId, includeResolved],
    queryFn: () =>
      api.get<Signal[]>('/signals', { project_id: projectId || undefined, include_resolved: includeResolved }),
  });

  function setParam(key: string, value: string) {
    const copy = new URLSearchParams(params);
    if (value) copy.set(key, value);
    else copy.delete(key);
    setParams(copy, { replace: true });
  }

  return (
    <>
      <PageHeader title="Сигналы" subtitle="Резкие изменения метрик и новые ошибки диагностики">
        <select value={projectId} onChange={(e) => setParam('project', e.target.value)} aria-label="Проект">
          <option value="">Все проекты</option>
          {projects.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <label className="row small">
          <input type="checkbox" checked={includeResolved} onChange={(e) => setParam('resolved', e.target.checked ? '1' : '')} />
          Показывать закрытые
        </label>
      </PageHeader>
      <QueryState query={signals}>
        {(data) =>
          data.length === 0 ? (
            <div className="panel empty">Сигналов нет — резких изменений не найдено.</div>
          ) : (
            <div className="panel signal-list">
              {data.map((signal) => (
                <SignalItem key={signal.id} signal={signal} />
              ))}
            </div>
          )
        }
      </QueryState>
    </>
  );
}
