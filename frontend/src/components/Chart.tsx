/**
 * Графики временных рядов на ECharts.
 *
 * Правила оформления: одна шкала на график, линии 2px, столбцы не шире 24px
 * со скруглённым верхом, сетка и оси — приглушённые, легенда показывается
 * для двух и более серий, цвета серий назначаются в фиксированном порядке
 * и не меняются, когда часть серий скрыта.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { BarChart, LineChart } from 'echarts/charts';
import { GridComponent, MarkLineComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';

import type { Granularity } from '../api/types';
import { cssVar, useTheme } from '../lib/theme';
import { formatCompact, formatMonth, formatShortDate, formatValue } from '../lib/format';

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, MarkLineComponent, CanvasRenderer]);

export interface ChartSeries {
  name: string;
  points: [string, number | null][];
  /** CSS-цвет; по умолчанию — слот категориальной палитры по порядку серии. */
  color?: string;
}

export interface ChartMark {
  date: string;
  text: string;
}

interface Props {
  series: ChartSeries[];
  kind?: 'line' | 'bar' | 'stacked';
  unit?: string;
  /** Перевернуть ось: для позиций меньшее значение — выше. */
  inverse?: boolean;
  marks?: ChartMark[];
  height?: number;
  /** Группировка точек: влияет на подписи дат. */
  granularity?: Granularity;
}

const SERIES_SLOTS = 8;
/** При большем числе столбцов зазор между ними не рисуется, иначе он «съедает» сами столбцы. */
const MAX_BARS_WITH_GAP = 45;

function escapeHtml(text: string): string {
  return text.replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch] ?? ch);
}

function axisDate(value: string, granularity: Granularity): string {
  return granularity === 'month' ? formatMonth(value) : formatShortDate(value);
}

function tooltipDate(value: string, granularity: Granularity): string {
  if (granularity === 'month') return formatMonth(value);
  if (granularity === 'week') return `Неделя с ${formatShortDate(value)}`;
  return formatShortDate(value);
}

