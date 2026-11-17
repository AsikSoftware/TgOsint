#!/bin/bash
# БОЕВАЯ база Оценки: в сделках с кассы заменить заводской код Apple («iPhone15,2») в
# devices.code_name на номер модели («A2890») — из справочника самой Оценки, по началу IMEI
# сделки (phone_tac -> phone_codenames), тем же путём, каким его получает сделка из бота.
#
# Меняется одна колонка у сделок, где сейчас лежит заводской код (17.11.2026 — 26 сделок с
# кассы). Строки не удаляются и не добавляются, бот не перезапускается. Чего справочник не
# знает (новая модель) — поле очищается: пусто честнее заводского кода, так же пусто у бота.
# Запускать можно повторно: второй раз править будет нечего.
# Запускает владелец. Вернуть как было — по файлу прежних значений, путь скрипт напечатает.
set -e
# База по умолчанию боевая; для пробы на тестовой: ispravit_code_name.sh pintel_ocenka_test
BASE=${1:-pintel_ocenka}
case "$BASE" in pintel_ocenka|pintel_ocenka_test) ;; *) echo "не та база: $BASE"; exit 1;; esac
STAMP=$(date +%F_%H%M)
DUMP=/root/${BASE}_devices_$STAMP.dump
BYLO=/root/code_name_bylo_$STAMP.csv
sudo -u postgres pg_dump -Fc -t devices "$BASE" > "$DUMP"
sudo -u postgres psql -d "$BASE" -At -F ';' -c \
  "SELECT id, code_name FROM devices WHERE code_name ~ '^iPhone[0-9]+,[0-9]+\$' ORDER BY id" > "$BYLO"
echo "копия таблицы devices: $DUMP"
echo "прежние значения: $BYLO — строк: $(wc -l < "$BYLO")"
sudo -u postgres psql -d "$BASE" -v ON_ERROR_STOP=1 -At -F ' | ' <<'SQL'
BEGIN;
\echo == сделок с заводским кодом до правки
SELECT count(*) FROM devices WHERE code_name ~ '^iPhone[0-9]+,[0-9]+$';
DO $proverka$
BEGIN
  IF (SELECT count(*) FROM devices WHERE code_name ~ '^iPhone[0-9]+,[0-9]+$') > 300 THEN
    RAISE EXCEPTION 'строк больше 300 — это не похоже на сделки с кассы, ничего не меняю';
  END IF;
END
$proverka$;
WITH novoe AS (
  SELECT d.id,
         (SELECT c.code_name FROM device_imeis i
          JOIN phone_tac t ON t.tac = left(i.imei, 8)
          JOIN phone_codenames c ON c.id = t.code_name_id
          WHERE i.device_id = d.id ORDER BY i.first DESC NULLS LAST LIMIT 1) AS nomer
  FROM devices d WHERE d.code_name ~ '^iPhone[0-9]+,[0-9]+$')
UPDATE devices d SET code_name = novoe.nomer FROM novoe WHERE d.id = novoe.id;
\echo == осталось с заводским кодом после правки
SELECT count(*) FROM devices WHERE code_name ~ '^iPhone[0-9]+,[0-9]+$';
\echo == сделки с кассы теперь: модель | code_name | сколько
SELECT model, coalesce(code_name, '(пусто)'), count(*) FROM devices
WHERE comment_ocenka LIKE '%Киоск %' GROUP BY 1, 2 ORDER BY 3 DESC, 1;
COMMIT;
SQL
echo "готово. Вернуть как было: строки файла $BYLO — это «id;прежний code_name»"
