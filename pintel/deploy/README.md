# Развёртывание Pintel Server на VPS (Ubuntu)

Один сервер и база на все точки. Нужны Docker и Docker Compose
(`sudo apt install docker.io docker-compose-v2`).

```bash
git clone <репозиторий> pintel && cd pintel/pintel/deploy
cp .env.example .env && nano .env              # пароли, ключ Sickw, адрес
mkdir -p secrets && cp /путь/к/gservice.json secrets/gservice.json
docker compose up -d --build                   # база + приложение + ночные копии
docker compose exec app python -m pintel_server.cli create-admin --login admin --name "Руслан"
```

Касса: `http://<адрес-сервера>:8000` (или `https://<домен>`, если включить
Caddy: `docker compose --profile https up -d`, домен должен указывать на VPS).

Дальше в кассе под администратором: **Настройки → Добавить точку → Создать
киоск** (токен показывается один раз, вписать в `kiosk.toml` на киоске) →
**Обновить прайс**. **Сотрудники → Добавить**.

Обновление: `git pull && docker compose up -d --build` — миграции базы
применяются сами при старте (`alembic upgrade head`).

Резервные копии: папка `deploy/backups`, по одной в сутки, хранятся 30 дней.
Восстановить: `docker compose exec -T db pg_restore -U pintel -d pintel -c < backups/pintel_2026-10-23.dump`.

Разработка без Docker: `pip install -e ".[server]"`, `python -m pintel_server.cli create-admin …`,
`python -m pintel_server.cli run` (SQLite-файл `pintel.db` рядом).

## Демо на сервере 37.140.243.136 + pintelkz.com

> Для этого сервера рекомендую установку **на хост** (systemd + общий Postgres),
> а не Docker: тестовая база Оценки `pintel_ocenka_test` живёт в Postgres на хосте,
> и импорт сделок ходит туда по `127.0.0.1` без возни с сетью Docker.
> Пошагово: **[PINTELKZ.md](PINTELKZ.md)**. Ниже — вариант через Docker (для отдельного VPS).

Основной домен `pintelkz.com` уже занят рабочим сайтом, поэтому демо вешаем на
**поддомен** и отдельный HTTPS через Caddy — существующий сайт не трогается.

1. **DNS.** В панели домена добавить A-запись:
   `kiosk.pintelkz.com → 37.140.243.136`. Проверить: `dig +short kiosk.pintelkz.com`.
2. **На сервере** (под root, Docker уже есть):
   ```bash
   git clone <репозиторий> pintel && cd pintel/pintel/deploy
   cp .env.example .env && nano .env     # POSTGRES_PASSWORD, PINTEL_SECRET_KEY, ключ Sickw
   mkdir -p secrets && cp /путь/к/gservice.json secrets/gservice.json
   docker compose up -d --build
   docker compose --profile https up -d  # Caddy сам выпустит сертификат на kiosk.pintelkz.com
   docker compose exec app python -m pintel_server.cli create-admin --login admin --name "Руслан"
   ```
3. **Проверка QR.** Теперь `PINTEL_PUBLIC_URL=https://kiosk.pintelkz.com`, поэтому
   QR на отчёте ведёт на `https://kiosk.pintelkz.com/r/<код>` — открывается с
   телефона по мобильному интернету (раньше «грузилось и всё» из-за локального адреса).

> Если 80/443 на сервере уже заняты существующим сайтом (nginx/apache),
> Caddy не поднимется. Тогда не включаем профиль `https`, а в конфиге того
> веб-сервера добавляем проксирование `kiosk.pintelkz.com → 127.0.0.1:8000`.
> Скажи, что стоит на сервере (nginx/apache/ispmanager/панель), — дам точный конфиг.
