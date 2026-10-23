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
