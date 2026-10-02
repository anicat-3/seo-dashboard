/** Блок одной системы на дашборде проекта: карточки, графики и дополнительные разделы. */
import { Link } from 'react-router-dom';

import type {
  Annotation,
  Block,
  Card,
  CwvData,
  Distribution,
  DistributionBucket,
  Granularity,
  PsiDevice,
  PsiRow,
  SitemapRow,
} from '../api/types';
import { formatDate, formatShortDate, formatValue, isPositionMetric } from '../lib/format';
import { periodSearch, type PeriodState } from '../lib/period';
import { useTheme } from '../lib/theme';
import { ordinalRamp, TimeSeriesChart } from './Chart';
import { MultiMetricChart } from './MultiMetricChart';
import { Delta, Hint, StatusBadge } from './ui';

function StatCard({ card, compact = false }: { card: Card; compact?: boolean }) {
  return (
    <div className={`stat${compact ? ' compact' : ''}${card.is_signal ? ' is-signal' : ''}`} title={card.is_signal ? 'Резкое ухудшение — см. сигналы' : undefined}>
      <div className="stat-label">{card.label}</div>
      <div className="stat-value">{formatValue(card.value, card.unit)}</div>
      <div className="stat-foot">
        <Delta changePct={card.change_pct} higherIsBetter={card.higher_is_better} position={isPositionMetric(card.metric_code)} />
        <span>было {formatValue(card.baseline, card.unit)}</span>
      </div>
    </div>
  );
}

