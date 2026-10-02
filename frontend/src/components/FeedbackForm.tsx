import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import { ErrorNotice } from './ui';

/** Форма внизу страниц: предложения и замечания команды уходят администратору. */
export function FeedbackForm() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState('');
  const send = useMutation({
    mutationFn: () => api.post('/feedback', { message: message.trim() }),
    onSuccess: () => {
      setMessage('');
      void queryClient.invalidateQueries({ queryKey: ['feedback'] });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    send.mutate();
  }

  return (
    <form className="feedback-form no-print" onSubmit={submit}>
      <div className="feedback-form-head">
        <b>Предложения по дашборду</b>
        <span className="small muted">Что улучшить, что неудобно, чего не хватает — обращение получит администратор.</span>
      </div>
      <textarea
        value={message}
        onChange={(e) => {
          setMessage(e.target.value);
          if (send.isSuccess) send.reset();
        }}
        rows={2}
        maxLength={5000}
        placeholder="Опишите идею или проблему"
      />
      <div className="row">
        <button type="submit" className="primary" disabled={message.trim().length < 3 || send.isPending}>
          {send.isPending ? 'Отправка…' : 'Отправить'}
        </button>
        {send.isSuccess && (
          <span className="feedback-sent" role="status">
            <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
              <circle cx="8" cy="8" r="8" fill="currentColor" />
              <path d="m4.5 8.2 2.3 2.3 4.7-4.9" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Спасибо! Обращение передано администратору.
          </span>
        )}
      </div>
      <ErrorNotice error={send.error} />
    </form>
  );
}
