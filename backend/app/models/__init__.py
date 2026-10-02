"""ORM-модели. Импорт пакета регистрирует все таблицы в ``Base.metadata``."""

from app.models.config import (
    Account,
    Credential,
    Integration,
    IntegrationGoal,
    MonitoredUrl,
    Project,
    System,
)
from app.models.feedback import Feedback
from app.models.metrics import DailyMetric, MetricCatalog, PeriodMetric
from app.models.positions import Keyword, KeywordPosition
from app.models.signals import Annotation, AuditLog, Signal, SignalRule
from app.models.snapshots import CwvWeekly, PsiRun, SiteIssue, SitemapSnapshot
from app.models.sync import RawResponse, SyncRun
from app.models.team import ActivityLog, FavoriteProject, TeamMember

__all__ = [
    "Account",
    "ActivityLog",
    "Annotation",
    "AuditLog",
    "Credential",
    "CwvWeekly",
    "DailyMetric",
    "Feedback",
    "FavoriteProject",
    "Integration",
    "IntegrationGoal",
    "Keyword",
    "KeywordPosition",
    "MetricCatalog",
    "MonitoredUrl",
    "PeriodMetric",
    "Project",
    "PsiRun",
    "RawResponse",
    "SiteIssue",
    "Signal",
    "SignalRule",
    "SitemapSnapshot",
    "SyncRun",
    "System",
    "TeamMember",
]
