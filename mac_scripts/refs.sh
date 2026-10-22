#!/bin/bash
# Собирает справочник эталонов батарей из журнала приёмок.
# Смысл: diag.sh идёт 15 секунд и пишет отпечаток батареи в журнал. Прогнав
# витрину, получаешь эталоны для всех своих моделей — полный harvest.sh для
# этого не нужен. Скрипт печатает готовые строки для вставки в diag.sh.
# Запуск: bash ~/Downloads/refs.sh
python3 - <<'PY'
import json, os, collections, re
log = os.path.expanduser("~/Downloads/iphone_diag_log.jsonl")
diag = os.path.expanduser("~/Downloads/diag.sh")
if not os.path.exists(log):
    print("Журнала ещё нет. Прогони diag.sh хотя бы на одном телефоне.")
    raise SystemExit(0)

# Считаем НЕЗАВИСИМЫЕ аппараты по серийнику, а не число проверок: один телефон,
# прогнанный десять раз, подтверждением эталона не является.
seen = collections.defaultdict(lambda: collections.defaultdict(set))
names = {}
for line in open(log, encoding="utf-8"):
    try: d = json.loads(line)
    except Exception: continue
    m = d.get("модель")
    # Прогоны регрессии — не независимые аппараты, их в счёт не берём.
    if d.get("источник") not in (None, "приёмка"): continue
    b = d.get("батарея_эталон") or {}
    if not m or not b.get("ёмкость"): continue
    names[m] = d.get("название") or m
    fp = (b["ёмкость"], b["химия_hi"], b["алгоритм_hi"], b["код_детали"])
    seen[m][fp].add(d.get("серийник") or d.get("udid") or "?")

if not seen:
    print("В журнале пока нет записей с отпечатком батареи.")
    raise SystemExit(0)

have = set(re.findall(r'"(iPhone\d+,\d+)":\s*\(', open(diag, encoding="utf-8").read()))

MIN = 3   # столько независимых аппаратов должно совпасть, чтобы верить эталону
print("Моделей в журнале: %d" % len(seen))
print("Эталону верим от %d совпавших аппаратов: часть телефонов с витрины могла" % MIN)
print("уже побывать в ремонте, и эталон, снятый с одного, может оказаться")
print("отпечатком ПОДДЕЛКИ — тогда правило начнёт обвинять родные батареи.\n")
new, conflict, thin = [], [], []
for m in sorted(seen):
    variants = seen[m]
    devs = set().union(*variants.values())
    ranked = sorted(variants.items(), key=lambda kv: -len(kv[1]))
    best, best_devs = ranked[0]
    mark = "уже в diag.sh" if m in have else "НОВАЯ"
    print("  %-14s %-20s аппаратов %2d   %s" % (m, names[m][:20], len(devs), mark))
    if len(variants) > 1:
        # Отпечатки разошлись: меньшинство — подозрительные аппараты. Называем
        # их серийники, чтобы можно было взять эти телефоны и посмотреть руками.
        print("       ⚠️ отпечатки РАЗНЫЕ. Большинство задаёт норму, меньшинство —")
        print("          подозрительные аппараты. Проверь их физически:")
        for fp, ds in ranked:
            role = "большинство" if ds is best_devs else "ПОДОЗРИТЕЛЬНЫЕ"
            print("          %-14s (%s, 0x%X, 0x%X, %s)  аппараты: %s" % (
                role, fp[0], fp[1], fp[2], fp[3], ", ".join(sorted(ds))[:60]))
        if len(best_devs) < MIN or len(best_devs) <= len(devs) - len(best_devs):
            conflict.append(m)
            continue
        print("          → большинство %d из %d, беру его за норму" % (len(best_devs), len(devs)))
    if len(best_devs) < MIN:
        thin.append("%s (%d из %d)" % (m, len(best_devs), MIN))
        if m not in have:
            continue
    if m not in have or len(best_devs) >= MIN:
        new.append('    "%s": (%s, 0x%X, 0x%X, "%s", %d),' % (
            m, best[0], best[1], best[2], best[3], len(best_devs)))

