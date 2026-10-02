"""Журнал изменений настроек (``audit_log``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(session: Session, *, account_id: int | None, actor_name: str, action: str,
          entity: str, entity_id: Any = None, changes: dict[str, Any] | None = None,
          project_name: str | None = None) -> None:
    """Добавить запись в журнал изменений.

    Секреты (токены, ключи, пароли) в ``changes`` передавать нельзя.

    Args:
        session: Сессия БД (запись фиксируется вместе с изменением).
        account_id: Учётная запись, под которой выполнено действие.
        actor_name: Имя сотрудника из сессии.
        action: Действие: ``create``, ``update``, ``pause``, ``delete`` …
        entity: Сущность: ``project``, ``integration``, ``credential`` …
        entity_id: Идентификатор сущности.
        changes: Изменённые поля.
        project_name: Название проекта, к которому относится действие.
    """
    session.add(AuditLog(
        account_id=account_id, actor_name=actor_name, action=action, entity=entity,
        entity_id=None if entity_id is None else str(entity_id), changes=changes or {},
        project_name=project_name,
    ))
