/**
 * Сохранение отчёта в PDF через печать браузера («Сохранить как PDF»).
 *
 * Перед печатью страница переводится в «режим печати»: светлая тема, ширина листа A4,
 * без боковой панели и элементов управления. Графики успевают перестроиться под
 * новую ширину, после чего открывается диалог печати. Заголовок вкладки на это
 * время заменяется — браузер подставляет его как имя PDF-файла.
 */
import { forceTheme } from './theme';

/** Время на перестройку графиков под ширину листа. */
const LAYOUT_SETTLE_MS = 700;

export async function printReport(fileName: string): Promise<void> {
  const root = document.documentElement;
  const previousTitle = document.title;

  const restore = () => {
    root.classList.remove('print-mode');
    forceTheme(null);
    document.title = previousTitle;
    window.removeEventListener('afterprint', restore);
  };

  root.classList.add('print-mode');
  forceTheme('light');
  document.title = fileName;
  window.scrollTo({ top: 0 });
  await new Promise((resolve) => setTimeout(resolve, LAYOUT_SETTLE_MS));

  window.addEventListener('afterprint', restore);
  window.print();
}
