"""Командная строка приложения: ``seo-dashboard <команда>`` или ``python -m app.cli``.

Команды:
    init-env        Создать .env из .env.example со случайными SECRET_KEY и ENCRYPTION_KEY.
    setup           Загрузить справочники и создать две учётные записи (admin, seo).
    set-password    Сменить пароль учётной записи.
    sync            Запустить ежедневный сбор немедленно (или по одному подключению).
    detect-signals  Пересчитать подсветку изменений.
    purge-data      Удалить все проекты, доступы и собранные данные.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import secrets
import string
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import REPO_ROOT

ADMIN_LOGIN = "admin"
SPECIALIST_LOGIN = "seo"


def _generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ----------------------------------------------------------------- init-env
def cmd_init_env(args: argparse.Namespace) -> int:
    """Создать .env со случайными ключами; существующий файл не перезаписывается."""
    from app.security import generate_encryption_key

    target = REPO_ROOT / ".env"
    if target.exists() and not args.force:
        print(f"{target} уже существует — пропускаю (используйте --force для перезаписи)")
        return 0
    template = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    content = (template
               .replace("SECRET_KEY=change-me", f"SECRET_KEY={secrets.token_urlsafe(48)}")
               .replace("ENCRYPTION_KEY=change-me", f"ENCRYPTION_KEY={generate_encryption_key()}"))
    if args.database_url:
        content = "\n".join(
            f"DATABASE_URL={args.database_url}" if line.startswith("DATABASE_URL=") else line
            for line in content.splitlines()
        ) + "\n"
    target.write_text(content, encoding="utf-8")
    print(f"Создан {target}. Ключ ENCRYPTION_KEY храните в резервной копии: "
          "без него сохранённые токены не расшифровать.")
    return 0


# -------------------------------------------------------------------- setup
def seed_reference_data(session) -> None:
    """Загрузить (обновить) справочники систем, метрик и общие правила подсветки."""
    from app.catalog import DEFAULT_SIGNAL_RULES, METRICS, SYSTEMS
    from app.config import get_settings
    from app.models import MetricCatalog, SignalRule, System

    for s in SYSTEMS:
        stmt = insert(System).values(code=s.code, name=s.name, auth_type=s.auth_type,
                                     sort_order=s.sort_order)
        session.execute(stmt.on_conflict_do_update(
            index_elements=["code"], set_={"name": s.name, "auth_type": s.auth_type,
                                           "sort_order": s.sort_order}))
    for m in METRICS:
        values = {"system_code": m.system_code, "name_ru": m.name_ru, "unit": m.unit,
                  "aggregation": m.aggregation, "weight_metric_code": m.weight_metric_code,
                  "higher_is_better": m.higher_is_better}
        stmt = insert(MetricCatalog).values(code=m.code, **values)
        session.execute(stmt.on_conflict_do_update(index_elements=["code"], set_=values))
    existing = {(r.metric_code, r.segment) for r in session.scalars(
        select(SignalRule).where(SignalRule.project_id.is_(None)))}
    threshold = get_settings().default_signal_threshold_pct
    for metric_code, segment, comparison in DEFAULT_SIGNAL_RULES:
        if (metric_code, segment) not in existing:
            session.add(SignalRule(project_id=None, metric_code=metric_code, segment=segment,
                                   comparison=comparison, threshold_pct=threshold,
                                   is_active=True))


def _ask_password(login: str) -> str:
    from app.security import MIN_PASSWORD_LENGTH

    while True:
        first = getpass.getpass(f"Пароль для «{login}» (не короче {MIN_PASSWORD_LENGTH}): ")
        if len(first) < MIN_PASSWORD_LENGTH:
            print("Слишком короткий пароль")
            continue
        if getpass.getpass("Повторите пароль: ") == first:
            return first
        print("Пароли не совпадают")


def cmd_setup(args: argparse.Namespace) -> int:
    """Загрузить справочники и создать учётные записи администратора и SEO-команды."""
    from app.db import session_scope
    from app.models import Account
    from app.security import hash_password

    generated: list[tuple[str, str]] = []
    with session_scope() as session:
        seed_reference_data(session)
        for login, role in ((ADMIN_LOGIN, "admin"), (SPECIALIST_LOGIN, "specialist")):
            if session.scalar(select(Account).where(Account.login == login)):
                print(f"Учётная запись «{login}» уже существует")
                continue
            if args.generate_passwords:
                password = _generate_password()
                generated.append((login, password))
            else:
                password = _ask_password(login)
            session.add(Account(login=login, role=role, is_active=True,
                                password_hash=hash_password(password)))
            print(f"Создана учётная запись «{login}» ({role})")
    if generated:
        path = Path(args.generate_passwords)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{login}: {pw}\n" for login, pw in generated), encoding="utf-8")
        print(f"Сгенерированные пароли записаны в {path}. Смените их после первого входа "
              "и удалите файл.")
    print("Справочники загружены.")
    return 0


def cmd_set_password(args: argparse.Namespace) -> int:
    """Сменить пароль учётной записи (завершает её активные сессии)."""
    from app.db import session_scope
    from app.models import Account
    from app.security import hash_password

    with session_scope() as session:
        account = session.scalar(select(Account).where(Account.login == args.login))
        if account is None:
            print(f"Учётная запись «{args.login}» не найдена", file=sys.stderr)
            return 1
        account.password_hash = hash_password(_ask_password(args.login))
        account.password_changed_at = datetime.now(UTC)
    print("Пароль изменён")
    return 0


# -------------------------------------------------------------------- sync
def cmd_sync(args: argparse.Namespace) -> int:
    """Запустить сбор немедленно."""
    from app.models.sync import JOB_MANUAL
    from app.services import collector

    if args.integration:
        date_from = date.fromisoformat(args.date_from) if args.date_from else None
        date_to = date.fromisoformat(args.date_to) if args.date_to else None
        outcome = collector.run_integration_sync(args.integration, JOB_MANUAL, date_from,
                                                 date_to, actor_name="CLI")
        print(f"{outcome.status}: строк {outcome.rows_written} {outcome.error or ''}")
        return 0 if outcome.status != "error" else 1
    print(collector.run_daily_sync())
    return 0


def cmd_detect_signals(_: argparse.Namespace) -> int:
    """Пересчитать сигналы по текущим данным."""
    from app.db import session_scope
    from app.services import signals

    with session_scope() as session:
        print(f"Создано сигналов: {signals.detect_signals(session)}")
    return 0


#: Таблицы с проектами, доступами, собранными данными и журналами — всё, что удаляет
#: ``purge-data``. Учётные записи, команда и справочники в список не входят.
PURGE_TABLES = (
    "annotations", "signals", "signal_rules", "favorite_projects", "psi_runs",
    "monitored_urls", "keyword_positions", "keywords", "cwv_weekly", "site_issues",
    "sitemap_snapshots", "period_metrics", "daily_metrics", "raw_responses", "sync_runs",
    "integration_goals", "integrations", "credentials", "projects",
)
LOG_TABLES = ("audit_log", "activity_log", "feedback")


def cmd_purge_data(args: argparse.Namespace) -> int:
    """Удалить все проекты, доступы и собранные данные.

    Сохраняются учётные записи, состав команды и справочники; общие правила
    подсветки восстанавливаются со значениями по умолчанию.
    """
    from sqlalchemy import text

    from app.db import session_scope

    tables = PURGE_TABLES + (LOG_TABLES if args.with_logs else ())
    if not args.yes:
        print("Будут безвозвратно удалены все проекты, доступы к API, собранные данные"
              + (" и журналы" if args.with_logs else "") + ".")
        if input("Продолжить? Введите «да»: ").strip().lower() != "да":
            print("Отменено")
            return 1
    with session_scope() as session:
        counts = {t: session.scalar(text(f"SELECT count(*) FROM {t}")) for t in  # noqa: S608
                  ("projects", "credentials", "daily_metrics", "keyword_positions")}
        # RESTART IDENTITY: новые проекты и доступы снова нумеруются с 1.
        session.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        # Пустые месячные секции позиций больше не нужны.
        for (name,) in session.execute(text(
                "SELECT inhrelid::regclass::text FROM pg_inherits "
                "WHERE inhparent = 'keyword_positions'::regclass")):
            session.execute(text(f'DROP TABLE "{name}"'))
        seed_reference_data(session)
    print("Удалено: " + ", ".join(f"{k} — {v}" for k, v in counts.items()))
    print("Учётные записи, команда и справочники сохранены.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Построить разбор аргументов командной строки."""
    parser = argparse.ArgumentParser(prog="seo-dashboard", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-env", help="создать .env со случайными ключами")
    p.add_argument("--database-url", help="строка подключения к БД")
    p.add_argument("--force", action="store_true", help="перезаписать существующий .env")
    p.set_defaults(func=cmd_init_env)

    p = sub.add_parser("setup", help="справочники и учётные записи")
    p.add_argument("--generate-passwords", metavar="FILE",
                   help="сгенерировать пароли и записать их в файл (вместо ввода)")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("set-password", help="сменить пароль учётной записи")
    p.add_argument("login", choices=[ADMIN_LOGIN, SPECIALIST_LOGIN])
    p.set_defaults(func=cmd_set_password)

    p = sub.add_parser("sync", help="запустить сбор немедленно")
    p.add_argument("--integration", type=int, help="ID подключения (по умолчанию — все)")
    p.add_argument("--date-from")
    p.add_argument("--date-to")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("detect-signals", help="пересчитать подсветку изменений")
    p.set_defaults(func=cmd_detect_signals)

    p = sub.add_parser("purge-data", help="удалить все проекты, доступы и собранные данные")
    p.add_argument("--with-logs", action="store_true", help="очистить и журналы действий/изменений")
    p.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")
    p.set_defaults(func=cmd_purge_data)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Точка входа командной строки."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
