/**
 * Подтверждение действий внутри приложения.
 *
 * Заменяет `window.confirm`: браузерные окна могут блокироваться и выглядят чужеродно.
 * Использование: `const confirm = useConfirm(); if (await confirm({...})) { ... }`.
 */
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';

import { Modal } from './ui';

export interface ConfirmOptions {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  /** Опасное действие: кнопка подтверждения выделяется красным. */
  danger?: boolean;
  /** Если задано, подтверждение доступно только после ввода этого текста. */
  requireText?: string;
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm | null>(null);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const [typed, setTyped] = useState('');
  const resolver = useRef<((value: boolean) => void) | null>(null);

  const confirm = useCallback<Confirm>((next) => {
    setTyped('');
    setOptions(next);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  const close = useCallback((result: boolean) => {
    resolver.current?.(result);
    resolver.current = null;
    setOptions(null);
  }, []);

  const blocked = !!options?.requireText && typed.trim() !== options.requireText;

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {options && (
        <Modal
          title={options.title}
          onClose={() => close(false)}
          footer={
            <>
              <button onClick={() => close(false)}>Отмена</button>
              <button
                className={options.danger ? 'primary danger-fill' : 'primary'}
                onClick={() => close(true)}
                disabled={blocked}
                autoFocus={!options.requireText}
              >
                {options.confirmLabel ?? 'Подтвердить'}
              </button>
            </>
          }
        >
          <div>{options.message}</div>
          {options.requireText && (
            <label className="field">
              <span>
                Для подтверждения введите <b>{options.requireText}</b>
              </span>
              <input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
            </label>
          )}
        </Modal>
      )}
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): Confirm {
  const confirm = useContext(ConfirmContext);
  if (!confirm) throw new Error('useConfirm вызван вне ConfirmProvider');
  return confirm;
}
