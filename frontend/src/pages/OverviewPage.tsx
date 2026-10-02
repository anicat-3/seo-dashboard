import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import { useUser } from '../auth/AuthContext';
import type { Overview, OverviewCell } from '../api/types';
import { PeriodPicker } from '../components/PeriodPicker';
import { Delta, PageHeader, QueryState, SystemChips } from '../components/ui';
import { formatRange, formatValue, isPositionMetric } from '../lib/format';
import { periodQuery, periodSearch, usePeriod } from '../lib/period';

function Cell({ cell }: { cell: OverviewCell | null }) {
  if (!cell) return <td className="num muted">—</td>;
  return (
    <td className={`num${cell.is_signal ? ' cell-signal' : ''}`} title={cell.is_signal ? 'Резкое ухудшение' : undefined}>
      <div>{formatValue(cell.value, cell.unit)}</div>
      <Delta changePct={cell.change_pct} higherIsBetter={cell.higher_is_better} position={isPositionMetric(cell.metric_code)} />
    </td>
  );
}

/** Сводный экран по всем проектам с изменениями и подсвеченными сигналами. */
export function OverviewPage() {
  const [period, setPeriod] = usePeriod();
  const isAdmin = useUser().role === 'admin';
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ['overview', period],
    queryFn: () => api.get<Overview>('/overview', periodQuery(period)),
  });
  // Избранное закреплено за сотрудником, выбранным при входе.
  const favorite = useMutation({
    mutationFn: ({ slug, on }: { slug: string; on: boolean }) =>
      on ? api.put(`/projects/${slug}/favorite`) : api.delete(`/projects/${slug}/favorite`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['overview'] });
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });

  return (
    <>
      <PageHeader
        title="Сводка по проектам"
        subtitle={
          query.data &&
          `${formatRange(query.data.period.date_from, query.data.period.date_to)} · сравнение с ${formatRange(
            query.data.compare.date_from,
            query.data.compare.date_to,
          )}`
        }
      >
        <PeriodPicker period={period} onChange={setPeriod} />
      </PageHeader>
      <QueryState query={query}>
        {(data) =>
          data.rows.length === 0 ? (
            <div className="panel empty">
              Проектов пока нет. <Link to="/projects">Создайте первый проект</Link>.
            </div>
          ) : (
            <div className="panel table-wrap">
              <table>
                <thead>
                  <tr>
                    <th aria-label="Избранное" />
                    <th>Проект</th>
                    {data.columns.map((column) => (
                      <th key={column.key} className="num overview-head">
                        {column.title}
                      </th>
                    ))}
                    <th className="num overview-head">Сигналы</th>
                    <th className="num overview-head">Ошибки сбора</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr key={row.project.id} className={row.signals_new ? 'signal-row' : ''}>
                      <td style={{ width: 32, paddingRight: 0 }}>
                        <button
                          className={`star-btn${row.is_favorite ? ' on' : ''}`}
                          onClick={() => favorite.mutate({ slug: row.project.slug, on: !row.is_favorite })}
                          title={row.is_favorite ? 'Убрать из избранного' : 'В избранное: проект будет показываться первым'}
                          aria-pressed={row.is_favorite}
                          aria-label={row.is_favorite ? 'Убрать из избранного' : 'Добавить в избранное'}
                        >
                          {row.is_favorite ? '★' : '☆'}
                        </button>
                      </td>
                      <td className="overview-project">
                        <Link to={`/projects/${row.project.slug}${periodSearch(period)}`}>
                          <b>{row.project.name}</b>
                        </Link>
                        <div className="small muted">{row.project.domain}</div>
                        <SystemChips systems={row.systems} />
                      </td>
                      {data.columns.map((column) => (
                        <Cell key={column.key} cell={row.cells[column.key]} />
                      ))}
                      <td className="num">
                        {row.signals_open ? (
                          <Link to={`/signals?project=${row.project.id}`}>
                            <span className={row.signals_new ? 'badge signal' : 'badge'}>
                              {row.signals_new ? `${row.signals_new} новых` : `${row.signals_open} просм.`}
                            </span>
                          </Link>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td className="num">
                        {row.errors ? (
                          isAdmin ? (
                            <Link to="/errors">
                              <span className="badge error">
                                <span className="dot" />
                                {row.errors}
                              </span>
                            </Link>
                          ) : (
                            <span className="badge error">
                              <span className="dot" />
                              {row.errors}
                            </span>
                          )
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </QueryState>
    </>
  );
}
