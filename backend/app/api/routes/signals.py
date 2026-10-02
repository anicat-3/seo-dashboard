"""Сигналы, правила подсветки и пометки на графиках."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import Admin, DbSession, User, get_project_or_404
from app.api.schemas import (
    AnnotationIn,
    AnnotationOut,
    SignalRuleIn,
    SignalRuleOut,
    SignalRuleUpdate,
)
from app.catalog import METRICS, SYSTEM_NAMES
from app.models import Annotation, Integration, Project, Signal, SignalRule
from app.services.audit import audit
from app.services.dashboard import signal_to_dict

router = APIRouter(tags=["signals"])


def _project_name(db, project_id: int | None) -> str | None:
    """Название проекта для журнала изменений (``None`` — общее правило)."""
    project = db.get(Project, project_id) if project_id is not None else None
    return project.name if project else None


@router.get("/metrics")
def metric_catalog(_: User) -> list[dict]:
    """Каталог метрик (для выбора метрики в правилах)."""
    return [{"code": m.code, "system_code": m.system_code,
             "system_name": SYSTEM_NAMES[m.system_code], "name_ru": m.name_ru, "unit": m.unit,
             "aggregation": m.aggregation, "higher_is_better": m.higher_is_better}
            for m in METRICS]


# -------------------------------------------------------------------- сигналы
@router.get("/signals")
def list_signals(_: User, db: DbSession, project_id: int | None = None,
                 include_resolved: bool = False, limit: int = 200) -> list[dict]:
    """Сигналы (по умолчанию только открытые) с названием проекта и системы."""
    stmt = (select(Signal, Integration, Project.slug, Project.name)
            .join(Integration, Integration.id == Signal.integration_id)
            .join(Project, Project.id == Integration.project_id))
    if project_id is not None:
        stmt = stmt.where(Integration.project_id == project_id)
    if not include_resolved:
        stmt = stmt.where(Signal.resolved_at.is_(None))
    stmt = stmt.order_by(Signal.status, Signal.detected_at.desc()).limit(min(limit, 1000))
    result = []
    for signal, integration, slug, name in db.execute(stmt):
        item = signal_to_dict(signal)
        item.update(project_id=integration.project_id, project_slug=slug, project_name=name,
                    system_code=integration.system_code,
                    system_name=SYSTEM_NAMES.get(integration.system_code))
        result.append(item)
    return result


@router.post("/signals/{signal_id}/seen")
def mark_seen(signal_id: int, user: User, db: DbSession) -> dict:
    """Отметить сигнал просмотренным."""
    signal = db.get(Signal, signal_id)
    if signal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сигнал не найден")
    signal.status, signal.seen_by_name = "seen", user.actor_name
    db.commit()
    return signal_to_dict(signal)


# -------------------------------------------------------------------- правила
@router.get("/signal-rules", response_model=list[SignalRuleOut])
def list_rules(_: User, db: DbSession, project_id: int | None = None) -> list[SignalRule]:
    """Общие правила и (если указан проект) правила проекта."""
    stmt = select(SignalRule).order_by(SignalRule.metric_code, SignalRule.segment)
    if project_id is None:
        stmt = stmt.where(SignalRule.project_id.is_(None))
    else:
        stmt = stmt.where((SignalRule.project_id.is_(None)) | (SignalRule.project_id == project_id))
    return list(db.scalars(stmt))


@router.post("/signal-rules", response_model=SignalRuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(payload: SignalRuleIn, user: Admin, db: DbSession) -> SignalRule:
    """Создать правило (например, свой порог для проекта или метрики)."""
    if payload.project_id is not None:
        get_project_or_404(db, payload.project_id)
    rule = SignalRule(**payload.model_dump())
    db.add(rule)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестная метрика") from exc
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="create",
          entity="signal_rule", entity_id=rule.id, changes=payload.model_dump(),
          project_name=_project_name(db, rule.project_id))
    db.commit()
    return rule


@router.patch("/signal-rules/{rule_id}", response_model=SignalRuleOut)
def update_rule(rule_id: int, payload: SignalRuleUpdate, user: Admin, db: DbSession) -> SignalRule:
    """Изменить порог, базу сравнения или выключить правило."""
    rule = db.get(SignalRule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Правило не найдено")
    changes = payload.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(rule, key, value)
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="update",
          entity="signal_rule", entity_id=rule.id,
          changes={"metric_code": rule.metric_code, **changes},
          project_name=_project_name(db, rule.project_id))
    db.commit()
    return rule


@router.delete("/signal-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, user: Admin, db: DbSession) -> None:
    """Удалить правило проекта (общие правила не удаляются, их можно выключить)."""
    rule = db.get(SignalRule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Правило не найдено")
    if rule.project_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Общее правило можно только выключить")
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="delete",
          entity="signal_rule", entity_id=rule.id,
          changes={"metric_code": rule.metric_code, "segment": rule.segment},
          project_name=_project_name(db, rule.project_id))
    db.delete(rule)
    db.commit()


# -------------------------------------------------------------------- пометки
@router.get("/projects/{project_id}/annotations", response_model=list[AnnotationOut])
def list_annotations(project_id: str, _: User, db: DbSession) -> list[Annotation]:
    """Все пометки проекта."""
    project = get_project_or_404(db, project_id)
    return list(db.scalars(select(Annotation).where(Annotation.project_id == project.id)
                           .order_by(Annotation.date.desc())))


@router.post("/projects/{project_id}/annotations", response_model=AnnotationOut,
             status_code=status.HTTP_201_CREATED)
def create_annotation(project_id: str, payload: AnnotationIn, user: User,
                      db: DbSession) -> Annotation:
    """Добавить пометку на графики проекта."""
    project = get_project_or_404(db, project_id)
    annotation = Annotation(project_id=project.id, date=payload.date, text=payload.text,
                            author_name=user.actor_name)
    db.add(annotation)
    db.flush()
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="create",
          entity="annotation", entity_id=annotation.id, changes=payload.model_dump(mode="json"),
          project_name=project.name)
    db.commit()
    return annotation


@router.delete("/annotations/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_annotation(annotation_id: int, user: User, db: DbSession) -> None:
    """Удалить пометку."""
    annotation = db.get(Annotation, annotation_id)
    if annotation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пометка не найдена")
    audit(db, account_id=user.account_id, actor_name=user.actor_name, action="delete",
          entity="annotation", entity_id=annotation.id, changes={"text": annotation.text},
          project_name=_project_name(db, annotation.project_id))
    db.delete(annotation)
    db.commit()
