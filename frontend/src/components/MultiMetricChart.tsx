/**
 * Сводный график поисковой консоли: клики, показы, CTR и средняя позиция на одном графике.
 *
 * Как в Google Search Console: у каждой метрики своя шкала (оси скрыты, точные
 * значения — во всплывающей подсказке), метрики включаются переключателями.
 * По умолчанию показаны клики и показы. Шкала позиции перевёрнута: выше — лучше.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { LineChart } from 'echarts/charts';
import { GridComponent, MarkLineComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';

import type { Granularity, Series } from '../api/types';
import { formatMonth, formatShortDate, formatValue } from '../lib/format';
import { cssVar, useTheme } from '../lib/theme';
import type { ChartMark } from './Chart';

echarts.use([LineChart, GridComponent, TooltipComponent, MarkLineComponent, CanvasRenderer]);

const SERIES_SLOTS = 8;

function escapeHtml(text: string): string {
  return text.replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch] ?? ch);
}

export function MultiMetricChart({
  series,
  defaultVisible,
  marks = [],
  granularity = 'day',
  height = 280,
}: {
  series: Series[];
  defaultVisible: string[];
  marks?: ChartMark[];
  granularity?: Granularity;
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [theme] = useTheme();
  const [visible, setVisible] = useState<Set<string>>(
    () => new Set(defaultVisible.length ? defaultVisible : series.slice(0, 2).map((s) => s.metric_code)),
  );

  const dates = useMemo(() => {
    const all = new Set<string>();
    series.forEach((s) => s.points.forEach(([date]) => all.add(date)));
    return [...all].sort();
  }, [series]);

  // Цвет закреплён за метрикой (по порядку в списке) и не меняется при переключениях.
  const colors = useMemo(
    () => series.map((_, i) => cssVar(`--series-${(i % SERIES_SLOTS) + 1}`)),
    // Цвета перечитываются при смене темы.
    [series, theme],
  );

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
    const shown = series.map((s, index) => ({ s, index })).filter(({ s }) => visible.has(s.metric_code));
    const markDates = marks
      .map((m) => ({ ...m, axisDate: [...dates].reverse().find((d) => d <= m.date) }))
      .filter((m): m is ChartMark & { axisDate: string } => m.axisDate !== undefined && m.date <= (dates[dates.length - 1] ?? ''));

    chart.setOption(
      {
        animation: false,
        textStyle: { fontFamily },
        grid: { left: 12, right: 12, top: 16, bottom: 4, containLabel: true },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'line', lineStyle: { color: axis } },
          backgroundColor: surface,
          borderColor: grid,
          textStyle: { color: textPrimary, fontSize: 12, fontFamily },
          formatter: (params: { axisValue: string; seriesIndex: number; value: number | null; color: string }[]) => {
            const date = params[0]?.axisValue ?? '';
            const head =
              granularity === 'month' ? formatMonth(date) : granularity === 'week' ? `Неделя с ${formatShortDate(date)}` : formatShortDate(date);
            const rows = params
              .filter((p) => p.value !== null && p.value !== undefined)
              .map((p) => {
                const item = shown[p.seriesIndex].s;
                return (
                  `<div style="display:flex;gap:12px;justify-content:space-between">` +
                  `<span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;` +
                  `background:${p.color};margin-right:6px"></span>${escapeHtml(item.name)}</span>` +
                  `<b>${formatValue(p.value, item.unit)}</b></div>`
                );
              });
            const notes = markDates
              .filter((m) => m.axisDate === date)
              .map((m) => `<div style="margin-top:4px;color:${muted}">✎ ${formatShortDate(m.date)}: ${escapeHtml(m.text)}</div>`);
            return `<div style="margin-bottom:4px;color:${muted}">${head}</div>${rows.join('')}${notes.join('')}`;
          },
        },
        xAxis: {
          type: 'category',
          data: dates,
          boundaryGap: false,
          axisLine: { lineStyle: { color: axis } },
          axisTick: { show: false },
          axisLabel: {
            color: muted,
            fontSize: 11,
            hideOverlap: true,
            formatter: (value: string) => (granularity === 'month' ? formatMonth(value) : formatShortDate(value)),
          },
        },
        // У каждой метрики своя скрытая шкала: так клики и показы разного масштаба видны вместе.
        yAxis: shown.map(({ s }, position) => ({
          type: 'value',
          show: false,
          scale: true,
          inverse: s.inverse,
          splitLine: { show: position === 0, lineStyle: { color: grid } },
        })),
        series: shown.map(({ s, index }, position) => {
          const byDate = new Map(s.points);
          return {
            name: s.name,
            type: 'line',
            yAxisIndex: position,
            data: dates.map((date) => byDate.get(date) ?? null),
            connectNulls: true,
            showSymbol: dates.length <= 35,
            symbol: 'circle',
            symbolSize: 6,
            lineStyle: { width: 2, color: colors[index] },
            itemStyle: { color: colors[index], borderColor: surface, borderWidth: 1 },
            markLine:
              position === 0 && markDates.length
                ? {
                    symbol: 'none',
                    silent: true,
                    label: { show: true, formatter: '✎', color: muted, fontSize: 11 },
                    lineStyle: { color: muted, type: 'solid', width: 1 },
                    data: markDates.map((m) => ({ xAxis: m.axisDate })),
                  }
                : undefined,
          };
        }),
      },
      true,
    );
  }, [series, dates, colors, visible, marks, theme, granularity]);

  function toggle(metricCode: string) {
    const next = new Set(visible);
    if (next.has(metricCode)) {
      if (next.size === 1) return; // хотя бы одна метрика остаётся на графике
      next.delete(metricCode);
    } else {
      next.add(metricCode);
    }
    setVisible(next);
  }

  return (
    <>
      <div className="metric-toggles" role="group" aria-label="Метрики на графике">
        {series.map((s, index) => {
          const on = visible.has(s.metric_code);
          return (
            <button
              key={s.metric_code}
              type="button"
              className={`metric-toggle${on ? ' on' : ''}`}
              style={on ? { borderColor: colors[index] } : undefined}
              onClick={() => toggle(s.metric_code)}
              aria-pressed={on}
            >
              <span className="metric-check" style={on ? { background: colors[index], borderColor: colors[index] } : undefined}>
                {on ? '✓' : ''}
              </span>
              {s.name}
            </button>
          );
        })}
      </div>
      <div ref={ref} className="chart" style={{ height }} role="img" aria-label={series.map((s) => s.name).join(', ')} />
    </>
  );
}
