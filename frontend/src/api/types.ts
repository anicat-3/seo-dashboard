/** Типы ответов API (соответствуют схемам backend/app/api/schemas.py и сервису дашборда). */

export type Role = 'admin' | 'specialist';

export interface Me {
  account_id: number;
  login: string;
  role: Role;
  actor_name: string;
  member_id: number | null;
}

export interface TeamMemberShort {
  id: number;
  full_name: string;
}

/** Первый шаг входа: выбрать сотрудника или вход уже завершён. */
export interface LoginStep {
  status: 'choose_member' | 'done';
  members: TeamMemberShort[];
  me: Me | null;
}

export interface TeamMember extends TeamMemberShort {
  is_active: boolean;
  created_at: string;
}

export interface ActivityEntry {
  id: number;
  member_id: number | null;
  actor_name: string;
  event: 'login' | 'logout' | 'view';
  path: string | null;
  page: string | null;
  project_name: string | null;
  created_at: string;
}

export interface ActivitySummary {
  member_id: number;
  full_name: string;
  is_active: boolean;
  last_login: string | null;
  last_activity: string | null;
  logins: number;
  views: number;
  days: number;
}

export interface Account {
  id: number;
  login: string;
  role: Role;
  is_active: boolean;
  password_changed_at: string;
}

export interface SystemInfo {
  code: string;
  name: string;
  auth_type: 'oauth' | 'api_key';
}

export type CredentialStatus = 'ok' | 'error' | 'unchecked';

export interface Credential {
  id: number;
  system_code: string;
  label: string;
  account_login: string | null;
  auth_type: 'oauth' | 'api_key';
  status: CredentialStatus;
  status_message: string | null;
  expires_at: string | null;
  last_checked_at: string | null;
  created_by_name: string | null;
  has_secret: boolean;
  integrations_count: number;
}

export interface Resource {
  external_id: string;
  name: string;
  timezone: string;
  extra: Record<string, unknown>;
}

export interface Goal {
  external_goal_id: string;
  name: string;
}

export interface Project {
  id: number;
  /** Адрес проекта в URL: домен с дефисами вместо точек. */
  slug: string;
  name: string;
  domain: string;
  created_by_name: string;
  created_at: string;
  is_active: boolean;
  archived_at: string | null;
  systems: string[];
  /** Проект в избранном текущего сотрудника. */
  is_favorite: boolean;
}

export interface SyncRun {
  id: number;
  integration_id: number;
  job_type: 'daily' | 'backfill' | 'manual' | 'period';
  started_at: string;
  finished_at: string | null;
  status: 'running' | 'success' | 'partial' | 'error';
  date_from: string | null;
  date_to: string | null;
  rows_written: number;
  error_message: string | null;
  started_by_name: string | null;
}

export interface Integration {
  id: number;
  project_id: number;
  system_code: string;
  credential_id: number;
  external_id: string;
  external_name: string | null;
  timezone: string;
  settings: Record<string, unknown>;
  is_active: boolean;
  status: 'ok' | 'error' | 'pending';
  last_error: string | null;
  collect_from: string | null;
  disabled_at: string | null;
  created_by_name: string;
  created_at: string;
  goals: Goal[];
  last_run: SyncRun | null;
}

export interface MonitoredUrl {
  id: number;
  project_id: number;
  url: string;
  template_name: string | null;
  is_active: boolean;
}

export interface TestResult {
  ok: boolean;
  message: string;
  sample: Record<string, unknown>;
}

export interface PeriodRange {
  date_from: string;
  date_to: string;
}

export type CompareMode = 'previous' | 'previous_month' | 'year_ago' | 'custom';

export type Granularity = 'day' | 'week' | 'month';

export interface Card {
  metric_code: string;
  segment: string;
  label: string;
  unit: string;
  value: number | null;
  baseline: number | null;
  change_pct: number | null;
  higher_is_better: boolean;
  is_signal: boolean;
}

export interface Series {
  name: string;
  metric_code: string;
  segment: string;
  unit: string;
  inverse: boolean;
  points: [string, number | null][];
}

export interface ChartData {
  title: string;
  /** `multi` — сводный график консоли: у каждой метрики своя шкала, серии включаются переключателями. */
  kind: 'line' | 'bar' | 'multi';
  series: Series[];
  /** Метрики, показанные на сводном графике по умолчанию. */
  default_visible: string[];
  /** Пояснение к значениям, например «в среднем за день» при группировке по неделям. */
  note: string | null;
}

export interface SitemapRow {
  sitemap_url: string;
  snapshot_date: string;
  status: 'ok' | 'pending' | 'warning' | 'error';
  is_index?: boolean;
  submitted_urls: number | null;
  submitted_urls_before?: number | null;
  errors: number;
  warnings: number;
  last_downloaded_at: string | null;
}

export interface IssueRow {
  id: number;
  issue_code: string;
  title: string;
  severity: string;
  first_seen_at: string;
  affected_count: number | null;
  state?: 'open' | 'resolved';
  last_seen_at?: string;
  resolved_at?: string | null;
}

export interface CwvLatest {
  p75: number | null;
  good_pct: number | null;
  ni_pct: number | null;
  poor_pct: number | null;
  period_end: string;
}

