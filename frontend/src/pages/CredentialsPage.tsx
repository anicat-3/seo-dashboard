import { useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import type { Credential, SystemInfo } from '../api/types';
import { useConfirm } from '../components/ConfirmDialog';
import { ErrorNotice, Modal, PageHeader, QueryState, StatusBadge } from '../components/ui';
import { formatDateTime } from '../lib/format';

const AUTH_LABELS: Record<string, string> = { oauth: 'OAuth', api_key: 'API-ключ' };

/** Поля секрета по системам; значения шифруются на сервере и обратно не возвращаются. */
function secretFields(systemCode: string): { key: string; label: string }[] {
  if (systemCode === 'topvisor') {
    return [
      { key: 'user_id', label: 'User ID Топвизора' },
      { key: 'api_key', label: 'API-ключ' },
    ];
  }
  return [
    {
      key: 'api_key',
      label: systemCode === 'seranking' ? 'API-токен' : 'API-ключ',
    },
  ];
}

function CredentialDialog({
  systems,
  existing,
  onClose,
}: {
  systems: SystemInfo[];
  /** Если передан — режим переподключения: заменить ключ существующего доступа. */
  existing?: Credential;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [systemCode, setSystemCode] = useState(existing?.system_code ?? '');
  const [label, setLabel] = useState(existing?.label ?? '');
  const [accountLogin, setAccountLogin] = useState(existing?.account_login ?? '');
  const [secret, setSecret] = useState<Record<string, string>>({});

  const system = systems.find((s) => s.code === systemCode);
  const save = useMutation({
    mutationFn: () => {
      const body = {
        label,
        account_login: accountLogin || null,
        secret: Object.values(secret).some(Boolean) ? secret : undefined,
      };
      return existing
        ? api.patch(`/credentials/${existing.id}`, body)
        : api.post('/credentials', {
            ...body,
            system_code: systemCode,
            auth_type: 'api_key',
          });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['credentials'] });
      void queryClient.invalidateQueries({ queryKey: ['errors'] });
      onClose();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <Modal
      title={existing ? 'Переподключить аккаунт' : 'Подключить аккаунт системы'}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Отмена</button>
          <button className="primary" type="submit" form="credential-form" disabled={save.isPending || !systemCode}>
            Сохранить
          </button>
        </>
      }
    >
      <form id="credential-form" className="stack" onSubmit={submit}>
        <label className="field">
          Система
          <select value={systemCode} onChange={(e) => setSystemCode(e.target.value)} disabled={!!existing} required>
            <option value="">— выберите —</option>
            {systems.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        {!existing && system?.auth_type === 'oauth' ? (
          <div className="notice info">
            <div>
              Аккаунты {providerOf(system.code) === 'google' ? 'Google' : 'Яндекса'} подключаются входом в аккаунт: один вход даёт доступ сразу к{' '}
              {providerOf(system.code) === 'google' ? 'Search Console и GA4' : 'Метрике и Вебмастеру'}.
              <div style={{ marginTop: 8 }}>
                <span>Закройте это окно и нажмите «Войти через {providerOf(system.code) === 'google' ? 'Google' : 'Яндекс'}» вверху страницы.</span>
              </div>
            </div>
          </div>
        ) : (
          <>
            <label className="field">
              Название доступа
              <input value={label} onChange={(e) => setLabel(e.target.value)} required maxLength={200} placeholder="Например: Google-аккаунт №3" />
            </label>
            <label className="field">
              Логин аккаунта (для справки)
              <input value={accountLogin} onChange={(e) => setAccountLogin(e.target.value)} maxLength={255} />
            </label>
            {secretFields(systemCode).map((field) => (
                <label className="field" key={field.key}>
                  {field.label}
                  <input
                    type="password"
                    autoComplete="off"
                    value={secret[field.key] ?? ''}
                    onChange={(e) => setSecret({ ...secret, [field.key]: e.target.value })}
                    required={!existing}
                    placeholder={existing ? 'Оставьте пустым, чтобы не менять' : ''}
                  />
                </label>
              ))}
            <span className="field-hint">
              Ключ хранится в базе в зашифрованном виде и нигде не отображается.
              {(systemCode === 'psi' || systemCode === 'crux') &&
                ' Один ключ Google Cloud подходит и для PageSpeed Insights, и для CrUX — добавьте его для обеих систем.'}
            </span>
          </>
        )}
        <ErrorNotice error={save.error} />
      </form>
    </Modal>
  );
}

/** OAuth-провайдер системы: Google — GSC и GA4, Яндекс — Метрика и Вебмастер. */
function providerOf(systemCode: string): 'google' | 'yandex' {
  return systemCode === 'metrika' || systemCode === 'ywm' ? 'yandex' : 'google';
}

interface OAuthProvider {
  name: 'google' | 'yandex';
  title: string;
  configured: boolean;
  redirect_uri: string;
  /** Код подтверждения вводится вручную (Яндекс). */
  manual_code: boolean;
}

/**
 * Вход через Яндекс: Яндекс показывает код подтверждения на своей странице
 * (адрес возврата приложения — https://oauth.yandex.ru/verification_code),
 * администратор вставляет его сюда.
 */
function VerificationCodeDialog({ provider, onClose }: { provider: OAuthProvider; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [code, setCode] = useState('');
  const [opened, setOpened] = useState(false);
  const submit = useMutation({
    mutationFn: () =>
      api.post<{ login: string }>(`/oauth/${provider.name}/code`, { code: code.trim() }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['credentials'] });
      void queryClient.invalidateQueries({ queryKey: ['errors'] });
    },
  });

  return (
    <Modal
      title={`Вход через ${provider.title}`}
      onClose={onClose}
      footer={
        submit.isSuccess ? (
          <button className="primary" onClick={onClose}>
            Готово
          </button>
        ) : (
          <>
            <button onClick={onClose}>Отмена</button>
            <button className="primary" onClick={() => submit.mutate()} disabled={code.trim().length < 4 || submit.isPending}>
              {submit.isPending ? 'Подключение…' : 'Подключить'}
            </button>
          </>
        )
      }
    >
      {submit.isSuccess ? (
        <div className="notice info">
          Аккаунт <b>{submit.data.login}</b> подключён: доступы «Яндекс.Метрика» и «Яндекс.Вебмастер» появились в списке.
        </div>
      ) : (
        <>
          <div>
            <b>1.</b> Откройте страницу Яндекса, войдите в нужный аккаунт и нажмите «Разрешить».
            <div style={{ marginTop: 8 }}>
              <a href={`/api/oauth/${provider.name}/start`} target="_blank" rel="noreferrer" onClick={() => setOpened(true)}>
                <button type="button" className={opened ? '' : 'primary'}>
                  Открыть страницу входа {provider.title}
                </button>
              </a>
            </div>
            <div className="field-hint" style={{ marginTop: 6 }}>
              Для другого аккаунта Яндекса сначала выйдите из текущего в браузере или откройте ссылку в окне инкогнито.
            </div>
          </div>
          <label className="field">
            <span>
              <b>2.</b> Скопируйте код подтверждения со страницы Яндекса и вставьте его сюда
            </span>
            <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Например, 1234567" autoComplete="off" />
            <span className="field-hint">Код действует 10 минут.</span>
          </label>
          <ErrorNotice error={submit.error} />
        </>
      )}
    </Modal>
  );
}

/** Доступы к аккаунтам внешних систем и их переподключение. */
export function CredentialsPage() {
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const [params, setParams] = useSearchParams();
  const providers = useQuery({
    queryKey: ['oauth-providers'],
    queryFn: () => api.get<OAuthProvider[]>('/oauth/providers'),
  });
  const connected = params.get('connected');
  const [codeProvider, setCodeProvider] = useState<OAuthProvider | null>(null);
  const oauthError = params.get('oauth_error');
  const [dialog, setDialog] = useState<{ existing?: Credential } | null>(null);
  const systems = useQuery({
    queryKey: ['systems'],
    queryFn: () => api.get<SystemInfo[]>('/systems'),
  });
  const credentials = useQuery({
    queryKey: ['credentials', ''],
    queryFn: () => api.get<Credential[]>('/credentials'),
  });
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['credentials'] });
    void queryClient.invalidateQueries({ queryKey: ['errors'] });
  };
  const check = useMutation({
    mutationFn: (id: number) => api.post(`/credentials/${id}/check`),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/credentials/${id}`),
    onSuccess: invalidate,
  });
  const systemName = (code: string) => systems.data?.find((s) => s.code === code)?.name ?? code;

  return (
    <>
      <PageHeader title="Подключения" subtitle="Доступы к API: аккаунты Google, Яндекса и других сервисов, из которых собираются данные">
        {providers.data?.map((provider) => {
          const hint = provider.configured
            ? undefined
            : `Сначала заполните ${provider.name.toUpperCase()}_CLIENT_ID_1 и ${provider.name.toUpperCase()}_CLIENT_SECRET_1 в .env`;
          return provider.manual_code ? (
            <button key={provider.name} disabled={!provider.configured} title={hint} onClick={() => setCodeProvider(provider)}>
              Войти через {provider.title}
            </button>
          ) : (
            <a key={provider.name} href={provider.configured ? `/api/oauth/${provider.name}/start` : undefined} title={hint}>
              <button disabled={!provider.configured}>Войти через {provider.title}</button>
            </a>
          );
        })}
        <button className="primary" onClick={() => setDialog({})}>
          + Подключить по API-ключу
        </button>
      </PageHeader>
      {connected && (
        <div className="notice info" style={{ marginBottom: 12 }}>
          <span>
            Аккаунт <b>{connected}</b> подключён ({params.get('provider')}). Доступы для его систем появились в списке — теперь их можно выбирать при
            подключении систем к проектам.
          </span>
          <button className="small ghost" onClick={() => setParams({}, { replace: true })}>
            ✕
          </button>
        </div>
      )}
      {oauthError && (
        <div className="notice error" style={{ marginBottom: 12 }}>
          <span>{oauthError}</span>
          <button className="small ghost" onClick={() => setParams({}, { replace: true })}>
            ✕
          </button>
        </div>
      )}
      {providers.data?.some((p) => !p.configured) && (
        <div className="notice warn" style={{ marginBottom: 12 }}>
          <span>
            Для входа через{' '}
            {providers.data
              .filter((p) => !p.configured)
              .map((p) => p.title)
              .join(' и ')}{' '}
            нужно OAuth-приложение: заполните ключи в файле .env и перезапустите приложение. Адреса возврата для настроек приложений:{' '}
            {providers.data
              .filter((p) => !p.configured)
              .map((p) => p.redirect_uri)
              .join(', ')}
            . Подробнее — docs/api-keys.md.
          </span>
        </div>
      )}
      <ErrorNotice error={check.error ?? remove.error} />
      <QueryState query={credentials}>
        {(data) =>
          data.length === 0 ? (
            <div className="panel empty">Доступов пока нет. Подключите аккаунт системы, чтобы добавлять её к проектам.</div>
          ) : (
            <div className="panel table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Система</th>
                    <th>Доступ</th>
                    <th>Тип</th>
                    <th>Статус</th>
                    <th>Проверен</th>
                    <th className="num">Подключений</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.map((credential) => (
                    <tr key={credential.id}>
                      <td>{systemName(credential.system_code)}</td>
                      <td>
                        <b>{credential.label}</b>
                        <div className="small muted">{credential.account_login ?? ''}</div>
                      </td>
                      <td>{AUTH_LABELS[credential.auth_type]}</td>
                      <td>
                        <StatusBadge status={credential.status} />
                        {credential.status_message && <div className="small muted">{credential.status_message}</div>}
                      </td>
                      <td className="nowrap">{formatDateTime(credential.last_checked_at)}</td>
                      <td className="num">{credential.integrations_count}</td>
                      <td>
                        <div className="row" style={{ justifyContent: 'flex-end' }}>
                          <button
                            className="small"
                            onClick={() => check.mutate(credential.id)}
                            disabled={check.isPending}
                            title={credential.system_code === 'psi' ? 'Проверка PageSpeed Insights занимает до 30 секунд' : undefined}
                          >
                            {check.isPending && check.variables === credential.id ? 'Проверка…' : 'Проверить'}
                          </button>
                          {credential.auth_type === 'oauth' &&
                            (providerOf(credential.system_code) === 'yandex' ? (
                              <button
                                className="small"
                                onClick={() => setCodeProvider(providers.data?.find((p) => p.name === 'yandex') ?? null)}
                              >
                                Войти заново
                              </button>
                            ) : (
                              <a href="/api/oauth/google/start">
                                <button className="small">Войти заново</button>
                              </a>
                            ))}
                          {credential.auth_type === 'api_key' && (
                            <button className="small" onClick={() => setDialog({ existing: credential })}>
                              Переподключить
                            </button>
                          )}
                          <button
                            className="small danger"
                            disabled={credential.integrations_count > 0}
                            title={credential.integrations_count > 0 ? 'Доступ используется подключениями' : undefined}
                            onClick={async () => {
                              const ok = await confirm({
                                title: `Удалить доступ «${credential.label}»?`,
                                message:
                                  'Сохранённый ключ будет удалён. Чтобы снова собирать данные из этого аккаунта, его придётся подключить заново.',
                                confirmLabel: 'Удалить',
                                danger: true,
                              });
                              if (ok) remove.mutate(credential.id);
                            }}
                          >
                            Удалить
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </QueryState>
      {codeProvider && <VerificationCodeDialog provider={codeProvider} onClose={() => setCodeProvider(null)} />}
      {dialog && systems.data && <CredentialDialog systems={systems.data} existing={dialog.existing} onClose={() => setDialog(null)} />}
    </>
  );
}