function Sitemaps({ rows }: { rows: SitemapRow[] }) {
  if (!rows.length) return <div className="muted small">Снимков карт сайта за период нет.</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Карта сайта</th>
            <th>Статус</th>
            <th className="num">URL</th>
            <th className="num">Было</th>
            <th className="num">Ошибки</th>
            <th className="num">Предупр.</th>
            <th>Загружена</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.sitemap_url}>
              <td className="mono">{row.sitemap_url}</td>
              <td>
                <StatusBadge status={row.status} />
              </td>
              <td className="num">{formatValue(row.submitted_urls)}</td>
              <td className="num muted">{formatValue(row.submitted_urls_before)}</td>
              <td className="num">{row.errors || '—'}</td>
              <td className="num">{row.warnings || '—'}</td>
              <td className="nowrap">{formatDate(row.last_downloaded_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const CWV_METRICS: { key: string; label: string; hint: string; unit: string; good: number; poor: number }[] = [
  { key: 'lcp', label: 'LCP', hint: 'отрисовка основного контента', unit: 'мс', good: 2500, poor: 4000 },
  { key: 'inp', label: 'INP', hint: 'отклик на действия пользователя', unit: 'мс', good: 200, poor: 500 },
  { key: 'cls', label: 'CLS', hint: 'сдвиги макета при загрузке', unit: '', good: 0.1, poor: 0.25 },
  { key: 'fcp', label: 'FCP', hint: 'первая отрисовка', unit: 'мс', good: 1800, poor: 3000 },
  { key: 'ttfb', label: 'TTFB', hint: 'время ответа сервера', unit: 'мс', good: 800, poor: 1800 },
];

function cwvStatus(value: number | null, good: number, poor: number): { status: string; label: string } {
  if (value === null) return { status: 'pending', label: 'нет данных' };
  if (value <= good) return { status: 'ok', label: 'хорошо' };
  if (value <= poor) return { status: 'warning', label: 'нужно улучшить' };
  return { status: 'error', label: 'плохо' };
}

function formatCwv(value: number | null, key: string): string {
  if (value === null) return '—';
  return key === 'cls' ? value.toFixed(2).replace('.', ',') : `${Math.round(value)} мс`;
}

function Cwv({ data }: { data: CwvData }) {
  const devices = [
    { key: 'phone', label: 'Мобильные' },
    { key: 'desktop', label: 'ПК' },
  ].filter((d) => data.latest[d.key]);
  if (!devices.length) return <div className="muted small">Данных CrUX за период нет.</div>;
  return (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Метрика</th>
              {devices.map((d) => (
                <th key={d.key} className="wrap">
                  {d.label}: у 75% загрузок не хуже
                </th>
              ))}
              {devices.map((d) => (
                <th key={d.key} className="num wrap">
                  Доля быстрых загрузок, {d.label.toLowerCase()}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {CWV_METRICS.map((metric) => (
              <tr key={metric.key}>
                <td>
                  <b>{metric.label}</b>
                  <div className="small muted">{metric.hint}</div>
                </td>
                {devices.map((d) => {
                  const point = data.latest[d.key]?.[metric.key];
                  const state = cwvStatus(point?.p75 ?? null, metric.good, metric.poor);
                  return (
                    <td key={d.key}>
                      <span className="cwv-cell">
                        <span className="cwv-value">{formatCwv(point?.p75 ?? null, metric.key)}</span>
                        <StatusBadge status={state.status} label={state.label} />
                      </span>
                    </td>
                  );
                })}
                {devices.map((d) => (
                  <td key={d.key} className="num">
                    {formatValue(data.latest[d.key]?.[metric.key]?.good_pct, '%')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="charts">
        {CWV_METRICS.slice(0, 3).map((metric) => (
          <div className="chart-card" key={metric.key}>
            <h3>
              {metric.label} по неделям{metric.unit ? `, ${metric.unit}` : ''}
            </h3>
            <TimeSeriesChart
              series={devices.map((d) => ({ name: d.label, points: data.series[d.key]?.[metric.key] ?? [] }))}
              height={200}
            />
          </div>
        ))}
      </div>
    </>
  );
}

function PsiCell({ run }: { run: PsiDevice | null }) {
  if (!run) return <td className="muted">—</td>;
  const score = run.performance_score;
  const status = score === null ? 'pending' : score >= 90 ? 'ok' : score >= 50 ? 'warning' : 'error';
  return (
    <td>
      <div className="row">
        <b>{formatValue(score)}</b>
        <StatusBadge status={status} label={status === 'ok' ? 'хорошо' : status === 'warning' ? 'средне' : 'плохо'} />
      </div>
      <div className="small muted">
        LCP {formatCwv(run.lcp, 'lcp')} · INP {formatCwv(run.inp, 'inp')} · CLS {formatCwv(run.cls, 'cls')}
        {run.is_origin_fallback ? ' · полевые данные по сайту' : ''}
      </div>
    </td>
  );
}

function Psi({ rows }: { rows: PsiRow[] }) {
  if (!rows.length) return <div className="muted small">Добавьте URL для проверки в настройках проекта.</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>URL</th>
            <th>Мобильные</th>
            <th>ПК</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.url}>
              <td>
                <div className="mono">{row.url}</div>
                {row.template_name && <div className="small muted">{row.template_name}</div>}
              </td>
              <PsiCell run={row.mobile} />
              <PsiCell run={row.desktop} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const BUCKETS: { key: DistributionBucket; label: string }[] = [
  { key: '1-3', label: 'ТОП 1–3' },
  { key: '4-10', label: '4–10' },
  { key: '11-30', label: '11–30' },
  { key: '31-100', label: '31–100' },
  { key: '100+', label: 'Не найдено' },
];

function DistributionCharts({ items }: { items: Distribution[] }) {
  const [theme] = useTheme();
  const ramp = ordinalRamp(theme);
  return (
    <div className="charts">
      {items.map((item) => (
        <div className="chart-card" key={item.segment}>
          <h3>Распределение по топам · {item.label}</h3>
          <TimeSeriesChart
            kind="stacked"
            series={BUCKETS.map((bucket, index) => ({
              name: bucket.label,
              color: ramp[index],
              points: item.points.map((p) => [p.date, p[bucket.key]] as [string, number]),
            }))}
          />
        </div>
      ))}
    </div>
  );
}

export function BlockView({
  block,
  projectRef,
  period,
  granularity,
  annotations,
  isAdmin,
  showResource = false,
}: {
  block: Block;
  /** Адрес проекта (slug) для ссылок на детализацию. */
  projectRef: string;
  period: PeriodState;
  granularity: Granularity;
  annotations: Annotation[];
  /** Ссылка на экран ошибок сбора видна только администратору. */
  isAdmin: boolean;
  /** Показать название подключённого ресурса (позиции или несколько подключений одной системы). */
  showResource?: boolean;
}) {
  const marks = annotations.map((a) => ({ date: a.date, text: `${a.text} — ${a.author_name}` }));
  const search = periodSearch(period);
  const isPositions = block.system_code === 'topvisor' || block.system_code === 'seranking';
  const hasData = block.history_from !== null;
  // Цели — отдельной секцией: при большом их числе они не теряются среди основных метрик.
  const goalCards = block.cards.filter((card) => card.metric_code.endsWith('.goals'));
  const mainCards = block.cards.filter((card) => !card.metric_code.endsWith('.goals'));

  return (
    <section className="panel block" id={`block-${block.integration_id}`}>
      <div className="panel-header">
        <div className="block-title">
          <h2>{block.system_name}</h2>
          {showResource && <span className="secondary">{block.external_name ?? block.external_id}</span>}
          {block.system_code === 'crux' && (
            <Hint label="Что означают показатели">
              Данные реальных посетителей из отчёта Chrome UX Report за последние 28 дней. <b>Значение метрики</b> — уровень, в
              который укладываются 75% загрузок страниц (75-й перцентиль, p75): у трёх посещений из четырёх показатель не хуже
              указанного. <b>Доля быстрых загрузок</b> — процент посещений, у которых метрика попала в зону «хорошо» по порогам
              Google.
            </Hint>
          )}
          {block.status !== 'ok' && <StatusBadge status={block.status} />}
        </div>
        <div className="row small">
          {isPositions && <Link to={`/projects/${projectRef}/keywords/${block.integration_id}${search}`}>Позиции по запросам →</Link>}
          {block.extras.issues && <Link to={`/projects/${projectRef}/issues/${block.integration_id}${search}`}>Все ошибки →</Link>}
          {block.extras.sitemaps && <Link to={`/projects/${projectRef}/sitemaps/${block.integration_id}${search}`}>История карт сайта →</Link>}
        </div>
      </div>
      <div className="panel-body stack">
        {block.status === 'error' && (
          <div className="notice error">
            Ошибка сбора: {(block.last_error ?? 'неизвестная ошибка').replace(/\.$/, '')}.{' '}
            {isAdmin ? <Link to="/errors">Экран ошибок</Link> : 'Администратор получит уведомление на экране ошибок.'}
          </div>
        )}
        {block.incomplete_dates.length > 0 && (
          <div className="notice warn">
            Данные неполные: сбор не прошёл за {block.incomplete_dates.length} дн. (
            {block.incomplete_dates.slice(0, 6).map(formatShortDate).join(', ')}
            {block.incomplete_dates.length > 6 ? '…' : ''}).
          </div>
        )}
        {!hasData ? (
          <div className="notice info">Данных пока нет: история загружается после подключения.</div>
        ) : (
          block.history_from! > period.from && (
            <div className="notice info">История доступна с {formatDate(block.history_from)}</div>
          )
        )}

        {hasData && mainCards.length > 0 && (
          <div className="cards">
            {mainCards.map((card) => (
              <StatCard key={`${card.metric_code}:${card.segment}`} card={card} />
            ))}
          </div>
        )}

        {hasData && goalCards.length > 0 && (
          <div className="goals-panel">
            <div className="goals-panel-title">Достижения целей за период</div>
            <div className="cards goal-cards">
              {goalCards.map((card) => (
                <StatCard key={`${card.metric_code}:${card.segment}`} card={card} compact />
              ))}
            </div>
          </div>
        )}

        {hasData && block.charts.length > 0 && (
          <div className="charts" style={{ marginTop: 0 }}>
            {block.charts.map((chart) =>
              chart.kind === 'multi' ? (
                <div className="chart-card chart-wide" key={chart.title}>
                  <h3>{chart.title}</h3>
                  <MultiMetricChart series={chart.series} defaultVisible={chart.default_visible} marks={marks} granularity={granularity} />
                </div>
              ) : (
              <div className="chart-card" key={chart.title}>
                <h3>
                  {chart.title}
                  {chart.note && <span className="chart-note"> — {chart.note}</span>}
                </h3>
                <TimeSeriesChart
                  kind={chart.kind === 'bar' ? 'bar' : 'line'}
                  granularity={granularity}
                  unit={chart.series[0]?.unit}
                  inverse={chart.series.every((s) => s.inverse) && chart.series[0]?.metric_code.endsWith('position')}
                  series={chart.series.map((s) => ({ name: s.name, points: s.points }))}
                  marks={marks}
                />
              </div>
              ),
            )}
          </div>
        )}

        {block.extras.distribution && block.extras.distribution.length > 0 && <DistributionCharts items={block.extras.distribution} />}
        {block.extras.cwv && <Cwv data={block.extras.cwv} />}
        {block.extras.psi && (
          <div className="sub-section">
            <h3>Проверяемые страницы</h3>
            <Psi rows={block.extras.psi} />
          </div>
        )}
        {block.extras.issues && (
          <div className="sub-section">
            <h3>Открытые ошибки диагностики: {block.extras.issues.length}</h3>
            {block.extras.issues.length === 0 ? (
              <div className="muted small">Открытых ошибок нет.</div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Ошибка</th>
                      <th>Критичность</th>
                      <th>Появилась</th>
                      <th className="num">Затронуто</th>
                    </tr>
                  </thead>
                  <tbody>
                    {block.extras.issues.map((issue) => (
                      <tr key={issue.id}>
                        <td>{issue.title}</td>
                        <td>
                          <SeverityBadge severity={issue.severity} />
                        </td>
                        <td className="nowrap">{formatDate(issue.first_seen_at)}</td>
                        <td className="num">{formatValue(issue.affected_count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        {block.extras.sitemaps && (
          <div className="sub-section">
            <h3>Карты сайта</h3>
            <Sitemaps rows={block.extras.sitemaps} />
          </div>
        )}
      </div>
    </section>
  );
}

const SEVERITY: Record<string, { status: string; label: string }> = {
  FATAL: { status: 'error', label: 'Фатальная' },
  CRITICAL: { status: 'error', label: 'Критичная' },
  POSSIBLE_PROBLEM: { status: 'warning', label: 'Возможная проблема' },
  RECOMMENDATION: { status: 'pending', label: 'Рекомендация' },
};

export function SeverityBadge({ severity }: { severity: string }) {
  const item = SEVERITY[severity] ?? { status: 'pending', label: severity };
  return <StatusBadge status={item.status} label={item.label} />;
}
