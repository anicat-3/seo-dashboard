import { useQuery } from '@tanstack/react-query';

import { api } from '../api/client';
import type { AuditEntry, MetricInfo } from '../api/types';
import { PageHeader, QueryState, systemShort } from '../components/ui';
import { formatDate, formatDateTime } from '../lib/format';

const ACTIONS: Record<string, string> = {
  create: 'Создание',
  update: 'Изменение',
  delete: 'Удаление',
  pause: 'Приостановка сбора',
  disable: 'Отключение',
  archive: 'Отправка в архив',
  restore: 'Возврат / включение',
  manual_sync: 'Ручной перезапуск сбора',
  sync_all: 'Запуск сбора по всем подключениям',
  change_password: 'Смена пароля',
};

const ENTITIES: Record<string, string> = {
  project: 'проекта',
  integration: 'подключения',
  credential: 'доступа',
  monitored_url: 'URL для PSI',
  signal_rule: 'правила подсветки',
  annotation: 'пометки',
  account: 'учётной записи',
  team_member: 'сотрудника',
  system: '',
};

/** Подписи полей в подробностях записи. */
const FIELDS: Record<string, string> = {
  old_name: 'Было',
  full_name: 'Сотрудник',
  name: 'Название',
  domain: 'Домен',
  system_code: 'Система',
  external_id: 'Ресурс',
  label: 'Название доступа',
  account_login: 'Логин аккаунта',
  auth_type: 'Способ подключения',
  secret: 'Ключ',
  url: 'URL',
  template_name: 'Шаблон страницы',
  is_active: 'Состояние',
  date: 'Дата',
  text: 'Текст',
  date_from: 'Период с',
  date_to: 'по',
  metric_code: 'Метрика',
  segment: 'Сегмент',
  comparison: 'База сравнения',
  threshold_pct: 'Порог',
  project_id: 'Область действия',
  login: 'Учётная запись',
  credential_id: 'Доступ №',
  timezone: 'Часовой пояс',
  goals: 'Избранные цели',
  settings: 'Настройки',
  integrations: 'Удалено подключений',
  daily_metrics: 'Удалено дневных значений',
  keywords: 'Удалено запросов',
  sync_runs: 'Удалено запусков сбора',
};

const FIELD_KEYS = Object.keys(FIELDS);

function fieldOrder(key: string): number {
  const index = FIELD_KEYS.indexOf(key);
  return index === -1 ? FIELD_KEYS.length : index;
}

const VALUES: Record<string, Record<string, string>> = {
  auth_type: { api_key: 'API-ключ', oauth: 'OAuth' },
  comparison: { wow: 'неделя к неделе', mom: '30 дней к 30 дням' },
  segment: { all: 'все', organic: 'органика', '*': 'каждый сегмент', mobile: 'мобильные', desktop: 'ПК' },
};

function formatField(key: string, value: unknown, metricNames: Map<string, string>): string {
  if (value === null || value === undefined || value === '') return '—';
  if (key === 'is_active') return value ? 'включено' : 'выключено';
  if (key === 'system_code') return systemShort(String(value));
  if (key === 'metric_code') return metricNames.get(String(value)) ?? String(value);
  if (key === 'threshold_pct') return `${String(value)}%`;
  if (key === 'project_id') return 'только этот проект';
  if (key === 'date' || key === 'date_from' || key === 'date_to') return formatDate(String(value));
  if (key === 'goals' && Array.isArray(value)) {
    return value.map((goal: { name?: string }) => goal.name ?? '').join(', ') || 'нет';
  }
  if (key === 'settings' && typeof value === 'object') {
    const targets = (value as { targets?: { engine: string; region: string }[] }).targets;
    return targets?.length ? targets.map((t) => `${t.engine} · ${t.region}`).join(', ') : 'по умолчанию';
  }
  if (VALUES[key]?.[String(value)]) return VALUES[key][String(value)];
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

/** Подробности записи обычным текстом: «Поле: значение». */
function Details({ entry, metricNames }: { entry: AuditEntry; metricNames: Map<string, string> }) {
  const items = Object.entries(entry.changes)
    .filter(([key, value]) => !(key === 'project_id' && value === null))
    // Поля выводятся в порядке справочника подписей, а не в порядке хранения JSON.
    .sort(([left], [right]) => fieldOrder(left) - fieldOrder(right));
  if (items.length === 0) return <span className="muted">—</span>;
  return (
    <>
      {items.map(([key, value]) => (
        <div key={key}>
          <span className="muted">{FIELDS[key] ?? key}:</span> {formatField(key, value, metricNames)}
        </div>
      ))}
    </>
  );
}

/** Журнал изменений настроек: кто, в каком проекте и что менял. */
export function AuditPage() {
  const query = useQuery({ queryKey: ['audit'], queryFn: () => api.get<AuditEntry[]>('/audit') });
  const metrics = useQuery({ queryKey: ['metrics'], queryFn: () => api.get<MetricInfo[]>('/metrics'), staleTime: Infinity });
  const metricNames = new Map(metrics.data?.map((m) => [m.code, `${m.system_name}: ${m.name_ru}`]));

  return (
    <>
      <PageHeader title="Журнал изменений" subtitle="Последние 200 действий с настройками" />
      <QueryState query={query}>
        {(rows) => (
          <div className="panel table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Когда</th>
                  <th>Кто</th>
                  <th>Проект</th>
                  <th>Действие</th>
                  <th>Подробности</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td className="nowrap">{formatDateTime(row.created_at)}</td>
                    <td>{row.actor_name}</td>
                    <td>{row.project_name ?? <span className="muted">— общее —</span>}</td>
                    <td>
                      {ACTIONS[row.action] ?? row.action} {ENTITIES[row.entity] ?? row.entity}
                    </td>
                    <td>
                      <Details entry={row} metricNames={metricNames} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 && <div className="empty">Изменений пока не было.</div>}
          </div>
        )}
      </QueryState>
    </>
  );
}
