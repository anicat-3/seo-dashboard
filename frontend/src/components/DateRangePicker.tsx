/**
 * Календарь выбора периода.
 *
 * - Отчёт не перестраивается, пока пользователь листает месяцы и выбирает даты:
 *   период применяется только кнопкой «Применить».
 * - Под числом показываются отметки: синяя точка — день съёма позиций, красная —
 *   день, когда обнаружены ошибки или резкие изменения.
 * - Выбрать можно только даты до вчерашнего дня включительно (данные собираются
 *   с задержкой), листать дальше текущего месяца нельзя.
 */
import { useEffect, useMemo, useRef, useState } from 'react';

import { formatDate, formatRange } from '../lib/format';
import { isoDate, yesterdayIso } from '../lib/period';

export interface CalendarMarks {
  checks: string[];
  alerts: string[];
  history_from: string | null;
}

interface Props {
  from: string;
  to: string;
  marks?: CalendarMarks;
  onApply: (range: { from: string; to: string }) => void;
}

/** Примерная ширина окна с двумя месяцами — для выбора стороны выравнивания. */
const POPOVER_WIDTH = 580;
const DOW = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const monthFmt = new Intl.DateTimeFormat('ru-RU', { month: 'long', year: 'numeric' });

/** Первый день месяца, в котором находится дата `value` (YYYY-MM-DD). */
function monthOf(value: string): Date {
  const [year, month] = value.split('-').map(Number);
  return new Date(year, month - 1, 1);
}

function addMonths(date: Date, count: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + count, 1);
}

function Month({
  month,
  start,
  end,
  maxDate,
  checks,
  alerts,
  onPick,
}: {
  month: Date;
  start: string;
  end: string | null;
  maxDate: string;
  checks: Set<string>;
  alerts: Set<string>;
  onPick: (day: string) => void;
}) {
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  // Неделя начинается с понедельника.
  const offset = (month.getDay() + 6) % 7;
  const cells: (string | null)[] = [
    ...Array<null>(offset).fill(null),
    ...Array.from({ length: days }, (_, i) => isoDate(new Date(month.getFullYear(), month.getMonth(), i + 1))),
  ];
  const last = end ?? start;

  return (
    <div>
      <div className="cal-head">
        <span className="cal-month-name">{monthFmt.format(month)}</span>
      </div>
      <div className="cal-grid">
        {DOW.map((name) => (
          <div key={name} className="cal-dow">
            {name}
          </div>
        ))}
        {cells.map((day, index) =>
          day === null ? (
            <div key={`empty-${index}`} />
          ) : (
            <button
              key={day}
              type="button"
              className={`cal-day${day === start || day === last ? ' edge' : day > start && day < last ? ' in-range' : ''}`}
              disabled={day > maxDate}
              onClick={() => onPick(day)}
              title={[checks.has(day) && 'съём позиций', alerts.has(day) && 'обнаружены ошибки или резкие изменения']
                .filter(Boolean)
                .join(', ')}
            >
              {Number(day.slice(8))}
              <span className="cal-dots">
                {checks.has(day) && <span className="cal-dot check" />}
                {alerts.has(day) && <span className="cal-dot alert" />}
              </span>
            </button>
          ),
        )}
      </div>
    </div>
  );
}

export function DateRangePicker({ from, to, marks, onApply }: Props) {
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState(from);
  const [end, setEnd] = useState<string | null>(to);
  // Правый из двух показанных месяцев.
  const [viewMonth, setViewMonth] = useState(() => monthOf(to));
  const rootRef = useRef<HTMLDivElement>(null);
  // Окно прижимается к правому краю кнопки, если слева от края экрана ему не хватает места.
  const [alignRight, setAlignRight] = useState(false);
  const maxDate = yesterdayIso();
  const lastMonth = monthOf(isoDate(new Date()));

  const checks = useMemo(() => new Set(marks?.checks), [marks]);
  const alerts = useMemo(() => new Set(marks?.alerts), [marks]);

  // При открытии черновик сбрасывается к применённому периоду.
  useEffect(() => {
    if (open) {
      setStart(from);
      setEnd(to);
      setViewMonth(monthOf(to));
      const left = rootRef.current?.getBoundingClientRect().left ?? 0;
      setAlignRight(left + POPOVER_WIDTH > window.innerWidth);
    }
  }, [open, from, to]);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  /** Первый клик задаёт начало, второй — конец (порядок дат не важен). */
  function pick(day: string) {
    if (end !== null) {
      setStart(day);
      setEnd(null);
    } else if (day < start) {
      setEnd(start);
      setStart(day);
    } else {
      setEnd(day);
    }
  }

  const canGoForward = viewMonth < lastMonth;
  const hasMarks = checks.size > 0 || alerts.size > 0;

  return (
    <div className="range-picker" ref={rootRef}>
      <button type="button" className="range-trigger" onClick={() => setOpen(!open)} aria-haspopup="dialog" aria-expanded={open}>
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="1.5" y="3" width="13" height="11.5" rx="2" />
          <path d="M1.5 6.5h13M5 1.5v3M11 1.5v3" />
        </svg>
        {formatRange(from, to)}
      </button>
      {open && (
        <div className={`range-popover${alignRight ? ' align-right' : ''}`} role="dialog" aria-label="Выбор периода">
          <div className="cal-head">
            <button type="button" className="small" onClick={() => setViewMonth(addMonths(viewMonth, -1))} aria-label="Предыдущий месяц">
              ←
            </button>
            <span className="small muted">{end === null ? 'Выберите дату окончания' : 'Выберите дату начала'}</span>
            <button
              type="button"
              className="small"
              onClick={() => setViewMonth(addMonths(viewMonth, 1))}
              disabled={!canGoForward}
              aria-label="Следующий месяц"
            >
              →
            </button>
          </div>
          <div className="range-months">
            {[addMonths(viewMonth, -1), viewMonth].map((month) => (
              <Month
                key={month.toISOString()}
                month={month}
                start={start}
                end={end}
                maxDate={maxDate}
                checks={checks}
                alerts={alerts}
                onPick={pick}
              />
            ))}
          </div>
          <div className="range-footer">
            <div className="cal-legend">
              {hasMarks && (
                <>
                  <span>
                    <span className="cal-dot check" /> съём позиций
                  </span>
                  <span>
                    <span className="cal-dot alert" /> ошибки и резкие изменения
                  </span>
                </>
              )}
              {marks?.history_from && <span>история с {formatDate(marks.history_from)}</span>}
            </div>
            <div className="row">
              <span className="small secondary">{formatRange(start, end ?? start)}</span>
              <span className="spacer" />
              <button type="button" onClick={() => setOpen(false)}>
                Отмена
              </button>
              <button
                type="button"
                className="primary"
                onClick={() => {
                  onApply({ from: start, to: end ?? start });
                  setOpen(false);
                }}
              >
                Применить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
