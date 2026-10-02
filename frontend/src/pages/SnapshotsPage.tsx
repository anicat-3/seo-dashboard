import { useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { api, csvUrl } from '../api/client';
import type { IssueRow, SitemapRow } from '../api/types';
import { SeverityBadge } from '../components/BlockView';
import { PeriodPicker } from '../components/PeriodPicker';
import { PageHeader, QueryState, StatusBadge } from '../components/ui';
import { formatDate, formatValue } from '../lib/format';
import { periodQuery, periodSearch, usePeriod } from '../lib/period';

function Issues({ integrationId }: { integrationId: string }) {
  const [state, setState] = useState('all');
  const query = useQuery({
    queryKey: ['issues', integrationId, state],
    queryFn: () => api.get<IssueRow[]>(`/integrations/${integrationId}/issues`, { state }),
  });
  return (
    <div className="stack">
      <div className="row">
        <div className="segmented">
          {[
            ['all', 'Все'],
            ['open', 'Открытые'],
            ['resolved', 'Исправленные'],
          ].map(([value, label]) => (
            <button key={value} className={state === value ? 'active' : ''} onClick={() => setState(value)}>
              {label}
            </button>
          ))}
        </div>
        <a href={csvUrl(`/integrations/${integrationId}/issues`, { state })}>
          <button>Выгрузить CSV</button>
        </a>
      </div>
      <QueryState query={query}>
        {(rows) => (
          <div className="panel table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ошибка</th>
                  <th>Критичность</th>
                  <th>Состояние</th>
                  <th>Появилась</th>
                  <th>Последний раз</th>
                  <th>Исправлена</th>
                  <th className="num">Затронуто</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>
                      {row.title}
                      <div className="small muted mono">{row.issue_code}</div>
                    </td>
                    <td>
                      <SeverityBadge severity={row.severity} />
                    </td>
                    <td>
                      <StatusBadge status={row.state ?? 'open'} />
                    </td>
                    <td className="nowrap">{formatDate(row.first_seen_at)}</td>
                    <td className="nowrap">{formatDate(row.last_seen_at)}</td>
                    <td className="nowrap">{formatDate(row.resolved_at)}</td>
                    <td className="num">{formatValue(row.affected_count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 && <div className="empty">Ошибок нет.</div>}
          </div>
        )}
      </QueryState>
    </div>
  );
}

function Sitemaps({ integrationId }: { integrationId: string }) {
  const [period, setPeriod] = usePeriod();
  const query = useQuery({
    queryKey: ['sitemaps', integrationId, period],
    queryFn: () => api.get<SitemapRow[]>(`/integrations/${integrationId}/sitemaps`, periodQuery(period)),
  });
  return (
    <div className="stack">
      <div className="row">
        <PeriodPicker period={period} onChange={setPeriod} />
        <a href={csvUrl(`/integrations/${integrationId}/sitemaps`, periodQuery(period))}>
          <button>Выгрузить CSV</button>
        </a>
      </div>
      <QueryState query={query}>
        {(rows) => (
          <div className="panel table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Дата снимка</th>
                  <th>Карта сайта</th>
                  <th>Статус</th>
                  <th className="num">URL</th>
                  <th className="num">Ошибки</th>
                  <th className="num">Предупр.</th>
                  <th>Загружена</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={`${row.snapshot_date}|${row.sitemap_url}`}>
                    <td className="nowrap">{formatDate(row.snapshot_date)}</td>
                    <td className="mono">{row.sitemap_url}</td>
                    <td>
                      <StatusBadge status={row.status} />
                    </td>
                    <td className="num">{formatValue(row.submitted_urls)}</td>
                    <td className="num">{row.errors || '—'}</td>
                    <td className="num">{row.warnings || '—'}</td>
                    <td className="nowrap">{formatDate(row.last_downloaded_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 && <div className="empty">Снимков за период нет.</div>}
          </div>
        )}
      </QueryState>
    </div>
  );
}

/** Детализация снимков состояния: ошибки диагностики и история карт сайта. */
export function SnapshotsPage() {
  const { projectRef, kind, integrationId } = useParams();
  const [period] = usePeriod();
  if (!integrationId || (kind !== 'issues' && kind !== 'sitemaps')) return <Navigate to={`/projects/${projectRef}`} replace />;

  return (
    <>
      <PageHeader title={kind === 'issues' ? 'Ошибки диагностики' : 'История карт сайта'}>
        <Link to={`/projects/${projectRef}${periodSearch(period)}`}>
          <button>← К дашборду</button>
        </Link>
      </PageHeader>
      {kind === 'issues' ? <Issues integrationId={integrationId} /> : <Sitemaps integrationId={integrationId} />}
    </>
  );
}
