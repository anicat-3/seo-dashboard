# Развёртывание на сервере

На сервере создаётся новая пустая база: проекты, подключения и история заводятся
заново. Файл `.env` переносится как есть — в нём уже есть ключи шифрования и
OAuth-приложений Google и Яндекса.

## Установка

1. **Сервер.** PostgreSQL 17, Python 3.12, Node.js 20+.
2. **Код.** Склонировать репозиторий, например в `/opt/seo-dashboard`.
3. **`.env`.** Скопировать файл в корень репозитория. Для работы по домену поменять
   две строки:
   ```dotenv
   PUBLIC_BASE_URL=https://seo.example.com   # из него строится адрес возврата Google
   SESSION_COOKIE_SECURE=true                # cookie входа только по HTTPS
   ```
   `DATABASE_URL` менять не нужно, если на шаге 4 задать пользователю БД пароль из этой
   строки (`postgresql+psycopg://seo_dashboard:<пароль>@localhost:5432/seo_dashboard`).
4. **База.** Создать пользователя и пустую базу (от имени `postgres`):
   ```sql
   CREATE ROLE seo_dashboard LOGIN PASSWORD '<пароль из DATABASE_URL>';
   CREATE DATABASE seo_dashboard OWNER seo_dashboard ENCODING 'UTF8';
   ```
   `scripts\setup.ps1` этот шаг пропускает, если `.env` уже существует, поэтому
   базу создают вручную.
5. **Схема, справочники, учётные записи, сборка.**
   ```bash
   cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e .
   .venv/bin/python -m alembic upgrade head   # все таблицы, индексы и ограничения
   .venv/bin/python -m app.cli setup          # справочники, правила подсветки, admin и seo
   cd ../frontend && npm ci && npm run build
   ```
   `setup` спросит пароли учётных записей `admin` и `seo`. На Windows Server то же
   самое делает `.\scripts\setup.ps1` (после шага 4).
6. **Служба.** Приложение должно работать круглосуточно и **в одном процессе**
   (планировщик сбора внутри). Пример unit-файла systemd:
   ```ini
   [Unit]
   Description=SEO dashboard
   After=network.target postgresql.service

   [Service]
   User=seo
   WorkingDirectory=/opt/seo-dashboard/backend
   ExecStart=/opt/seo-dashboard/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
   На Windows Server — запуск `scripts\run.ps1` через Планировщик заданий
   («При запуске системы») или NSSM.
7. **HTTPS.** Перед приложением — обратный прокси (nginx или Caddy) с TLS-сертификатом,
   проксирующий на `127.0.0.1:8000`.
8. **Google OAuth.** В OAuth-приложении `GOOGLE_CLIENT_ID_1` добавить адрес возврата
   `https://<домен>/api/oauth/google/callback`. Приложение должно быть с типом
   **External** и в статусе **In production** — иначе войти смогут только тестовые
   пользователи. У Яндекса ничего менять не нужно.
9. **Проверка.**
   - `https://<домен>/api/health` отвечает `{"status": "ok", …}`;
   - с сервера открываются API сервисов, особенно `curl -I https://api.topvisor.com`
     (Topvisor бывает недоступен из-за DNS или блокировок).

## Первая настройка

Порядок — в [admin-guide.md](admin-guide.md), раздел «Первый запуск»: команда,
подключения, проекты. Все аккаунты Google и Яндекса подключаются заново через
кнопки «Войти через …» — новые входы идут через приложения `_1`; ключи `_2`, `_3`…
в `.env` новой базе не нужны, но и не мешают.

При подключении системы к проекту история загружается сама: GSC и GA4 — около
16 месяцев, Bing — полгода, Метрика и Вебмастер — сколько отдаёт API, Topvisor и
SE Ranking — за выбранный период. Снимки карт сайта, ошибки диагностики и прогоны
PageSpeed Insights начнут копиться с первого ночного сбора.

## Резервное копирование

Копия базы — `pg_dump` в формате custom. На Windows это делает `scripts\backup.ps1`
(копии старше 30 дней удаляются):

```powershell
.\scripts\backup.ps1 -OutDir "D:\Backups\seo-dashboard"
```

На Linux — ежедневная задача cron:

```bash
pg_dump -Fc -U seo_dashboard seo_dashboard > /var/backups/seo-dashboard/$(date +%F).dump
```

Отдельно храните `.env` (например, в менеджере паролей): без `ENCRYPTION_KEY` из
копии базы не восстановить сохранённые доступы.

## Обновление версии

```bash
git pull
cd backend && .venv/bin/pip install -e . && .venv/bin/python -m alembic upgrade head
cd ../frontend && npm ci && npm run build
# перезапустить службу
```

На Windows — те же команды с `.\.venv\Scripts\python -m …`.

## Если PostgreSQL нельзя установить с правами администратора

Подойдёт архив с бинарными файлами без установки: распаковать, выполнить
`initdb -D <папка данных> -U postgres -W -E UTF8`, запускать командой
`pg_ctl -D <папка данных> start`. Папку данных нельзя размещать в синхронизируемых
каталогах (Google Диск, OneDrive).
