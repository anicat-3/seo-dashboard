/**
 * Выпадающий список с поиском — для длинных списков (сотни сайтов и счётчиков
 * в аккаунте). Ищет по названию и идентификатору, управляется с клавиатуры.
 */
import { useEffect, useMemo, useRef, useState } from 'react';

export interface SearchOption {
  value: string;
  label: string;
  /** Вторая строка: идентификатор ресурса, домен. */
  hint?: string;
  disabled?: boolean;
}

/** Сколько вариантов рисовать за раз: остальные находятся поиском. */
const RENDER_LIMIT = 200;

export function SearchSelect({
  options,
  value,
  onChange,
  placeholder = '— выберите —',
  disabled = false,
  ariaLabel,
}: {
  options: SearchOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const selected = options.find((o) => o.value === value);

  const matches = useMemo(() => {
    const words = search.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return options.filter((o) => {
      const text = `${o.label} ${o.hint ?? ''} ${o.value}`.toLowerCase();
      return words.every((w) => text.includes(w));
    });
  }, [options, search]);

  useEffect(() => {
    if (!open) return;
    setSearch('');
    setActive(0);
    const onDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  function choose(option: SearchOption | undefined) {
    if (!option || option.disabled) return;
    onChange(option.value);
    setOpen(false);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'Escape') setOpen(false);
    else if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive(Math.min(active + 1, Math.min(matches.length, RENDER_LIMIT) - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive(Math.max(active - 1, 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      choose(matches[active]);
    }
  }

  return (
    <div className="search-select" ref={rootRef}>
      <button
        type="button"
        className="search-select-trigger"
        onClick={() => setOpen(!open)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
      >
        <span className={selected ? '' : 'muted'}>{selected?.label ?? placeholder}</span>
        <span className="switcher-caret" aria-hidden="true">
          ▾
        </span>
      </button>
      {open && (
        <div className="switcher-popover search-select-popover" onKeyDown={onKeyDown}>
          <input
            className="switcher-search"
            placeholder={`Поиск среди ${options.length}`}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setActive(0);
            }}
            autoFocus
            aria-label="Поиск"
          />
          <div className="switcher-list" role="listbox">
            {matches.slice(0, RENDER_LIMIT).map((option, index) => (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
                disabled={option.disabled}
                className={`switcher-item${option.value === value ? ' current' : ''}${index === active ? ' active' : ''}`}
                onMouseEnter={() => setActive(index)}
                onClick={() => choose(option)}
              >
                <span className="switcher-name">{option.label}</span>
                {option.hint && <span className="small muted">{option.hint}</span>}
              </button>
            ))}
            {matches.length > RENDER_LIMIT && (
              <div className="empty small">Показаны первые {RENDER_LIMIT} из {matches.length} — уточните поиск</div>
            )}
            {matches.length === 0 && <div className="empty small">Ничего не найдено</div>}
          </div>
        </div>
      )}
    </div>
  );
}
