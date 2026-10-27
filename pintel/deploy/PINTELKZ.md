# Демо Pintel на сервере 37.140.243.136 / kiosk.pintelkz.com (на хост, без Docker)

Почему на хост, а не в Docker: тестовая база Оценки `pintel_ocenka_test` живёт в
PostgreSQL **на самом сервере**, и нашему приложению проще всего ходить туда по
`127.0.0.1`. Ставим так же, как ваши боты — systemd + общий Postgres + nginx.
Боевое не трогаем: отдельный поддомен, отдельная база, отдельный сервис.

## 0. DNS
A-запись `kiosk.pintelkz.com → 37.140.243.136`. Проверка: `dig +short kiosk.pintelkz.com`.

## 1. Код и окружение
```bash
cd /home/www/code
git clone https://github.com/AsikSoftware/TgOsint pintel_src   # или git -C pintel_src pull
git -C pintel_src checkout claude/new-session-1hqkrp           # пока не влит в main
python3.13 -m venv /home/www/code/pintel_env
/home/www/code/pintel_env/bin/pip install -U pip
/home/www/code/pintel_env/bin/pip install -e "/home/www/code/pintel_src/pintel[server]"
```

## 2. Наша база (на том же Postgres, отдельная от Оценки)
```bash
sudo -u postgres psql -c "CREATE ROLE pintel_kiosk LOGIN PASSWORD 'ПРИДУМАЙ-ПАРОЛЬ';"
sudo -u postgres psql -c "CREATE DATABASE pintel_kiosk OWNER pintel_kiosk;"
```

## 3. Конфиг
```bash
mkdir -p /home/www/pintel_media
cp /home/www/code/pintel_src/pintel/deploy/.env.example /home/www/code/pintel.env
nano /home/www/code/pintel.env
```
Заполнить (POSTGRES_PASSWORD/DOMAIN из примера на хосте не нужны — они для Docker):
```
PINTEL_DATABASE_URL=postgresql+psycopg://pintel_kiosk:ПАРОЛЬ@127.0.0.1:5432/pintel_kiosk
PINTEL_SECRET_KEY=длинная-случайная-строка
PINTEL_PUBLIC_URL=https://kiosk.pintelkz.com
PINTEL_MEDIA_DIR=/home/www/pintel_media
PINTEL_SICKW_KEY=ВАШ-КЛЮЧ-SICKW
PINTEL_GSERVICE_JSON=/путь/к/gservice.json
PINTEL_PRICE_SHEET_URL=https://docs.google.com/spreadsheets/d/.../edit?gid=...
# --- импорт в тестовую Оценку (значения из .env Оценки) ---
PINTEL_OCENKA_DB_URL=postgresql+psycopg://<DB_USER>:<DB_PASS>@127.0.0.1:5432/pintel_ocenka_test
PINTEL_OCENKA_BOT_TOKEN=<TOKEN_DEMO>
PINTEL_OCENKA_MEDIA_CHAT=<CHANNEL_DEMO или id чата, где состоит тест-бот>
PINTEL_OCENKA_SHOP_LITERA=<литера демо-точки из таблицы shops>
```

## 4. Схема базы + администратор кассы
```bash
set -a; . /home/www/code/pintel.env; set +a
cd /home/www/code/pintel_src/pintel
/home/www/code/pintel_env/bin/alembic upgrade head
/home/www/code/pintel_env/bin/python -m pintel_server.cli create-admin --login admin --name "Руслан"
```

## 5. systemd — `/etc/systemd/system/pintel-kiosk.service`
```ini
[Unit]
Description=Pintel Kiosk Server
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/home/www/code/pintel_src/pintel
EnvironmentFile=/home/www/code/pintel.env
ExecStartPre=/home/www/code/pintel_env/bin/alembic upgrade head
ExecStart=/home/www/code/pintel_env/bin/uvicorn pintel_server.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=*
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
```bash
systemctl daemon-reload && systemctl enable --now pintel-kiosk
systemctl status pintel-kiosk --no-pager
```

## 6. nginx + HTTPS (nginx уже стоит для barcode-scan)
`/etc/nginx/sites-available/kiosk.pintelkz.com`:
```nginx
server {
    server_name kiosk.pintelkz.com;
    client_max_body_size 80M;                 # фото и видео клиента
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
```
```bash
ln -s /etc/nginx/sites-available/kiosk.pintelkz.com /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d kiosk.pintelkz.com        # выпустит сертификат
```

## 7. Запуск демо
1. `https://kiosk.pintelkz.com/healthz` → `{"ok":true}`.
2. Касса: войти → **Настройки → Добавить точку → Создать киоск** (токен показывается один раз).
   Там же **Обновить прайс**. На киоске в `kiosk.toml`: `server=https://kiosk.pintelkz.com`, `token=…`.
3. Прогнать телефон на киоске → на экране результат проверки и QR на отчёт (номера пока нет),
   клиент подходит к сотруднику. Клиент сам ничего не вводит.
4. В кассе карточка сделки: сотрудник записывает **имя и телефон клиента**, коробку/шнур →
   сервер **выдаёт номер заявки**, киоск тут же показывает его клиенту. Фото и видео телефона
   сотрудник **загружает с компьютера** или **снимает на свой телефон по QR** с карточки
   (временная ссылка `/m/<код>`). Затем ставит panic при необходимости, **выбирает себя из списка
   оценщиков** (тянется из `pintel_ocenka_test.users`), называет цену и жмёт **«Отправить в Оценку»**
   → в тестовой Оценке появляется сделка «Ожидает оценку».

## Предпосылки для импорта в Оценку
- Тестовый бот Оценки должен работать против `pintel_ocenka_test` на токене `TOKEN_DEMO`
  — тогда `file_id` фото/видео, полученные нами через этот же токен, валидны для него.
- Бот обязан состоять в чате `PINTEL_OCENKA_MEDIA_CHAT` (туда он отправляет медиа, оттуда берётся `file_id`).
- Роль из `PINTEL_OCENKA_DB_URL` должна иметь доступ к `pintel_ocenka_test`.
- Обновление кода демо: `git -C /home/www/code/pintel_src pull && systemctl restart pintel-kiosk`
  (миграции применяются сами при старте).
```
