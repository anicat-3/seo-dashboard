/** Плавная прокрутка, не зависящая от поддержки `behavior: 'smooth'` в браузере. */

const DURATION_MS = 650;

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

/**
 * Плавно прокрутить окно к позиции `top`.
 *
 * Если браузер не рисует кадры (вкладка в фоне), прокрутка всё равно завершается
 * по таймеру — страница не «застревает» на полпути.
 */
export function smoothScrollTo(top: number): void {
  const start = window.scrollY;
  const distance = top - start;
  if (Math.abs(distance) < 2) return;
  const startedAt = performance.now();
  let finished = false;

  const step = (now: number) => {
    if (finished) return;
    const progress = Math.min(1, (now - startedAt) / DURATION_MS);
    window.scrollTo(0, start + distance * easeInOutCubic(progress));
    if (progress < 1) requestAnimationFrame(step);
    else finished = true;
  };
  requestAnimationFrame(step);
  window.setTimeout(() => {
    if (!finished) {
      finished = true;
      window.scrollTo(0, top);
    }
  }, DURATION_MS + 250);
}
