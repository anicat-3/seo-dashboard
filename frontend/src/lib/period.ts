/**
 * Период дашборда и база сравнения.
 *
 * Состояние хранится в адресной строке (`?from=…&to=…&compare=…`), поэтому ссылкой
 * на дашборд за конкретный период можно поделиться.
 */
import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';

import type { CompareMode, Granularity } from '../api/types';

export interface PeriodState {
  from: string;
  to: string;
  compare: CompareMode;
  /** Свой период сравнения (при `compare = 'custom'`). */
  compareFrom: string | null;
  compareTo: string | null;
  /** Группировка графиков; `null` — подобрать автоматически по длине периода. */
  granularity: Granularity | null;
}

export const GRANULARITY_LABELS: Record<Granularity, string> = {
  day: 'По дням',
  week: 'По неделям',
  month: 'По месяцам',
};

export const COMPARE_LABELS: Record<CompareMode, string> = {
  previous: 'Предыдущий период',
  previous_month: 'Предыдущий месяц',
  year_ago: 'Год назад',
  custom: 'Свой период',
};

export function isoDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

function addDays(date: Date, days: number): Date {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
}

/** Вчера — последний полный день данных. */
function yesterday(): Date {
  return addDays(new Date(), -1);
}

export function yesterdayIso(): string {
  return isoDate(yesterday());
}

export interface Preset {
  key: string;
  label: string;
  range: () => { from: string; to: string };
}

export const PRESETS: Preset[] = [
  {
    key: '7d',
    label: '7 дней',
    range: () => ({ from: isoDate(addDays(yesterday(), -6)), to: isoDate(yesterday()) }),
  },
  {
    key: '30d',
    label: '30 дней',
    range: () => ({ from: isoDate(addDays(yesterday(), -29)), to: isoDate(yesterday()) }),
  },
  {
    key: 'week',
    label: 'Прошлая неделя',
    range: () => {
      const y = yesterday();
      // Последнее завершённое воскресенье (getDay: вс = 0).
      const end = addDays(y, -(y.getDay() % 7));
      return { from: isoDate(addDays(end, -6)), to: isoDate(end) };
    },
  },
  {
    key: 'month',
    label: 'Прошлый месяц',
    range: () => {
      const now = new Date();
      const first = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      const last = new Date(now.getFullYear(), now.getMonth(), 0);
      return { from: isoDate(first), to: isoDate(last) };
    },
  },
  {
    key: '90d',
    label: 'Квартал',
    range: () => ({ from: isoDate(addDays(yesterday(), -89)), to: isoDate(yesterday()) }),
  },
];

const COMPARE_MODES: CompareMode[] = ['previous', 'previous_month', 'year_ago', 'custom'];
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const GRANULARITIES: Granularity[] = ['day', 'week', 'month'];

/** Прочитать и изменить период в адресной строке. */
export function usePeriod(): [PeriodState, (next: Partial<PeriodState>) => void] {
  const [params, setParams] = useSearchParams();
  const from = params.get('from');
  const to = params.get('to');
  const compareParam = params.get('compare') as CompareMode | null;
  const groupParam = params.get('group') as Granularity | null;
  const cfrom = params.get('cfrom');
  const cto = params.get('cto');

  const state = useMemo<PeriodState>(() => {
    const fallback = PRESETS[0].range();
    const valid = !!from && !!to && ISO_DATE.test(from) && ISO_DATE.test(to) && from <= to;
    const customValid = !!cfrom && !!cto && ISO_DATE.test(cfrom) && ISO_DATE.test(cto) && cfrom <= cto;
    let compare: CompareMode = compareParam && COMPARE_MODES.includes(compareParam) ? compareParam : 'previous';
    // Свой период без дат не имеет смысла — возвращаемся к сравнению с предыдущим.
    if (compare === 'custom' && !customValid) compare = 'previous';
    return {
      from: valid ? from : fallback.from,
      to: valid ? to : fallback.to,
      compare,
      compareFrom: compare === 'custom' ? cfrom : null,
      compareTo: compare === 'custom' ? cto : null,
      granularity: groupParam && GRANULARITIES.includes(groupParam) ? groupParam : null,
    };
  }, [from, to, compareParam, groupParam, cfrom, cto]);

  const update = useCallback(
    (next: Partial<PeriodState>) => {
      const merged = { ...state, ...next };
      const copy = new URLSearchParams(params);
      copy.set('from', merged.from);
      copy.set('to', merged.to);
      copy.set('compare', merged.compare);
      if (merged.compare === 'custom' && merged.compareFrom && merged.compareTo) {
        copy.set('cfrom', merged.compareFrom);
        copy.set('cto', merged.compareTo);
      } else {
        copy.delete('cfrom');
        copy.delete('cto');
      }
      if (merged.granularity) copy.set('group', merged.granularity);
      else copy.delete('group');
      setParams(copy, { replace: true });
    },
    [params, setParams, state],
  );

  return [state, update];
}

/** Параметры запроса API для периода и базы сравнения. */
export function periodQuery(period: PeriodState): Record<string, string> {
  const query: Record<string, string> = { date_from: period.from, date_to: period.to, compare: period.compare };
  if (period.compare === 'custom' && period.compareFrom && period.compareTo) {
    query.compare_from = period.compareFrom;
    query.compare_to = period.compareTo;
  }
  return query;
}

/** Строка запроса для ссылок между страницами с сохранением периода. */
export function periodSearch(period: PeriodState): string {
  const custom =
    period.compare === 'custom' && period.compareFrom ? `&cfrom=${period.compareFrom}&cto=${period.compareTo}` : '';
  return `?from=${period.from}&to=${period.to}&compare=${period.compare}${custom}`;
}

/** Предыдущий период той же длины, что и `from`–`to` (как сравнение «предыдущий период»). */
export function previousRange(from: string, to: string): { from: string; to: string } {
  const start = new Date(`${from}T00:00:00`);
  const end = new Date(`${to}T00:00:00`);
  const days = Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1;
  const prevEnd = addDays(start, -1);
  return { from: isoDate(addDays(prevEnd, -(days - 1))), to: isoDate(prevEnd) };
}

/**
 * База сравнения для режима `mode` — те же правила, что на сервере
 * (`app/services/periods.py::compare_period`). Нужна, чтобы показать даты
 * прямо в списке «Сравнить», не дожидаясь ответа сервера.
 */
export function compareRange(from: string, to: string, mode: CompareMode): { from: string; to: string } | null {
  if (mode === 'previous') return previousRange(from, to);
  if (mode === 'previous_month') {
    const start = new Date(`${from}T00:00:00`);
    return {
      from: isoDate(new Date(start.getFullYear(), start.getMonth() - 1, 1)),
      to: isoDate(new Date(start.getFullYear(), start.getMonth(), 0)),
    };
  }
  if (mode === 'year_ago') {
    const shift = (value: string) => {
      const [year, month, day] = value.split('-').map(Number);
      // 29 февраля превращается в 28-е, как на сервере.
      const lastDay = new Date(year - 1, month, 0).getDate();
      return isoDate(new Date(year - 1, month - 1, Math.min(day, lastDay)));
    };
    return { from: shift(from), to: shift(to) };
  }
  return null;
}
