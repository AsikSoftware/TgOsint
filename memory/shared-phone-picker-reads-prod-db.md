---
name: shared-phone-picker-reads-prod-db
description: Веб-пикер модели телефона общий для тестового и боевого бота Оценки и читает боевую БД
metadata:
  type: project
---

Выбор модели в Оценке — это Telegram WebApp по жёстко прописанному адресу
`https://barcode-scan.duckdns.org/apps/phone_picker.html` (keyboards/keyboards.py).
Список моделей ему отдаёт systemd-сервис `imei_api.service` (uvicorn, 127.0.0.1:8001)
с `WorkingDirectory=/home/www/code/Pintel_ocenka`, то есть он читает **боевую** БД
`pintel_ocenka`. Адрес один и тот же для тестового и боевого бота.

**Why:** добавление моделей только в тестовую БД `pintel_ocenka_test` в тестовом боте
не видно — пикер всё равно показывает боевой справочник. Это легко принять за баг кода.

**How to apply:** чтобы новая модель появилась хоть где-то, строки нужны в боевой
`pintel_ocenka.phones` + `phone_codenames` — а это запись в боевую БД, которую владелец
просил не делать без спроса. 11.10.2026 он разрешил добавить туда 18 серию iPhone и
Note 15 5G / Pro+ 5G (вставлено +7 строк, TAC не трогали, бэкап в
/root/backup_phones_20261011-053205/phones.sql). Альтернатива — отдельный
`imei_api` на тестовой БД со своим адресом. См. [[test-bots-on-server]].
