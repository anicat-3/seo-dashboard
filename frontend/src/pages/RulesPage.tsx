import { RulesPanel } from '../components/RulesPanel';
import { PageHeader } from '../components/ui';

/** Общие правила подсветки изменений для всех проектов. */
export function RulesPage() {
  return (
    <>
      <PageHeader
        title="Правила подсветки"
        subtitle="Что считать резким изменением. Сигнал создаётся, когда метрика ухудшилась на порог и более к базе сравнения."
      />
      <div className="panel">
        <RulesPanel />
      </div>
      <p className="small muted">
        Свой порог для отдельного проекта задаётся в настройках проекта. Новые ошибки диагностики Вебмастера подсвечиваются всегда.
      </p>
    </>
  );
}
