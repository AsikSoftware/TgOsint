#!/bin/bash
# Сверяет, что инструмент СКАЗАЛ, с тем, что про аппарат ИЗВЕСТНО.
# Работает только по записям, помеченным через diag.sh --ремонт "...".
# Три исхода по каждой детали:
#   ПОЙМАЛ   — ремонт известен, инструмент его показал. Правило работает.
#   ПРОПУСТИЛ — ремонт известен, инструмент промолчал. Правила не хватает.
#   ЛИШНЕЕ   — инструмент показал ремонт, которого в списке нет. Либо ложное
#              срабатывание, либо владелец не всё рассказал — разбирать руками.
# Запуск: bash ~/Downloads/calib.sh
python3 - <<'PY'
import json, os, re, collections
L = os.path.expanduser("~/Downloads/iphone_diag_log.jsonl")
if not os.path.exists(L):
    print("Журнала нет. Прогони diag.sh --ремонт \"что менялось\" на ремонтных аппаратах.")
    raise SystemExit(0)

# какие слова в описании ремонта к какой детали относятся
PART = {
    "Экран":            r"экран|дисплей|стекл|тачскрин|модул[ьи] экран",
    "Батарея":          r"батар|аккум|акб",
    "Основная камера":  r"основн\w* камер|задн\w* камер|широкоуг",
    "Сверхширокая":     r"сверхширок|ultrawide|ультраширок",
    "Телефото":         r"телефото|зум",
    "Фронтальная":      r"фронтал|селфи|передн\w* камер",
    "Face ID":          r"face\s*id|фейс|труднеп|truedepth|сканер лица",
    "Taptic Engine":    r"тапти|taptic|вибро|вибрац",
    "Память":           r"памят|nand|накопит|объ[её]м",
    "Плата":            r"плат|motherboard|мат\w*плат",
}
rows = []
for line in open(L, encoding="utf-8"):
    try: d = json.loads(line)
    except Exception: continue
    if d.get("источник") not in (None, "приёмка"): continue
    if not (d.get("известный_ремонт") or "").strip(): continue
    rows.append(d)

if not rows:
    print("В журнале нет аппаратов с пометкой ремонта.")
    print()
    print("Прогони каждый ремонтный телефон так, перечислив что менялось:")
    print('  bash ~/Downloads/diag.sh --ремонт "экран неоригинал, батарея менялась"')
    print()
    print("Без пометки ремонтный аппарат для калибровки бесполезен: по отсутствию")
    print("флага нельзя понять, промахнулось правило или сверки для этой детали нет.")
    raise SystemExit(0)

# берём последний прогон каждого аппарата
last = {}
for d in rows: last[d.get("серийник") or d.get("udid")] = d

print("Аппаратов с известным ремонтом: %d\n" % len(last))
score = collections.Counter()
detail = collections.defaultdict(collections.Counter)

for ser, d in sorted(last.items()):
    txt = (d["известный_ремонт"] or "").lower()
    known = {p for p, pat in PART.items() if re.search(pat, txt)}
    unmatched = not known
    flagged = {p for p, v in (d.get("детали") or {}).items()
               if v.startswith(("ЗАМЕН", "НЕОРИГ")) or v == "СБОИ"}
    # память и вскрытие приходят не через детали
    if any("перепаян" in s or "апгрейд" in s for s in (d.get("стоп") or [])):
        flagged.add("Память")
    if d.get("снимали_батарею"):
        flagged.add("Батарея")

    print("  %-14s %-14s  вердикт: %s" % (d.get("модель","?"), ser, d.get("вердикт","?")))
    print("       известно  : %s" % d["известный_ремонт"])
    if unmatched:
        print("       ⚠️ описание не распознано — ни одна деталь не узнана по словам")
    print("       распознано: %s" % (", ".join(sorted(known)) or "—"))
    print("       показал   : %s" % (", ".join(sorted(flagged)) or "ничего"))
    for p in sorted(known & flagged):
        score["ПОЙМАЛ"] += 1; detail[p]["ПОЙМАЛ"] += 1
    for p in sorted(known - flagged):
        score["ПРОПУСТИЛ"] += 1; detail[p]["ПРОПУСТИЛ"] += 1
        print("       ✗ ПРОПУСТИЛ: %s" % p)
    for p in sorted(flagged - known):
        score["ЛИШНЕЕ"] += 1; detail[p]["ЛИШНЕЕ"] += 1
        print("       ? ЛИШНЕЕ: %s — ложный флаг или владелец не всё сказал" % p)
    print()

print("ИТОГО по деталям")
for p in sorted(detail):
    c = detail[p]
    print("  %-18s поймал %d, пропустил %d, лишнее %d" % (
        p, c["ПОЙМАЛ"], c["ПРОПУСТИЛ"], c["ЛИШНЕЕ"]))
print()
print("ВСЕГО: поймал %d, пропустил %d, лишнее %d" % (
    score["ПОЙМАЛ"], score["ПРОПУСТИЛ"], score["ЛИШНЕЕ"]))
print()
print("Как читать: ПРОПУСТИЛ — там, где правила не хватает, это список задач.")
print("ЛИШНЕЕ — проверить руками: ложное срабатывание опаснее пропуска, потому")
print("что обвиняет честного клиента.")
PY
