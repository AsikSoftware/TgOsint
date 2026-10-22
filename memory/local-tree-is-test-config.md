---
name: local-tree-is-test-config
description: Локальные копии Pintel_Ocenka и PintelPay_2.0 — тестовая конфигурация; копировать их в боевое нельзя, боевой бот встанет
metadata:
  type: project
---

Тест и боевое различаются **кодом**, а не только .env. В локальных копиях
`/Users/pintel/Downloads/Pintel_Ocenka` и `PintelPay_2.0` зашито тестовое:
`token=settings.TOKEN_DEMO` вместо `TOKEN`, `ACTIVE_CHANNEL_ID = settings.CHANNEL_DEMO`,
закомментированы `daily_loop()`, `revision_daily_status_loop()` и
`load_phones_from_json()`, уровень логов INFO вместо WARNING.

**Why:** выкладка локального дерева в `/home/www/code/Pintel_ocenka` подняла бы боевой
бот на тестовом токене — боевой встал бы, а ночная выгрузка в Google Sheets и статус
ревизии замолчали бы. Плюс боевое ушло вперёд: в нём повторы и обход IPv6 для Sheets,
механика GWT-серийников (`moysklad_serial_numbers.py`, `moysklad_gwt_config.py`),
`tests/test_moysklad_gwt_signatures.py`, `imei_api/imei_info_old.py`, магазин
`"W": "Атырау"`, а в Pay `apply_current_deal_extra_fields.py` и та же литера W
(в локальной копии Pay W ошибочно = «Ербол Эльза АО»).

**How to apply:** на боевое выкладывать только пофайлово, взяв боевой код за основу.
Порядок, который сработал 12.10.2026: скачать боевое, сравнить с `diff -w` после
`tr -d '\r'` (боевое в CRLF, локальное в LF — иначе diff врёт на весь файл), разобрать
каждую теряющуюся строку, собрать дерево из боевого + свои файлы, прогнать тесты,
залить tar только нужных путей. Тогда вышло: Оценка 13 изменено / 11 добавлено /
0 удалено, Pay 2 файла. Бэкап: `/root/backup_prod_20261012-075011`.
См. [[supply-numbers-get-reused]].
