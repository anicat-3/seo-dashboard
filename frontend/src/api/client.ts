/**
 * HTTP-клиент API.
 *
 * Все запросы идут на тот же origin (`/api`), cookie сессии отправляются автоматически.
 * Для изменяющих запросов добавляется заголовок `X-Requested-With` — защита от CSRF
 * на стороне сервера.
 */

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

/** Собрать строку запроса, пропуская пустые значения. */
export function toQuery(params: Query = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

/** Извлечь понятное сообщение из ответа FastAPI (`detail` — строка или список ошибок). */
async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === 'string') return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail.map((d: { msg?: string }) => d.msg ?? '').join('; ');
    }
  } catch {
    /* тело не JSON */
  }
  return `Ошибка ${response.status}`;
}

/** Слушатели события «сессия истекла» (401). */
const unauthorizedListeners = new Set<() => void>();

export function onUnauthorized(listener: () => void): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

async function request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET') headers['X-Requested-With'] = 'fetch';
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const response = await fetch(`/api${path}${toQuery(query)}`, {
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 401 && path !== '/auth/login' && path !== '/auth/me') {
    unauthorizedListeners.forEach((listener) => listener());
  }
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>('GET', path, undefined, query),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>('POST', path, body ?? {}, query),
  patch: <T>(path: string, body?: unknown, query?: Query) => request<T>('PATCH', path, body ?? {}, query),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
  delete: <T>(path: string) => request<T>('DELETE', path),
};

/** Ссылка на выгрузку CSV (скачивается браузером по обычной ссылке). */
export function csvUrl(path: string, query: Query = {}): string {
  return `/api${path}${toQuery({ ...query, format: 'csv' })}`;
}