export function TimeSeriesChart({
  series,
  kind = 'line',
  unit = '',
  inverse = false,
  marks = [],
  height = 240,
  granularity = 'day',
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [theme] = useTheme();
  // Название серии, оставленной на графике одной (клик по легенде); null — показаны все.
  const [solo, setSolo] = useState<string | null>(null);

  const dates = useMemo(() => {
    const all = new Set<string>();
    series.forEach((s) => s.points.forEach(([date]) => all.add(date)));
    return [...all].sort();
  }, [series]);

  const colors = useMemo(
    () => series.map((s, i) => s.color ?? cssVar(`--series-${(i % SERIES_SLOTS) + 1}`)),
    // Цвета перечитываются при смене темы.
    [series, theme],
  );

  // Если выбранная серия исчезла (сменился период или набор целей) — показать все.
  const activeSolo = solo !== null && series.some((s) => s.name === solo) ? solo : null;

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const surface = cssVar('--surface-1');
    const muted = cssVar('--text-muted');
    const grid = cssVar('--grid');
    const axis = cssVar('--axis');
    const textPrimary = cssVar('--text-primary');
    const fontFamily = cssVar('--font');
    // Пометка привязывается к началу интервала, в который попадает её дата.
    const markDates = marks
      .map((m) => ({ ...m, axisDate: [...dates].reverse().find((d) => d <= m.date) }))
      .filter((m): m is ChartMark & { axisDate: string } => m.axisDate !== undefined && m.date <= (dates[dates.length - 1] ?? ''));
    const stacked = kind === 'stacked';
    const visible = series.map((s, index) => ({ s, index })).filter(({ s }) => activeSolo === null || s.name === activeSolo);
    const barGap = dates.length <= MAX_BARS_WITH_GAP;

    chart.setOption(
      {
        animation: false,
        textStyle: { fontFamily },
        grid: { left: 8, right: 24, top: 14, bottom: 4, containLabel: true },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: kind === 'line' ? 'line' : 'shadow', lineStyle: { color: axis } },
          backgroundColor: surface,
          borderColor: grid,
          textStyle: { color: textPrimary, fontSize: 12, fontFamily },
          formatter: (params: { axisValue: string; seriesName: string; value: number | null; color: string }[]) => {
            const date = params[0]?.axisValue ?? '';
            const rows = params
              .filter((p) => p.value !== null && p.value !== undefined)
              .map(
                (p) =>
                  `<div style="display:flex;gap:12px;justify-content:space-between">` +
                  `<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;` +
                  `background:${p.color};margin-right:6px"></span>${escapeHtml(p.seriesName)}</span>` +
                  `<b>${formatValue(p.value, unit)}</b></div>`,
              );
            const notes = markDates
              .filter((m) => m.axisDate === date)
              .map((m) => `<div style="margin-top:4px;color:${muted}">✎ ${formatShortDate(m.date)}: ${escapeHtml(m.text)}</div>`);
            return `<div style="margin-bottom:4px;color:${muted}">${tooltipDate(date, granularity)}</div>${rows.join('')}${notes.join('')}`;
          },
        },
        xAxis: {
          type: 'category',
          data: dates,
          boundaryGap: kind !== 'line',
          axisLine: { lineStyle: { color: axis } },
          axisTick: { show: false },
          axisLabel: { color: muted, fontSize: 11, formatter: (value: string) => axisDate(value, granularity), hideOverlap: true },
        },
        yAxis: {
          type: 'value',
          inverse,
          // Линии масштабируются по диапазону данных (круглые деления подбирает ECharts),
          // столбцы всегда растут от нуля.
          scale: kind === 'line',
          splitNumber: 4,
          axisLabel: {
            color: muted,
            fontSize: 11,
            formatter: (value: number) => (unit === '%' ? `${value}%` : formatCompact(value)),
          },
          splitLine: { lineStyle: { color: grid } },
        },
        series: visible.map(({ s, index }, position) => {
          const byDate = new Map(s.points);
          const data = dates.map((date) => byDate.get(date) ?? null);
          const color = colors[index];
          const markLine =
            position === 0 && markDates.length
              ? {
                  symbol: 'none',
                  silent: true,
                  label: { show: true, formatter: '✎', color: muted, fontSize: 11 },
                  lineStyle: { color: muted, type: 'solid', width: 1 },
                  data: markDates.map((m) => ({ xAxis: m.axisDate })),
                }
              : undefined;
          if (kind === 'line') {
            return {
              name: s.name,
              type: 'line',
              data,
              connectNulls: true,
              showSymbol: dates.length <= 35,
              symbol: 'circle',
              symbolSize: 6,
              lineStyle: { width: 2, color },
              itemStyle: { color, borderColor: surface, borderWidth: 1 },
              // Заливка — только для одиночной серии на обычной (не перевёрнутой) оси.
              areaStyle: visible.length === 1 && !inverse ? { color, opacity: 0.1 } : undefined,
              emphasis: { focus: 'none', itemStyle: { borderWidth: 2 } },
              markLine,
            };
          }
          const isTop = !stacked || position === visible.length - 1;
          return {
            name: s.name,
            type: 'bar',
            data,
            stack: stacked ? 'total' : undefined,
            barMaxWidth: 24,
            itemStyle: {
              color,
              // Зазор цвета поверхности разделяет соседние и сложенные столбцы.
              borderColor: surface,
              borderWidth: barGap ? 1 : 0,
              borderRadius: isTop && barGap ? [4, 4, 0, 0] : 0,
            },
            markLine,
          };
        }),
      },
      true,
    );
  }, [series, dates, colors, kind, unit, inverse, marks, theme, activeSolo, granularity]);

  return (
    <>
      {series.length > 1 && (
        <div className="legend">
          {series.map((s, index) => (
            <button
              key={s.name}
              type="button"
              className={`legend-item${activeSolo === s.name ? ' solo' : activeSolo !== null ? ' off' : ''}`}
              onClick={() => setSolo(activeSolo === s.name ? null : s.name)}
              title={activeSolo === s.name ? 'Показать все' : 'Оставить на графике только это'}
              aria-pressed={activeSolo === s.name}
            >
              <span className={`legend-swatch${kind === 'line' ? '' : ' box'}`} style={{ background: colors[index] }} />
              {s.name}
            </button>
          ))}
        </div>
      )}
      <div ref={ref} className="chart" style={{ height }} role="img" aria-label={series.map((s) => s.name).join(', ')} />
    </>
  );
}

/** Ступени одного оттенка для упорядоченных групп (распределение по топам). */
export function ordinalRamp(theme: 'light' | 'dark'): string[] {
  return theme === 'dark'
    ? ['#9ec5f4', '#6da7ec', '#2a78d6', '#184f95', '#4b4c53']
    : ['#104281', '#256abf', '#5598e7', '#86b6ef', '#c3c2b7'];
}
