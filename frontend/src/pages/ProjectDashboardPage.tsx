import { useEffect, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import { useUser } from '../auth/AuthContext';
import type { Annotation, Block, Dashboard, Granularity } from '../api/types';
import { BlockView } from '../components/BlockView';
import { useConfirm } from '../components/ConfirmDialog';
import type { CalendarMarks } from '../components/DateRangePicker';
import { PeriodPicker } from '../components/PeriodPicker';
import { ErrorNotice, Modal, QueryState } from '../components/ui';
import { ProjectSwitcher } from '../components/ProjectSwitcher';
import { formatDate, formatDateTime, formatRange } from '../lib/format';
import { GRANULARITY_LABELS, periodQuery, usePeriod } from '../lib/period';
import { printReport } from '../lib/print';
import { SignalItem } from './SignalsPage';

const GRANULARITIES: Granularity[] = ['day', 'week', 'month'];

/** Добавление пометки на графики проекта: релиз, апдейт поисковика. */
function AnnotationDialog({ projectRef, defaultDate, onClose }: { projectRef: string; defaultDate: string; onClose: () => void }) {
  const [date, setDate] = useState(defaultDate);
  const [text, setText] = useState('');
  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: () => api.post<Annotation>(`/projects/${projectRef}/annotations`, { date, text }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['dashboard', projectRef] });
      onClose();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <Modal
      title="Пометка на графиках"
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Отмена</button>
          <button className="primary" type="submit" form="annotation-form" disabled={create.isPending}>
            Добавить
          </button>
        </>
      }
    >
      <form id="annotation-form" className="stack" onSubmit={submit}>
        <label className="field">
          Дата
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
        </label>
        <label className="field">
          Что произошло
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            maxLength={1000}
            required
            placeholder="Например: релиз нового каталога, апдейт Google"
            autoFocus
          />
        </label>
        <ErrorNotice error={create.error} />
      </form>
    </Modal>
  );
}

/** Систему подключили к проекту несколько раз (например, два проекта Топвизора). */
function repeatedSystem(blocks: Block[], block: Block): boolean {
  return blocks.filter((b) => b.system_code === block.system_code).length > 1;
}

/** Название ресурса нужно у позиций всегда и у любой системы, подключённой дважды. */
function needsResourceName(blocks: Block[], block: Block): boolean {
  return block.system_code === 'topvisor' || block.system_code === 'seranking' || repeatedSystem(blocks, block);
}

/** Короткое имя ресурса для якоря: без домена в скобках. */
function shortResource(block: Block): string {
  return (block.external_name ?? block.external_id).replace(/\s*\(.*\)\s*$/, '');
}

/**
 * Сжимать закреплённую шапку после прокрутки. Пороги включения и выключения разные,
 * чтобы шапка не «мигала», когда её высота меняется на границе.
 */
function useCompactHeader(): boolean {
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    const onScroll = () => setCompact((current) => (current ? window.scrollY > 40 : window.scrollY > 220));
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  return compact;
}

