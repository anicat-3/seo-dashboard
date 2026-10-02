/** Небольшие переиспользуемые элементы интерфейса. */
import { useEffect, useState, type ReactNode } from 'react';
import type { UseQueryResult } from '@tanstack/react-query';

import loadingCat from '../assets/loading-cat.gif';
import { changeTone, formatChange } from '../lib/format';
import { smoothScrollTo } from '../lib/scroll';

const STATUS_LABELS: Record<string, string> = {
  ok: 'Работает',
  error: 'Ошибка',
  pending: 'Ожидает сбора',
  unchecked: 'Не проверен',
  running: 'Выполняется',
  success: 'Успешно',
  partial: 'Частично',
  warning: 'Предупреждение',
  paused: 'Приостановлено',
  disabled: 'Отключено',
  open: 'Открыта',
  resolved: 'Исправлена',
};

const STATUS_TONE: Record<string, string> = {
  ok: 'ok',
  success: 'ok',
  resolved: 'ok',
  error: 'error',
  open: 'error',
  partial: 'warn',
  warning: 'warn',
  paused: 'warn',
  running: 'pending',
  pending: 'pending',
  unchecked: 'pending',
  disabled: 'pending',
};

/** Статус с цветной точкой и подписью (цвет никогда не единственный носитель смысла). */
export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return (
    <span className={`badge ${STATUS_TONE[status] ?? 'pending'}`}>
      <span className="dot" />
      {label ?? STATUS_LABELS[status] ?? status}
    </span>
  );
}

/**
 * Изменение к базе сравнения: стрелка + процент, окраска по направлению «лучше».
 *
 * Для позиций (`position`) знак и стрелка показывают движение в выдаче, а не
 * изменение числа: позиция 10 → 12 — это падение, «▼ −20%».
 */
export function Delta({
  changePct,
  higherIsBetter,
  position = false,
}: {
  changePct: number | null;
  higherIsBetter: boolean;
  position?: boolean;
}) {
  const tone = changeTone(changePct, higherIsBetter);
  const shown = position && changePct !== null ? -changePct : changePct;
  const arrow = shown === null || tone === 'flat' ? '' : shown > 0 ? '▲ ' : '▼ ';
  return (
    <span className={`delta ${tone}`}>
      {arrow}
      {formatChange(shown)}
    </span>
  );
}

/** Значок «?» с пояснением: открывается при наведении, фокусе или нажатии. */
export function Hint({ children, label = 'Пояснение' }: { children: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="hint" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className="help"
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        ?
      </button>
      {open && (
        <span className="hint-popover" role="tooltip">
          {children}
        </span>
      )}
    </span>
  );
}

/** Экран загрузки: пиксельный котик и подпись. */
export function LoadingCat({ label = 'Загрузка…' }: { label?: string }) {
  return (
    <div className="loading-cat" role="status" aria-live="polite">
      <img src={loadingCat} alt="" width={146} height={274} />
      <span>{label}</span>
    </div>
  );
}

/** Единая обработка состояний запроса: загрузка, ошибка, данные. */
export function QueryState<T>({
  query,
  children,
}: {
  query: UseQueryResult<T>;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <LoadingCat />;
  if (query.isError) {
    return (
      <div className="notice error">
        Не удалось загрузить данные: {query.error.message}
        <button className="small" onClick={() => void query.refetch()}>
          Повторить
        </button>
      </div>
    );
  }
  return <>{children(query.data)}</>;
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="notice error">{error instanceof Error ? error.message : String(error)}</div>;
}

export function Modal({
  title,
  onClose,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-header">
          <h2>{title}</h2>
          <button className="ghost" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}

export function PageHeader({ title, subtitle, children }: { title: ReactNode; subtitle?: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <div className="subtitle">{subtitle}</div>}
      </div>
      {children && <div className="toolbar">{children}</div>}
    </div>
  );
}

const SYSTEM_SHORT: Record<string, string> = {
  ga4: 'GA4',
  metrika: 'Метрика',
  gsc: 'GSC',
  crux: 'CrUX',
  ywm: 'Вебмастер',
  topvisor: 'Topvisor',
  seranking: 'SE Ranking',
  bing: 'Bing',
  psi: 'PSI',
};

export function systemShort(code: string): string {
  return SYSTEM_SHORT[code] ?? code;
}

export function SystemChips({ systems }: { systems: string[] }) {
  return (
    <span className="row" style={{ gap: 4 }}>
      {systems.map((code) => (
        <span key={code} className="sys-chip">
          {systemShort(code)}
        </span>
      ))}
    </span>
  );
}

/** Кнопка возврата к началу страницы; появляется после прокрутки вниз. */
export function BackToTop() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const onScroll = () => setVisible(window.scrollY > 600);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  if (!visible) return null;
  return (
    <button
      className="to-top primary no-print"
      onClick={() => smoothScrollTo(0)}
      title="К началу страницы"
      aria-label="К началу страницы"
    >
      ↑
    </button>
  );
}
