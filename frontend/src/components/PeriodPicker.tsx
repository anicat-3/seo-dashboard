import { formatRange } from '../lib/format';
import { COMPARE_LABELS, PRESETS, compareRange, previousRange, type PeriodState } from '../lib/period';
import type { CompareMode } from '../api/types';
import { DateRangePicker, type CalendarMarks } from './DateRangePicker';

/**
 * Выбор периода и базы сравнения: готовые варианты,
 * календарь произвольного периода и режим сравнения, включая свой период.
 *
 * При смене периода группировка графиков сбрасывается на автоматическую,
 * чтобы не остаться, например, на «по дням» для квартала.
 */
export function PeriodPicker({
  period,
  onChange,
  marks,
  compact = false,
}: {
  period: PeriodState;
  onChange: (next: Partial<PeriodState>) => void;
  /** Отметки календаря: дни съёма позиций и дни с ошибками. */
  marks?: CalendarMarks;
  /** Компактный вид для закреплённой шапки: без кнопок готовых периодов. */
  compact?: boolean;
}) {
  const activePreset = PRESETS.find((preset) => {
    const range = preset.range();
    return range.from === period.from && range.to === period.to;
  });

  function changeCompare(mode: CompareMode) {
    if (mode === 'custom') {
      // Начальное значение своего сравнения — предыдущий период той же длины.
      const base = period.compareFrom && period.compareTo ? { from: period.compareFrom, to: period.compareTo } : previousRange(period.from, period.to);
      onChange({ compare: 'custom', compareFrom: base.from, compareTo: base.to });
    } else {
      onChange({ compare: mode, compareFrom: null, compareTo: null });
    }
  }

  return (
    <div className="row period-picker">
      {!compact && (
        <div className="segmented" role="group" aria-label="Период">
          {PRESETS.map((preset) => (
            <button
              key={preset.key}
              className={activePreset?.key === preset.key ? 'active' : ''}
              onClick={() => onChange({ ...preset.range(), granularity: null })}
            >
              {preset.label}
            </button>
          ))}
        </div>
      )}
      <DateRangePicker from={period.from} to={period.to} marks={marks} onApply={(range) => onChange({ ...range, granularity: null })} />
      <select aria-label="База сравнения" value={period.compare} onChange={(e) => changeCompare(e.target.value as CompareMode)}>
        {(Object.entries(COMPARE_LABELS) as [CompareMode, string][]).map(([mode, label]) => {
          // Даты базы сравнения видны прямо в списке — отдельная строка в шапке не нужна.
          const range = compareRange(period.from, period.to, mode);
          return (
            <option key={mode} value={mode}>
              Сравнить: {label.toLowerCase()}
              {range ? ` · ${formatRange(range.from, range.to)}` : ''}
            </option>
          );
        })}
      </select>
      {period.compare === 'custom' && period.compareFrom && period.compareTo && (
        <span className="row" style={{ gap: 6 }}>
          <span className="small muted">с</span>
          <DateRangePicker
            from={period.compareFrom}
            to={period.compareTo}
            marks={marks}
            onApply={(range) => onChange({ compareFrom: range.from, compareTo: range.to })}
          />
        </span>
      )}
    </div>
  );
}
