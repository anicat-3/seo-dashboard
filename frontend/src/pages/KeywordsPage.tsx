import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { api, csvUrl } from '../api/client';
import type { KeywordRow, KeywordsResponse } from '../api/types';
import type { CalendarMarks } from '../components/DateRangePicker';
import { PeriodPicker } from '../components/PeriodPicker';
import { PageHeader, QueryState } from '../components/ui';
import { formatDate, formatRange } from '../lib/format';
import { periodQuery, periodSearch, usePeriod } from '../lib/period';

type SortKey = 'keyword' | 'position' | 'change';

function PositionChange({ change }: { change: number | null }) {
  if (change === null) return <span className="muted">—</span>;
  if (change === 0) return <span className="delta flat">0</span>;
  // Положительное изменение — запрос поднялся выше.
  return <span className={`delta ${change > 0 ? 'good' : 'bad'}`}>{change > 0 ? `▲ ${change}` : `▼ ${Math.abs(change)}`}</span>;
}

/** Заголовок колонки позиций: «Позиция 28.09.2026», если съём у всех запросов в один день. */
function positionTitle(dates: string[] | undefined, fallback: string): string {
  if (dates?.length === 1) {
    const [year, month, day] = dates[0].split('-');
    return `Позиция ${day}.${month}.${year}`;
  }
  return fallback;
}

function sortRows(rows: KeywordRow[], key: SortKey, asc: boolean): KeywordRow[] {
  const direction = asc ? 1 : -1;
  // Запросы без значения всегда в конце списка.
  const value = (row: KeywordRow) => (key === 'keyword' ? row.keyword : row[key]);
  return [...rows].sort((a, b) => {
    const left = value(a);
    const right = value(b);
    if (left === null) return 1;
    if (right === null) return -1;
    return (typeof left === 'string' ? left.localeCompare(right as string, 'ru') : left - (right as number)) * direction;
  });
}

/** Детализация позиций по запросам с фильтрами и выгрузкой в CSV. */
export function KeywordsPage() {
  const { projectRef, integrationId } = useParams();
  const [period, setPeriod] = usePeriod();
  const [segment, setSegment] = useState('');
  const [group, setGroup] = useState('');
  const [search, setSearch] = useState('');
  const [top, setTop] = useState('');
  const [sort, setSort] = useState<{ key: SortKey; asc: boolean }>({ key: 'position', asc: true });

  const filters = { ...periodQuery(period), segment, group, search, top };
  const marks = useQuery({
    queryKey: ['calendar', projectRef],
    queryFn: () => api.get<CalendarMarks>(`/projects/${projectRef}/calendar`),
    staleTime: 10 * 60_000,
  });
  const query = useQuery({
    queryKey: ['keywords', integrationId, filters],
    queryFn: () => api.get<KeywordsResponse>(`/integrations/${integrationId}/keywords`, filters),
    placeholderData: (previous) => previous,
  });
  // Если у всех запросов один день съёма, дата стоит в заголовке колонки, а не в каждой строке.
  const sameDates = (query.data?.check_dates.length ?? 0) <= 1 && (query.data?.check_dates_before.length ?? 0) <= 1;
  const rows = useMemo(() => sortRows(query.data?.rows ?? [], sort.key, sort.asc), [query.data, sort]);

  const header = (key: SortKey, label: string, numeric = false) => (
    <th
      className={`sortable${numeric ? ' num' : ''}`}
      onClick={() => setSort({ key, asc: sort.key === key ? !sort.asc : true })}
      aria-sort={sort.key === key ? (sort.asc ? 'ascending' : 'descending') : 'none'}
    >
      {label} {sort.key === key ? (sort.asc ? '↑' : '↓') : ''}
    </th>
  );

  return (
    <>
      <PageHeader
        title="Позиции по запросам"
        subtitle={
          query.data &&
          `Последний съём за ${formatRange(query.data.period.date_from, query.data.period.date_to)} против ${formatRange(
            query.data.compare.date_from,
            query.data.compare.date_to,
          )}`
        }
      >
        <Link to={`/projects/${projectRef}${periodSearch(period)}`}>
          <button>← К дашборду</button>
        </Link>
        <a href={csvUrl(`/integrations/${integrationId}/keywords`, filters)}>
          <button>Выгрузить CSV</button>
        </a>
      </PageHeader>
      <div className="stack">
        <PeriodPicker period={period} onChange={setPeriod} marks={marks.data} />
        <div className="row">
          <input placeholder="Поиск по запросу" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Поиск по запросу" />
          <select value={segment} onChange={(e) => setSegment(e.target.value)} aria-label="Поисковик и регион">
            <option value="">Все поисковики и регионы</option>
            {query.data?.segments.map((s) => (
              <option key={s} value={s}>
                {s.replace(':', ' · ')}
              </option>
            ))}
          </select>
          <select value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Группа">
            <option value="">Все группы</option>
            {query.data?.groups.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
          <select value={top} onChange={(e) => setTop(e.target.value)} aria-label="Топ">
            <option value="">Любая позиция</option>
            <option value="3">ТОП-3</option>
            <option value="10">ТОП-10</option>
            <option value="30">ТОП-30</option>
          </select>
          <span className="muted small">Запросов: {rows.length}</span>
        </div>
        <QueryState query={query}>
          {() => (
            <div className="panel table-wrap">
              <table>
                <thead>
                  <tr>
                    {header('keyword', 'Запрос')}
                    <th>Группа</th>
                    <th>Поисковик · регион</th>
                    {header('position', positionTitle(query.data?.check_dates, 'Позиция'), true)}
                    <th className="num">{positionTitle(query.data?.check_dates_before, 'Было')}</th>
                    {header('change', 'Изменение', true)}
                    {!sameDates && <th>Дата съёма</th>}
                    <th>URL</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.keyword_id}>
                      <td>{row.keyword}</td>
                      <td className="muted">{row.group ?? '—'}</td>
                      <td className="nowrap">{row.segment.replace(':', ' · ')}</td>
                      <td className="num">{row.position ?? <span className="muted">нет</span>}</td>
                      <td className="num muted">{row.position_before ?? '—'}</td>
                      <td className="num">
                        <PositionChange change={row.change} />
                      </td>
                      {!sameDates && <td className="nowrap">{formatDate(row.check_date)}</td>}
                      <td className="mono">{row.url ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {rows.length === 0 && <div className="empty">Запросов по выбранным условиям нет.</div>}
            </div>
          )}
        </QueryState>
      </div>
    </>
  );
}