export interface PsiDevice {
  run_at: string;
  performance_score: number | null;
  lcp: number | null;
  inp: number | null;
  cls: number | null;
  fcp: number | null;
  ttfb: number | null;
  category: string | null;
  is_origin_fallback: boolean;
}

export interface PsiRow {
  url: string;
  template_name: string | null;
  mobile: PsiDevice | null;
  desktop: PsiDevice | null;
}

export type DistributionBucket = '1-3' | '4-10' | '11-30' | '31-100' | '100+';

export type DistributionPoint = { date: string } & Record<DistributionBucket, number>;

export interface Distribution {
  segment: string;
  label: string;
  points: DistributionPoint[];
}

export interface CwvData {
  series: Record<string, Record<string, [string, number | null][]>>;
  latest: Record<string, Record<string, CwvLatest>>;
}

export interface Block {
  integration_id: number;
  system_code: string;
  system_name: string;
  external_id: string;
  external_name: string | null;
  status: 'ok' | 'error' | 'pending';
  last_error: string | null;
  history_from: string | null;
  incomplete_dates: string[];
  cards: Card[];
  charts: ChartData[];
  extras: {
    sitemaps?: SitemapRow[];
    issues?: IssueRow[];
    cwv?: CwvData;
    psi?: PsiRow[];
    distribution?: Distribution[];
  };
}

export interface Annotation {
  id: number;
  project_id?: number;
  date: string;
  text: string;
  author_name: string;
  created_at?: string;
}

export interface Signal {
  id: number;
  kind: 'metric' | 'issue';
  integration_id: number;
  metric_code: string | null;
  segment: string | null;
  detected_at: string;
  period_from: string | null;
  period_to: string | null;
  value: number | null;
  baseline: number | null;
  change_pct: number | null;
  message: string;
  status: 'new' | 'seen';
  seen_by_name: string | null;
  resolved_at: string | null;
  project_id?: number;
  project_slug?: string;
  project_name?: string;
  system_code?: string;
  system_name?: string;
}

export interface ProjectRef {
  id: number;
  slug: string;
  name: string;
  domain: string;
}

export interface Dashboard {
  project: ProjectRef;
  period: PeriodRange;
  compare: PeriodRange & { mode: CompareMode };
  granularity: { value: Granularity; allowed: Granularity[] };
  blocks: Block[];
  annotations: Annotation[];
  signals: Signal[];
}

export interface OverviewCell {
  metric_code: string;
  value: number | null;
  baseline: number | null;
  change_pct: number | null;
  higher_is_better: boolean;
  unit: string;
  source: string;
  is_signal: boolean;
}

export interface OverviewRow {
  project: ProjectRef;
  systems: string[];
  cells: Record<string, OverviewCell | null>;
  is_favorite: boolean;
  signals_new: number;
  signals_open: number;
  errors: number;
}

export interface Overview {
  period: PeriodRange;
  compare: PeriodRange & { mode: CompareMode };
  columns: { key: string; title: string }[];
  rows: OverviewRow[];
}

export interface SignalRule {
  id: number;
  project_id: number | null;
  metric_code: string;
  segment: string;
  comparison: 'wow' | 'mom';
  threshold_pct: number;
  is_active: boolean;
}

export interface MetricInfo {
  code: string;
  system_code: string;
  system_name: string;
  name_ru: string;
  unit: string;
  aggregation: string;
  higher_is_better: boolean;
}

export interface KeywordRow {
  keyword_id: number;
  keyword: string;
  group: string | null;
  segment: string;
  device: string;
  position: number | null;
  position_before: number | null;
  change: number | null;
  check_date: string | null;
  check_date_before: string | null;
  url: string | null;
}

export interface KeywordsResponse {
  rows: KeywordRow[];
  /** Даты съёмов в выбранном периоде и в базе сравнения (обычно по одной). */
  check_dates: string[];
  check_dates_before: string[];
  groups: string[];
  segments: string[];
  period: PeriodRange;
  compare: PeriodRange;
}

export interface ErrorsResponse {
  credentials: {
    id: number;
    system_code: string;
    system_name: string;
    label: string;
    status_message: string | null;
    last_checked_at: string | null;
  }[];
  integrations: {
    id: number;
    project_id: number;
    project_slug: string;
    project_name: string;
    system_code: string;
    system_name: string;
    external_id: string;
    last_error: string | null;
    credential_id: number;
  }[];
  runs: {
    id: number;
    integration_id: number;
    system_code: string;
    system_name: string;
    project_name: string;
    project_slug: string;
    job_type: string;
    status: string;
    started_at: string;
    date_from: string | null;
    date_to: string | null;
    error_message: string | null;
  }[];
}

export interface AuditEntry {
  id: number;
  actor_name: string;
  project_name: string | null;
  action: string;
  entity: string;
  entity_id: string | null;
  changes: Record<string, unknown>;
  created_at: string;
}

export type FeedbackStatus = 'new' | 'closed' | 'rejected' | 'paused' | 'postponed';

/** Обращение команды по работе дашборда. */
export interface FeedbackItem {
  id: number;
  author_name: string;
  message: string;
  status: FeedbackStatus;
  admin_note: string | null;
  resolved_by_name: string | null;
  created_at: string;
  updated_at: string | null;
}
