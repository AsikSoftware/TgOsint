#!/bin/bash
# Прогоняет логику diag.sh по ВСЕМ ранее собранным аппаратам, не требуя телефонов.
# Берёт сохранённые записи реестра из harvest.sh и подсовывает их скрипту.
# Смысл: любое изменение правил проверяется сразу на всей накопленной выборке,
# и ложное срабатывание видно до того, как попадёт в магазин.
# Запуск: bash ~/Downloads/regress.sh
set -u
BASE="$HOME/Downloads/iphone_harvest"
DIAG="$HOME/Downloads/diag.sh"
[ -f "$DIAG" ] || { echo "Не найден $DIAG"; exit 1; }

python3 - "$BASE" "$DIAG" <<'PY'
import os, sys, glob, json, re, shutil, tempfile, subprocess
base, diag = sys.argv[1], sys.argv[2]

# Вытаскиваем питоновскую часть diag.sh: её можно запустить на сохранённых
# данных, подменив каталог. Шелловская часть обращается к телефону и не нужна.
src = open(diag, encoding="utf-8").read()
m = re.search(r"JSON=\$JSON DIR=\"\$D\" UDID=\"\$U\" python3 <<'PY'\n(.*?)\nPY\n", src, re.S)
if not m:
    print("Не удалось выделить питоновскую часть diag.sh — формат скрипта изменился.")
    raise SystemExit(1)
body = m.group(1)

devices = sorted(d for d in glob.glob(base + "/*/") if os.path.isdir(d + "entries"))
if not devices:
    print("Нет собранных аппаратов. Сначала прогони harvest.sh.")
    raise SystemExit(0)

print("Прогон по %d собранным аппаратам\n" % len(devices))
problems = errors = 0
for dev in devices:
    udid = os.path.basename(dev.rstrip("/"))
    try:
        meta = json.load(open(dev + "inventory.json"))
    except Exception:
        meta = {}
    model = meta.get("_meta/ProductType", "?")
    ios   = meta.get("_meta/ProductVersion", "?")
    if meta.get("_meta/complete") == "no" or len(meta) < 20000:
        print("  %-14s %-8s сбор неполный, пропускаю" % (model, ios))
        continue

    tmp = tempfile.mkdtemp()
    # diag.sh ждёт файлы вида ИМЯ.xml и info.xml/disk.xml
    for p in glob.glob(dev + "entries/*.plist"):
        shutil.copy(p, os.path.join(tmp, os.path.basename(p).replace(".plist", ".xml")))
    for src_name, dst in (("_root", "info"), ("com.apple.disk_usage", "disk")):
        f = dev + "domains/%s.plist" % src_name
        if os.path.exists(f): shutil.copy(f, os.path.join(tmp, dst + ".xml"))

    # Помечаем прогон, чтобы он не выдавал себя за живую приёмку в журнале.
    env = dict(os.environ, JSON="1", DIR=tmp, UDID=udid, DIAG_SOURCE="регрессия")
    r = subprocess.run([sys.executable, "-c", body], capture_output=True, text=True, env=env)
    shutil.rmtree(tmp, ignore_errors=True)

    if r.returncode != 0:
        # Ошибка выполнения — это поломка скрипта, а не подозрение на замену.
        # Считать их вместе значит прятать баг за статистикой.
        print("  %-14s %-8s ОШИБКА: %s" % (model, ios, r.stderr.strip().split("\n")[-1][:70]))
        errors += 1
        continue
    try:
        out = json.loads(r.stdout)
    except Exception:
        print("  %-14s %-8s вывод не разобрался" % (model, ios))
        errors += 1
        continue

    pv = out.get("parts_verdict", {})
    bad = [l for l, v in pv.items() if v["verdict"].startswith(("ЗАМЕН", "НЕОРИГ")) or v["verdict"] == "СБОИ"]
    nd  = [l for l, v in pv.items() if v["verdict"] == "НЕТ ДАННЫХ"]
    ov  = out.get("overall", {}).get("verdict", "?")
    flag = "  ⚠️" if bad else ""
    print("  %-14s %-8s %-18s дет.%d  замен:%s  нет данных:%d%s" %
          (model, ios, ov, len(pv), ",".join(bad) if bad else "нет", len(nd), flag))
    if bad: problems += 1

print()
if errors:
    print("Скрипт упал на %d аппаратах — это поломка, чинить до всего остального." % errors)
if problems:
    print("Аппаратов с подозрением на замену: %d." % problems)
    print("Все собранные телефоны считались исправными — проверь, не ложное ли это срабатывание.")
elif not errors:
    print("Ни одного срабатывания на накопленной выборке.")
    print("ВНИМАНИЕ: это НЕ значит «ложных срабатываний нет». Неизвестно, были ли")
    print("эти телефоны в ремонте. Если были — отсутствие флага означает, что")
    print("правило ремонт ПРОПУСТИЛО. Выборка годится для поиска ложных флагов,")
    print("но доказать способность ловить ремонт может только заведомо ремонтный")
    print("аппарат в выборке.")
PY
