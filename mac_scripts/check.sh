#!/bin/bash
# ОДНА КОМАНДА НА ТЕЛЕФОН: кабельная проверка + вердикт Apple + их сравнение.
#   bash ~/Downloads/check.sh
# Вердикт Apple требует одного действия руками: зайти в раздел на телефоне.
# Скрипт сам скажет когда и подождёт.
export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH
set -u
D=/Users/pintel/Downloads
U=$(idevice_id -l 2>/dev/null | head -1)
[ -z "$U" ] && { echo "Телефон не подключён или не доверяет компьютеру."; exit 1; }

MY=$(mktemp /tmp/chk_my.XXXXXX); AP=$(mktemp /tmp/chk_ap.XXXXXX)
trap 'rm -f "${MY:?}" "${AP:?}"' EXIT

# ---------- 1. Кабельная проверка ----------
echo "[1/3] Кабельная проверка..."
bash "$D/diag.sh" --json > "$MY" 2>/dev/null
if ! grep -q '"udid"' "$MY" 2>/dev/null; then
  echo "      не получилось: $(head -c 200 "$MY")"
  exit 1
fi
python3 -c "
import json,sys
d=json.load(open('$MY'))
print('      %s  %s  iOS %s' % (d['model'], d['serial'], d['ios']))
print('      мой вердикт: %s' % d['overall']['verdict'])
"

# ---------- 2. Вердикт Apple ----------
echo
echo "[2/3] Теперь вердикт Apple. НА ТЕЛЕФОНЕ:"
echo "      Настройки → Основные → Об этом устройстве →"
echo "      ЗАЙДИ в «Запчасти и история обслуживания»"
echo "      (если экран уже открыт — выйди назад и зайди снова,"
echo "       Настройки кэшируют ответ и иначе ничего не поймается)"
echo
echo "      жду до 60 сек..."
( idevicesyslog -u "$U" 2>/dev/null | grep --line-buffered 'CRRepairHistoryItem' > "$AP" ) &
SYS=$!
for i in $(seq 1 60); do grep -q CRRepairHistoryItem "$AP" 2>/dev/null && break; sleep 1; done
sleep 2; kill -9 "$SYS" 2>/dev/null; wait "$SYS" 2>/dev/null

# ---------- 3. Сравнение ----------
echo
python3 - "$MY" "$AP" <<'PY'
import json, re, sys, os, datetime
my = json.load(open(sys.argv[1]))
raw = open(sys.argv[2], encoding="utf-8", errors="replace").read()

# Узлы, которые Apple перечисляет. Собрано с шести аппаратов. ВАЖНО: код 1029
# встречался и как MTUB, и как LogicBoard — значит опираться надо на имя,
# а не на код.
RU = {"Battery":"Аккумулятор","Display":"Экран","Camera":"Камера",
      "FaceID":"Face ID","MTUB":"Верхний модуль","LogicBoard":"Материнская плата",
      "BackGlass":"Заднее стекло","Enclosure":"Корпус","RearSystem":"Задняя система"}
# Что в моём отчёте соответствует узлу Apple. Камеру Apple считает одним узлом,
# у меня их три — беру худший из них. Для MTUB соответствия у меня нет.
# Заднее стекло, корпус и плату по кабелю проверить нечем: в заднем стекле
# электроники нет вовсе, поэтому замену Apple видит, а я нет. Это честное
# «проверки не существует», а не промах правила.
MINE = {"Battery":["Батарея"],"Display":["Экран"],
        "Camera":["Основная камера","Сверхширокая","Телефото"],
        "FaceID":["Face ID"],"MTUB":[],"LogicBoard":[],"BackGlass":[],
        "Enclosure":[],"RearSystem":[]}

apple = {}
for m in re.finditer(r"componentName:(\w+): componentType:(\d+): isRepaired:(\d): isUsed:(\d): repairDate:(.*?):\"?", raw):
    c,t,r,u,dt = m.groups()
    dt = re.sub(r"\\U([0-9a-fA-F]{4})", lambda g: chr(int(g.group(1),16)), dt.strip())
    if dt in ("(null)",""): dt = ""
    if apple.get(c,{}).get("дата") and not dt: continue
    apple[c] = {"меняли": r=="1", "б/у": u=="1", "дата": dt, "код": int(t)}

pv = my.get("parts_verdict", {})
def mine_says(comp):
    labels = MINE.get(comp, [])
    if not labels: return None
    vs = [pv[l]["verdict"] for l in labels if l in pv]
    if not vs: return None
    if any(v.startswith(("ЗАМЕН","НЕОРИГ")) or v=="СБОИ" for v in vs): return "менял"
    if any(v=="ПОД ВОПРОСОМ" for v in vs): return "под вопросом"
    if all(v in ("НЕТ В МОДЕЛИ","НЕТ ДАННЫХ") for v in vs): return None
    return "цел"

print("════════ APPLE против КАБЕЛЯ ════════")
agree = dis = nocheck = 0
if not apple:
    print("  Вердикт Apple не получен — в раздел не зашли, либо модель его не показывает.")
    print("  Кабельная часть всё равно записана в журнал.")
else:
    for c in sorted(apple, key=lambda x: apple[x]["код"]):
        a = apple[c]
        a_txt = ("МЕНЯЛИ" + (" (б/у)" if a["б/у"] else " (новая)")) if a["меняли"] else "цел"
        m_txt = mine_says(c)
        if m_txt is None:
            mark, note = "—", "у меня проверки нет"
            nocheck += 1
        elif (m_txt == "менял") == a["меняли"]:
            mark, note = "✅", "сошлось"; agree += 1
        else:
            mark, note = "⛔", ("ПРОПУСТИЛ" if a["меняли"] else "ЛОЖНЫЙ ФЛАГ")
            dis += 1
        print("  %s %-16s Apple: %-16s я: %-13s %s" % (
            mark, RU.get(c,c), a_txt, m_txt or "—", note))
        if a["дата"]: print("       дата ремонта: %s" % a["дата"])
    print()
    print("  сошлось %d, расхождений %d, без проверки %d" % (agree, dis, nocheck))

# ---------- запись ----------
try:
    log = os.path.expanduser("~/Downloads/iphone_check.jsonl")
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "время": datetime.datetime.now().isoformat(timespec="seconds"),
            "udid": my["udid"], "модель": my["product_type"], "название": my["model"],
            "серийник": my["serial"], "ios": my["ios"],
            "apple": apple, "мой_вердикт": my["overall"]["verdict"],
            "мои_детали": {k: v["verdict"] for k, v in pv.items()},
            # Цифры батареи — чтобы порог уточнялся по мере набора аппаратов
            "батарея": {"ёмкость": my["battery"].get("capacity_mah"),
                        "завод": my["battery"].get("design_mah"),
                        "износ": my["battery"].get("health_pct"),
                        "циклы": my["battery"].get("cycles")},
            "сошлось": agree, "расхождений": dis, "без_проверки": nocheck,
        }, ensure_ascii=False) + "\n")
    print()
    print("  Записано в ~/Downloads/iphone_check.jsonl")
except Exception as e:
    print("  (в журнал не записалось: %r)" % (e,))
PY
