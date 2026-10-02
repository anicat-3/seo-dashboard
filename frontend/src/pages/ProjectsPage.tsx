import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import { useUser } from '../auth/AuthContext';
import type { Project } from '../api/types';
import { useConfirm } from '../components/ConfirmDialog';
import { ErrorNotice, Modal, PageHeader, QueryState, StatusBadge, SystemChips } from '../components/ui';
import { formatDate } from '../lib/format';

function CreateProjectDialog({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('');
  const [domain, setDomain] = useState('');
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const create = useMutation({
    mutationFn: () => api.post<Project>('/projects', { name, domain }),
    onSuccess: (project) => {
      void queryClient.invalidateQueries({ queryKey: ['projects'] });
      navigate(`/projects/${project.slug}/settings`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <Modal
      title="Новый проект"
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose}>Отмена</button>
          <button className="primary" form="create-project" type="submit" disabled={create.isPending}>
            Создать
          </button>
        </>
      }
    >
      <form id="create-project" className="stack" onSubmit={submit}>
        <label className="field">
          Название
          <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} autoFocus />
        </label>
        <label className="field">
          Домен
          <input value={domain} onChange={(e) => setDomain(e.target.value)} required placeholder="site.by" />
          <span className="field-hint">После создания подключите к проекту нужные системы.</span>
        </label>
        <ErrorNotice error={create.error} />
      </form>
    </Modal>
  );
}

/** Список проектов: создание, архивирование, возврат из архива и полное удаление. */
export function ProjectsPage() {
  const [creating, setCreating] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  // Создание, архивирование и удаление проектов доступны только администратору.
  const isAdmin = useUser().role === 'admin';
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const projects = useQuery({
    queryKey: ['projects', { archived: showArchived }],
    queryFn: () => api.get<Project[]>('/projects', { include_archived: showArchived }),
  });
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['projects'] });
    void queryClient.invalidateQueries({ queryKey: ['overview'] });
    void queryClient.invalidateQueries({ queryKey: ['signals'] });
    void queryClient.invalidateQueries({ queryKey: ['errors'] });
  };
  const archive = useMutation({
    mutationFn: ({ id, restore }: { id: number; restore: boolean }) => api.post(`/projects/${id}/archive`, {}, { restore }),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: (id: number) => api.delete(`/projects/${id}`), onSuccess: invalidate });

  async function toggleArchive(project: Project) {
    const restore = !project.is_active;
    const ok =
      restore ||
      (await confirm({
        title: `Архивировать «${project.name}»?`,
        message: 'Сбор данных по проекту остановится, проект исчезнет из сводки. Накопленная история сохранится, проект можно вернуть из архива.',
        confirmLabel: 'В архив',
      }));
    if (ok) archive.mutate({ id: project.id, restore });
  }

  async function removeProject(project: Project) {
    const ok = await confirm({
      title: `Удалить «${project.name}» навсегда?`,
      message: (
        <>
          Будут безвозвратно удалены все подключения проекта и вся накопленная история: метрики, позиции, снимки карт сайта, ошибки,
          сигналы и пометки. <b>Восстановить данные будет нельзя</b> — снимки состояния задним числом не собираются. Если проект может
          понадобиться, отправьте его в архив.
        </>
      ),
      confirmLabel: 'Удалить навсегда',
      danger: true,
      requireText: project.domain,
    });
    if (ok) remove.mutate(project.id);
  }

  return (
    <>
      <PageHeader title="Проекты">
        <label className="row small">
          <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
          Показывать архивные
        </label>
        {isAdmin && (
          <button className="primary" onClick={() => setCreating(true)}>
            + Новый проект
          </button>
        )}
      </PageHeader>
      <ErrorNotice error={archive.error ?? remove.error} />
      <QueryState query={projects}>
        {(data) =>
          data.length === 0 ? (
            <div className="panel empty">Проектов пока нет.</div>
          ) : (
            <div className="panel table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Проект</th>
                    <th>Подключённые системы</th>
                    <th>Создан</th>
                    <th>Статус</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.map((project) => (
                    <tr key={project.id}>
                      <td>
                        <Link to={`/projects/${project.slug}`}>
                          <b>{project.name}</b>
                        </Link>
                        <div className="small muted">{project.domain}</div>
                      </td>
                      <td>{project.systems.length ? <SystemChips systems={project.systems} /> : <span className="muted">—</span>}</td>
                      <td className="nowrap">
                        {formatDate(project.created_at)}
                        <div className="small muted">{project.created_by_name}</div>
                      </td>
                      <td>
                        <StatusBadge status={project.is_active ? 'ok' : 'disabled'} label={project.is_active ? 'Активен' : 'В архиве'} />
                      </td>
                      <td>
                        <div className="row" style={{ justifyContent: 'flex-end' }}>
                          <Link to={`/projects/${project.slug}/settings`}>
                            <button className="small">Настройки</button>
                          </Link>
                          {isAdmin && (
                            <>
                              <button className="small" disabled={archive.isPending} onClick={() => void toggleArchive(project)}>
                                {project.is_active ? 'В архив' : 'Вернуть'}
                              </button>
                              <button className="small danger" disabled={remove.isPending} onClick={() => void removeProject(project)}>
                                Удалить
                              </button>
                            </>
                          )}
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
      {creating && <CreateProjectDialog onClose={() => setCreating(false)} />}
    </>
  );
}