/** Дашборд проекта за период со сравнением. */
export function ProjectDashboardPage() {
  const projectRef = useParams().projectRef ?? '';
  const [period, setPeriod] = usePeriod();
  const [annotating, setAnnotating] = useState(false);
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const isAdmin = useUser().role === 'admin';

  const query = useQuery({
    queryKey: ['dashboard', projectRef, period],
    queryFn: () =>
      api.get<Dashboard>(`/projects/${projectRef}/dashboard`, { ...periodQuery(period), granularity: period.granularity }),
    // При смене периода прежний отчёт остаётся на экране, пока грузится новый.
    placeholderData: (previous) => (previous?.project.slug === projectRef ? previous : undefined),
  });
  const marks = useQuery({
    queryKey: ['calendar', projectRef],
    queryFn: () => api.get<CalendarMarks>(`/projects/${projectRef}/calendar`),
    staleTime: 10 * 60_000,
  });
  const removeAnnotation = useMutation({
    mutationFn: (id: number) => api.delete(`/annotations/${id}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['dashboard', projectRef] }),
  });

  const data = query.data;
  const granularity = data?.granularity.value ?? 'day';
  const compact = useCompactHeader();

  const granularityControl = (
    <div className="segmented" role="group" aria-label="Группировка графиков">
      {GRANULARITIES.map((value) => {
        const allowed = data?.granularity.allowed.includes(value) ?? false;
        return (
          <button
            key={value}
            className={granularity === value ? 'active' : ''}
            disabled={!allowed}
            title={allowed ? undefined : value === 'day' ? 'Для периодов длиннее 62 дней недоступно' : 'Период слишком короткий'}
            onClick={() => setPeriod({ granularity: value })}
          >
            {GRANULARITY_LABELS[value]}
          </button>
        );
      })}
    </div>
  );

  return (
    <>
      {data && (
        <div className="print-only" style={{ marginBottom: 12 }}>
          <h1>{data.project.name}</h1>
          <div className="secondary">
            {data.project.domain} · {formatRange(data.period.date_from, data.period.date_to)} · сравнение с{' '}
            {formatRange(data.compare.date_from, data.compare.date_to)} · графики: {GRANULARITY_LABELS[granularity].toLowerCase()} ·
            сформирован {formatDateTime(new Date().toISOString())}
          </div>
        </div>
      )}

      {/*
        Закреплённая шапка: переключатель проектов, период, группировка и якоря доступны
        из любого места страницы. После прокрутки шапка сжимается до одной строки.
      */}
      <div className={`sticky-bar no-print${compact ? ' compact' : ''}`}>
        <div className="bar-row">
          <ProjectSwitcher currentSlug={projectRef} currentName={data?.project.name} currentDomain={data?.project.domain} />
          {compact ? (
            <>
              <PeriodPicker period={period} onChange={setPeriod} marks={marks.data} compact />
              {granularityControl}
            </>
          ) : (
            <>
              <span className="spacer" />
              <span className="row bar-actions">
                <button onClick={() => setAnnotating(true)}>✎ Пометка</button>
                <button
                  disabled={!data}
                  onClick={() =>
                    data && void printReport(`SEO-отчёт ${data.project.domain} ${data.period.date_from} — ${data.period.date_to}`)
                  }
                  title="Откроется диалог печати: выберите «Сохранить как PDF»"
                >
                  ⤓ Скачать PDF
                </button>
                <Link to={`/projects/${projectRef}/settings`}>
                  <button>Настройки проекта</button>
                </Link>
              </span>
            </>
          )}
          {query.isFetching && data && <span className="small muted">Обновление…</span>}
        </div>
        {!compact && (
          <div className="bar-row">
            <PeriodPicker period={period} onChange={setPeriod} marks={marks.data} />
            {granularityControl}
          </div>
        )}
        {data && data.blocks.length > 0 && (
          <nav className="jump-nav" aria-label="Блоки дашборда">
            {data.blocks.map((block) => (
              <button
                key={block.integration_id}
                className="small"
                onClick={() => document.getElementById(`block-${block.integration_id}`)?.scrollIntoView()}
              >
                {block.system_name}
                {repeatedSystem(data.blocks, block) && ` · ${shortResource(block)}`}
              </button>
            ))}
          </nav>
        )}
      </div>

      <QueryState query={query}>
        {(dashboard) => (
          <div className="stack">
            {dashboard.signals.length > 0 && (
              <div className="panel">
                <div className="panel-header">
                  <h2>Сигналы: {dashboard.signals.length}</h2>
                  <Link className="small no-print" to={`/signals?project=${dashboard.project.id}`}>
                    Все сигналы проекта →
                  </Link>
                </div>
                <div className="signal-list">
                  {dashboard.signals.map((signal) => {
                    const block = dashboard.blocks.find((b) => b.integration_id === signal.integration_id);
                    return <SignalItem key={signal.id} signal={{ ...signal, system_code: block?.system_code }} />;
                  })}
                </div>
              </div>
            )}

            {dashboard.blocks.length === 0 ? (
              <div className="panel empty">
                К проекту не подключено ни одной системы. <Link to={`/projects/${projectRef}/settings`}>Подключить систему</Link>
              </div>
            ) : (
              dashboard.blocks.map((block) => (
                <BlockView
                  key={block.integration_id}
                  block={block}
                  projectRef={projectRef}
                  period={period}
                  granularity={dashboard.granularity.value}
                  annotations={dashboard.annotations}
                  isAdmin={isAdmin}
                  showResource={needsResourceName(dashboard.blocks, block)}
                />
              ))
            )}

            {dashboard.annotations.length > 0 && (
              <div className="panel">
                <div className="panel-header">
                  <h2>Пометки за период</h2>
                </div>
                <div className="table-wrap">
                  <table>
                    <tbody>
                      {dashboard.annotations.map((annotation) => (
                        <tr key={annotation.id}>
                          <td className="nowrap">{formatDate(annotation.date)}</td>
                          <td style={{ width: '100%' }}>{annotation.text}</td>
                          <td className="nowrap muted">{annotation.author_name}</td>
                          <td className="no-print">
                            <button
                              className="small danger"
                              onClick={async () => {
                                const ok = await confirm({
                                  title: 'Удалить пометку?',
                                  message: `«${annotation.text}» от ${formatDate(annotation.date)} исчезнет со всех графиков проекта.`,
                                  confirmLabel: 'Удалить',
                                  danger: true,
                                });
                                if (ok) removeAnnotation.mutate(annotation.id);
                              }}
                            >
                              Удалить
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}
      </QueryState>
      {annotating && <AnnotationDialog projectRef={projectRef} defaultDate={period.to} onClose={() => setAnnotating(false)} />}
    </>
  );
}
