# ASGARD — сайт личного кабинета

Flask + SQLite. Регистрация/вход, личный кабинет, привязка HWID (лимит 3), страница скачивания.

## Локальный запуск

```
start.bat        # или: python -m pip install -r requirements.txt && python app.py
```

Сайт будет на http://127.0.0.1:5000

## Файлы

- `app.py` — приложение (Flask), БД `asgard.db` создаётся автоматически
- `wsgi.py` — точка входа для gunicorn / PythonAnywhere
- `Procfile` — для Render
- `templates/`, `static/style.css` — вёрстка (тёмная тема)
- `.secret_key` — секретный ключ сессий (генерируется сам при первом запуске)

Ссылки на клиент — в начале `app.py`:
`CLIENT_JAR_URL` (jar на Google Drive) и `LOADER_ZIP_URL` (лоадер, опционально).

---

## Деплой: вариант 1 — PythonAnywhere (просто)

Бесплатный поддомен вида `ник.pythonanywhere.com`.
**Внимание:** кастомный домен (`*.eu.org`) на бесплатном тарифе PythonAnywhere НЕ поддерживается — только на платном (Hacker, $5/мес). Если хочешь именно свой домен бесплатно — см. вариант 2.

1. Зарегистрируйся на pythonanywhere.com.
2. Bash-консоль: `git clone <твой-репозиторий>` или загрузи файлы через Files.
3. `pip install --user -r requirements.txt`
4. Web → Add a new web app → Manual configuration → Python 3.10+.
5. WSGI: впиши путь к папке проекта и `from wsgi import application`.
6. Reload.

## Деплой: вариант 2 — Render (своё имя домена бесплатно)

Бесплатный сервис с кастомным доменом и TLS.
**Внимание:** на бесплатном тарифе Render диск «эфимерный» — данные SQLite сохраняются между «засыпаниями», но сбрасываются при повторном деплое. Для боевого использования лучше перенести БД во внешнюю (Supabase/Turso) — могу помочь.

1. Заливай проект в GitHub-репозиторий.
2. На render.com: New → Web Service → укажи репозиторий.
3. Build command: `pip install -r requirements.txt`
4. Start command: уже в `Procfile` (gunicorn). Render сам даёт `$PORT`.
5. После деплоя: Settings → Domains → добавь `asgardclientdlc.eu.org` (Render сам выпустит SSL-сертификат).

## DNS в desec.io (после одобрения домена eu.org)

В зоне `asgardclientdlc.eu.org` на desec.io добавь:

| Тип | Имя | Значение |
|-----|-----|----------|
| A   | @   | <IP хоста> |

- PythonAnywhere: IP из вкладки Web (для платного кастомного домена).
- Render: IP из Settings → Domains (после добавления домена), либо CNAME на `*.onrender.com`-адрес.

И убедись, что в eu.org у домена указаны NS: `ns1.desec.io`, `ns2.desec.org` (и др. если есть).

## Настройки в админке/клиенте

- Ник в игре по умолчанию: `Asgard`.
- Jar раздаётся с Google Drive по ссылке в `CLIENT_JAR_URL`.