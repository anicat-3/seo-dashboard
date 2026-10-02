"""Обращения команды по работе дашборда: отправка — все, разбор — администратор."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import Admin, DbSession, User
from app.api.schemas import FeedbackIn, FeedbackOut, FeedbackUpdate
from app.models import Feedback

router = APIRouter(tags=["feedback"])


@router.post("/feedback", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
def send_feedback(payload: FeedbackIn, user: User, db: DbSession) -> Feedback:
    """Отправить предложение или замечание администратору."""
    item = Feedback(account_id=user.account_id, author_name=user.actor_name,
                    message=payload.message.strip(), status="new")
    db.add(item)
    db.commit()
    return item


@router.get("/feedback", response_model=list[FeedbackOut])
def list_feedback(_: Admin, db: DbSession, status_filter: str | None = None) -> list[Feedback]:
    """Обращения, новые сверху."""
    stmt = select(Feedback).order_by(Feedback.created_at.desc())
    if status_filter:
        stmt = stmt.where(Feedback.status == status_filter)
    return list(db.scalars(stmt))


@router.get("/feedback/new-count")
def new_feedback_count(_: Admin, db: DbSession) -> dict[str, int]:
    """Число необработанных обращений — для счётчика в меню."""
    count = db.scalar(select(func.count()).select_from(Feedback)
                      .where(Feedback.status == "new"))
    return {"count": count or 0}


@router.patch("/feedback/{feedback_id}", response_model=FeedbackOut)
def update_feedback(feedback_id: int, payload: FeedbackUpdate, user: Admin,
                    db: DbSession) -> Feedback:
    """Сменить статус обращения и/или ответ администратора."""
    item = db.get(Feedback, feedback_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Обращение не найдено")
    if payload.status is not None:
        item.status = payload.status
    if payload.admin_note is not None:
        item.admin_note = payload.admin_note.strip() or None
    item.resolved_by_name = user.actor_name
    item.updated_at = datetime.now(UTC)
    db.commit()
    return item
