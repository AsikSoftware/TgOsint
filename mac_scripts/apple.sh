#!/bin/bash
# ВЕРДИКТ APPLE по запчастям — тот самый экран «Запчасти и история обслуживания».
#
# Как это работает. Сам вердикт по USB не отдаётся: ни lockdown-домены (перебрано
# около 77), ни IORegistry (перечислено 868-959 узлов на семи аппаратах) его не
# содержат. Но считает его демон mobilerepaird, и он ПИШЕТ РЕЗУЛЬТАТ В ЖУРНАЛ,
# а журнал по кабелю читается. Демон просыпается, когда на телефоне открывают
# тот экран. Поэтому один шаг руками неизбежен — зато ответ Apple полный:
# по каждой детали «меняли или нет» и «деталь новая или б/у».
#
# Запуск: bash ~/Downloads/apple.sh
export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH
set -u
U=$(idevice_id -l 2>/dev/null | head -1)
if [ -z "$U" ]; then
  echo "Телефон не подключён или не доверяет компьютеру."
  exit 1
fi
PT=$(ideviceinfo -u "$U" -k ProductType 2>/dev/null)
NAME=$(ideviceinfo -u "$U" -k ProductName 2>/dev/null)
SER=$(ideviceinfo -u "$U" -k SerialNumber 2>/dev/null)
RAW=$(mktemp /tmp/applerepair.XXXXXX)

echo "Аппарат: $PT  $SER"
echo
echo "СЕЙЧАС НА ТЕЛЕФОНЕ:"
echo "   Настройки → Основные → Об этом устройстве"
echo "   прокрути вниз и ЗАЙДИ в «Запчасти и история обслуживания»"
echo
echo "   Важно: нужен именно ПЕРЕХОД внутрь раздела. Если экран уже открыт,"
echo "   нажми «Назад» и зайди снова — Настройки кэшируют ответ и повторно"
echo "   демона не дёргают, поэтому на открытом экране ничего не поймается."
echo
echo "Жду до 60 секунд..."

# Фильтруем прямо на входе: за 45 секунд журнал даёт больше 300 тысяч строк,
# целиком его держать незачем.
( idevicesyslog -u "$U" 2>/dev/null | grep --line-buffered -E 'CRRepairHistoryItem|CoreRepair' > "$RAW" ) &
SYS=$!
# Ждём появления записей, но не дольше минуты.
for i in $(seq 1 60); do
  grep -q 'CRRepairHistoryItem' "$RAW" 2>/dev/null && break
  sleep 1
done
sleep 2
kill -9 "$SYS" 2>/dev/null; wait "$SYS" 2>/dev/null

if ! grep -q 'CRRepairHistoryItem' "$RAW" 2>/dev/null; then
  echo
  echo "Вердикт не появился. Возможные причины:"
  echo "  • экран так и не открыли — демон просыпается только от него;"
  echo "  • на этой модели раздела «Запчасти и история обслуживания» нет"
  echo "    (Apple показывает его начиная с iPhone 12 и не на всех моделях);"
  echo "  • телефон заблокировался во время ожидания."
  echo "Файл журнала оставлен для разбора: $RAW"
  exit 2
fi

python3 - "$RAW" "$U" "$PT" "$SER" "$NAME" <<'PY'
import re, sys, json, os, datetime
raw, udid, pt, ser, name = sys.argv[1:6]
txt = open(raw, encoding="utf-8", errors="replace").read()

RU = {"Battery": "Аккумулятор", "Display": "Экран", "Camera": "Камера",
      "FaceID": "Face ID", "MTUB": "Верхний модуль (динамик/датчики)",
      "RearSystem": "Задняя система", "Housing": "Корпус"}

items = {}
for m in re.finditer(
        r"componentName:(\w+): componentType:(\d+): isRepaired:(\d): isUsed:(\d): repairDate:(.*?):\"?", txt):
    comp, ctype, rep, used, date = m.groups()
    date = date.strip()
    # Даты в журнале приходят в \U-экранировании, раскрываем
    date = re.sub(r"\\U([0-9a-fA-F]{4})", lambda g: chr(int(g.group(1), 16)), date)
    if date in ("(null)", ""): date = ""
    prev = items.get(comp)
    # Из нескольких записей берём самую содержательную (с датой)
    if prev and prev["дата"] and not date: continue
    items[comp] = {"деталь": RU.get(comp, comp), "код": int(ctype),
                   "меняли": rep == "1", "б/у": used == "1", "дата": date}

print()
print("════════ ВЕРДИКТ APPLE ════════")
if not items:
    print("  записи есть, но разобрать не удалось")
    raise SystemExit(2)
bad = [v for v in items.values() if v["меняли"]]
for comp in sorted(items, key=lambda c: items[c]["код"]):
    v = items[comp]
    if v["меняли"]:
        tail = " — поставлена Б/У деталь" if v["б/у"] else " — деталь новая"
        when = f", {v['дата']}" if v["дата"] else ""
        print(f'  ⛔ {v["деталь"]:32}: МЕНЯЛИ{tail}{when}')
    else:
        print(f'  ✅ {v["деталь"]:32}: не меняли')
print()
if bad:
    used = [v["деталь"] for v in bad if v["б/у"]]
    print("  ИТОГ: аппарат РЕМОНТИРОВАН — %s" % ", ".join(v["деталь"].lower() for v in bad))
    if used:
        print("        и поставлены б/у детали: %s" % ", ".join(u.lower() for u in used))
    print("        Это вердикт самой Apple, а не вывод по косвенным признакам.")
else:
    print("  ИТОГ: по данным Apple ни одна деталь не менялась.")
    print("        Apple отслеживает только эти узлы: остальное её вердикт не покрывает.")

# В журнал приёмок — рядом с результатами кабельной проверки
try:
    log = os.path.expanduser("~/Downloads/iphone_apple_repair.jsonl")
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "время": datetime.datetime.now().isoformat(timespec="seconds"),
            "udid": udid, "модель": pt, "серийник": ser,
            "детали": items,
            "ремонтирован": bool(bad),
        }, ensure_ascii=False) + "\n")
    print()
    print("  Записано в ~/Downloads/iphone_apple_repair.jsonl")
except Exception:
    pass
PY
rm -f "${RAW:?}"