if new:
    print("\nСтроки для BATT_REF в diag.sh (пятое число — на скольких аппаратах")
    print("эталон подтверждён; diag.sh не выносит вердикт, пока их меньше %d):" % MIN)
    for l in new: print(l)
if thin:
    print("\n  Эталон ещё тонкий, вердикт по батарее НЕ выносится: %s" % ", ".join(thin))
    print("  Прогони через diag.sh ещё телефоны этих моделей — счётчик вырастет сам.")
if not new and not thin:
    print("\nНовых моделей нет.")
if conflict:
    print("\nМодели с расхождением: %s" % ", ".join(conflict))
    print("Их в справочник не вносить, пока не ясно, где оригинал.")

# ---- номер модели -> заводской объём памяти ----
# Номер модели (MGJ53) лежит в syscfg НА ПЛАТЕ и однозначно задаёт заводской
# объём. При перепайке памяти 64->256 ГБ телефон честно рапортует НОВЫЙ объём
# во всех источниках, и сверка их согласия ничего не даёт — а номер модели
# остаётся прежним. Поэтому расхождение «один номер, разные объёмы» и есть
# признак апгрейда. Таблица копится с витрины: внешние списки номеров в
# открытом виде неполны, а свои данные полны по тем моделям, что реально идут.
# Снова считаем аппараты, а не строки журнала: перепаянный телефон, прогнанный
# пять раз, иначе выглядел бы убедительнее честного, прогнанного один раз.
caps = collections.defaultdict(lambda: collections.defaultdict(set))
for line in open(log, encoding="utf-8"):
    try: d = json.loads(line)
    except Exception: continue
    if d.get("источник") not in (None, "приёмка"): continue
    mn, gb, m = d.get("номер_модели"), d.get("объём_гб"), d.get("модель")
    if not mn or not gb: continue
    # MGJ53RM/A -> MGJ53. Номер модели у Apple РОВНО пять знаков, дальше код
    # региона (RM, LL, ZA, B, J...). Жадное {4,6} прихватывало первую букву
    # региона, и тогда один и тот же аппарат из США и из Казахстана попадал
    # в разные строки — детектор апгрейда так молчал бы.
    base = re.match(r"([A-Z0-9]{5})", str(mn))
    if base:
        caps[base.group(1)][(gb, d.get("название") or m or "?")].add(
            d.get("серийник") or d.get("udid") or "?")

if caps:
    print("\nНОМЕР МОДЕЛИ -> ЗАВОДСКОЙ ОБЪЁМ (с вашей витрины)")
    bad = []
    for mn in sorted(caps):
        vals = caps[mn]
        ranked = sorted(vals.items(), key=lambda kv: -len(kv[1]))
        (gb, mdl), devs = ranked[0]
        if len(vals) == 1:
            flag = "" if len(devs) >= MIN else "   ← аппаратов меньше %d, в diag.sh пока не вносить" % MIN
            print("  %-8s %-14s %4d ГБ   аппаратов %d%s" % (mn, mdl, gb, len(devs), flag))
        else:
            bad.append(mn)
            print("  %-8s ⛔ РАЗНЫЕ ОБЪЁМЫ ПОД ОДНИМ НОМЕРОМ:" % mn)
            for (g2, m2), ds in ranked:
                role = "большинство" if ds is devs else "ПОДОЗРИТЕЛЬНЫЕ"
                print("           %-14s %4d ГБ (%s)  аппараты: %s" % (
                    role, g2, m2, ", ".join(sorted(ds))[:50]))
    if bad:
        print("\n  ⛔ %s — у одного номера модели разные объёмы." % ", ".join(bad))
        print("  Либо где-то перепаяна память, либо номер прочитан неверно.")
        print("  Серийники подозрительных указаны выше — возьми эти телефоны и")
        print("  посмотри руками. Пока не разобрался, номер в MODEL_CAP не вносить.")
    else:
        print("\n  Противоречий нет: у каждого номера модели один объём.")
PY
