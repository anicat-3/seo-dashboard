/**
 * Переключатель проектов на дашборде: показывает текущий проект, открывает список
 * с поиском. Избранные проекты сотрудника идут первыми и отмечены звёздочкой.
 * Выбранный период и сравнение сохраняются при переходе.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { api } from '../api/client';
import type { Project } from '../api/types';

export function ProjectSwitcher({ currentSlug, currentName, currentDomain }: { currentSlug: string; currentName?: string; currentDomain?: string }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const projects = useQuery({ queryKey: ['projects', { archived: false }], queryFn: () => api.get<Project[]>('/projects') });

  const matches = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (projects.data ?? []).filter(
      (p) => !term || p.name.toLowerCase().includes(term) || p.domain.toLowerCase().includes(term),
    );
  }, [projects.data, search]);

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

  function go(project: Project) {
    setOpen(false);
    if (project.slug !== currentSlug) navigate(`/projects/${project.slug}${location.search}`);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'Escape') setOpen(false);
    else if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive(Math.min(active + 1, matches.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive(Math.max(active - 1, 0));
    } else if (event.key === 'Enter' && matches[active]) {
      event.preventDefault();
      go(matches[active]);
    }
  }

  const favorites = matches.filter((p) => p.is_favorite);
  const others = matches.filter((p) => !p.is_favorite);

  const renderItem = (project: Project) => {
    const index = matches.indexOf(project);
    return (
      <button
        key={project.id}
        type="button"
        role="option"
        aria-selected={project.slug === currentSlug}
        className={`switcher-item${project.slug === currentSlug ? ' current' : ''}${index === active ? ' active' : ''}`}
        onMouseEnter={() => setActive(index)}
        onClick={() => go(project)}
      >
        <span className="switcher-name">
          {project.is_favorite && <span className="star on">★</span>}
          {project.name}
        </span>
        <span className="small muted">{project.domain}</span>
      </button>
    );
  };

  return (
    <div className="switcher" ref={rootRef}>
      <button type="button" className="switcher-trigger" onClick={() => setOpen(!open)} aria-haspopup="listbox" aria-expanded={open}>
        <span className="switcher-title">{currentName ?? 'Проект'}</span>
        {currentDomain && <span className="switcher-domain">{currentDomain}</span>}
        <span aria-hidden="true" className="switcher-caret">
          ▾
        </span>
      </button>
      {open && (
        <div className="switcher-popover" onKeyDown={onKeyDown}>
          <input
            className="switcher-search"
            placeholder="Поиск по названию или домену"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setActive(0);
            }}
            autoFocus
            aria-label="Поиск проекта"
          />
          <div className="switcher-list" role="listbox" aria-label="Проекты">
            {favorites.length > 0 && <div className="switcher-group">Избранные</div>}
            {favorites.map(renderItem)}
            {favorites.length > 0 && others.length > 0 && <div className="switcher-group">Все проекты</div>}
            {others.map(renderItem)}
            {matches.length === 0 && <div className="empty small">Ничего не найдено</div>}
          </div>
        </div>
      )}
    </div>
  );
}
