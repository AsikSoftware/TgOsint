#!/bin/bash
# Табло: насколько мои правила совпадают с вердиктом Apple.
# Считает по журналу ~/Downloads/iphone_check.jsonl, который пишет check.sh.
# Запуск: bash ~/Downloads/score.sh
python3 - <<'PY'
import json, os, collections
L = os.path.expanduser("~/Downloads/iphone_check.jsonl")
if not os.path.exists(L):
    print("Журнала нет. Прогони check.sh хотя бы на одном телефоне.")
    raise SystemExit(0)
by = collections.OrderedDict()
for line in open(L, encoding="utf-8"):
    try: r = json.loads(line)
    except Exception: continue
    by[r.get("серийник") or r.get("udid")] = r      # последний прогон аппарата

RU = {"Battery":"Аккумулятор","Display":"Экран","Camera":"Камера","FaceID":"Face ID",
      "MTUB":"Верхний модуль","LogicBoard":"Материнская плата","BackGlass":"Заднее стекло",
      "Enclosure":"Корпус","RearSystem":"Задняя система"}
MINE = {"Battery":["Батарея"],"Display":["Экран"],
        "Camera":["Основная камера","Сверхширокая","Телефото"],
        "FaceID":["Face ID"]}

stat = collections.defaultdict(collections.Counter)
noapple = []
for ser, r in by.items():
    ap = r.get("apple") or {}
    if not ap:
        noapple.append((ser, r.get("модель","?")))
        continue
    mine = r.get("мои_детали") or {}
    for comp, v in ap.items():
        labels = MINE.get(comp)
        if not labels:
            stat[comp]["нет проверки"] += 1
            if v["меняли"]: stat[comp]["нет проверки, а менян"] += 1
            continue
        vs = [mine[l] for l in labels if l in mine]
        flagged = any(x.startswith(("ЗАМЕН","НЕОРИГ")) or x in ("СБОИ","ПОД ВОПРОСОМ") for x in vs)
        if v["меняли"] and flagged:       stat[comp]["поймал"] += 1
        elif v["меняли"] and not flagged: stat[comp]["ПРОПУСТИЛ"] += 1
        elif not v["меняли"] and flagged: stat[comp]["ЛОЖНЫЙ ФЛАГ"] += 1
        else:                             stat[comp]["верно чисто"] += 1

print("Аппаратов с вердиктом Apple: %d" % (len(by) - len(noapple)))
if noapple:
    print("Без вердикта Apple (в раздел не зашли): %s" % ", ".join(s[:10] for s, _ in noapple))
print()
print("  %-18s %7s %10s %12s %12s" % ("узел","поймал","пропустил","ложный флаг","верно чисто"))
tot = collections.Counter()
for comp in sorted(stat, key=lambda c: -(stat[c]["поймал"]+stat[c]["ПРОПУСТИЛ"])):
    c = stat[comp]
    if "нет проверки" in c:
        bad = c["нет проверки, а менян"]
        print("  %-18s проверки нет (замен встречено: %d из %d)" % (
            RU.get(comp,comp), bad, c["нет проверки"]))
        continue
    print("  %-18s %7d %10d %12d %12d" % (
        RU.get(comp,comp), c["поймал"], c["ПРОПУСТИЛ"], c["ЛОЖНЫЙ ФЛАГ"], c["верно чисто"]))
    tot.update(c)
print()
print("ВСЕГО: поймал %d, пропустил %d, ложных флагов %d, верно чисто %d" % (
    tot["поймал"], tot["ПРОПУСТИЛ"], tot["ЛОЖНЫЙ ФЛАГ"], tot["верно чисто"]))
print()
print("Ложный флаг опаснее пропуска: он обвиняет честного клиента.")
print("Пропуск — список задач. «Проверки нет» — там кабель бессилен в принципе.")

# граница по батарее: где лежат родные, где заменённые
print()
print("ГРАНИЦА ПО БАТАРЕЕ (отношение к заводской ёмкости)")
pts = []
for ser, r in by.items():
    ap = r.get("apple") or {}
    b = r.get("батарея") or {}
    if not ap or "Battery" not in ap or not b.get("завод") or not b.get("ёмкость"): continue
    pts.append((b["ёмкость"]/b["завод"], ap["Battery"]["меняли"], r.get("модель","?"), ser))
if not pts:
    print("  данных пока нет — цифры батареи пишутся начиная с этой версии check.sh")
else:
    for ratio, rep, mdl, ser in sorted(pts):
        print("  %6.1f%%  %-14s %-12s %s" % (ratio*100, mdl, ser[:12],
              "ЗАМЕНЕНА (по Apple)" if rep else "родная"))
    gen = [p[0] for p in pts if not p[1]]
    rep = [p[0] for p in pts if p[1]]
    if gen and rep:
        print()
        print("  родные до %.1f%%, заменённые от %.1f%%" % (max(gen)*100, min(rep)*100))
        if max(gen) < min(rep):
            print("  разделение чистое — порог стоит между ними")
        else:
            print("  ⚠️ диапазоны ПЕРЕСЕКАЮТСЯ: одной ёмкости для вердикта мало")
PY
