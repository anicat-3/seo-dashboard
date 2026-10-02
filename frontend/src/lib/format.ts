/** Форматирование чисел, дат и изменений для интерфейса (локаль ru-RU). */

const numberFmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
const decimalFmt = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 2 });
const axisDecimalFmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
const compactFmt =new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 });
const dateFmt = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' });
const monthYearFmt = new Intl.DateTimeFormat('ru-RU', { month: 'short', year: 'numeric' });
const shortDateFmt = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' });
const dateTimeFmt = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
});

export const DASH = '—';

/** Длительность в секундах → «м:сс». */
export function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

/** Значение метрики с учётом единицы измерения (`%`, `s` или без единицы). */
export function formatValue(value: number | null | undefined, unit = ''): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  if (unit === 's') return formatDuration(value);
  if (unit === '%') return `${decimalFmt.format(value)}%`;
  return Number.isInteger(value) ? numberFmt.format(value) : decimalFmt.format(value);
}

/** Компактная запись для подписей осей: 12,9 тыс. */
export function formatCompact(value: number): string {
  if (Math.abs(value) >= 10000) return compactFmt.format(value);
  // Дробные деления (позиции, CLS) не округляются до целых, иначе подписи дублируются.
  return Number.isInteger(value) ? numberFmt.format(value) : axisDecimalFmt.format(value);
}

/** Изменение в процентах со знаком. */
export function formatChange(changePct: number | null | undefined): string {
  if (changePct === null || changePct === undefined) return DASH;
  const sign = changePct > 0 ? '+' : changePct < 0 ? '−' : '';
  return `${sign}${Math.abs(changePct).toFixed(1).replace('.', ',')}%`;
}

/** Класс окраски изменения: рост — хорошо или плохо в зависимости от метрики. */
export function changeTone(changePct: number | null | undefined, higherIsBetter: boolean): 'good' | 'bad' | 'flat' {
  if (changePct === null || changePct === undefined || Math.abs(changePct) < 0.05) return 'flat';
  return changePct > 0 === higherIsBetter ? 'good' : 'bad';
}

function parse(value: string): Date {
  // Дата без времени трактуется как локальная, чтобы не сдвигаться из-за UTC.
  return value.length === 10 ? new Date(`${value}T00:00:00`) : new Date(value);
}

export function formatDate(value: string | null | undefined): string {
  return value ? dateFmt.format(parse(value)) : DASH;
}

export function formatShortDate(value: string): string {
  return shortDateFmt.format(parse(value));
}

/** Месяц и год: «сент. 2026 г.» — для графиков по месяцам. */
export function formatMonth(value: string): string {
  return monthYearFmt.format(parse(value)).replace(' г.', '');
}

export function formatDateTime(value: string | null | undefined): string {
  return value ? dateTimeFmt.format(parse(value)) : DASH;
}

export function formatRange(from: string, to: string): string {
  return `${formatShortDate(from)} – ${formatDate(to)}`;
}

/** Метрика позиции в выдаче: меньше — лучше, рост числа означает падение позиций. */
export function isPositionMetric(metricCode: string | null | undefined): boolean {
  return !!metricCode && metricCode.endsWith('position');
}
