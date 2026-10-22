#!/bin/bash
# Сравнивает описи всех собранных аппаратов и делит ключи на две кучи:
#   ПОСТОЯННЫЕ - значение одинаково у всех. Для вердикта бесполезны: такое
#                правило сработает либо у всех, либо ни у кого.
#   РАЗЛИЧАЮТСЯ - значение отличается. Только здесь живут настоящие сигналы.
# Чем больше аппаратов собрано, тем точнее деление. Минимум - два.
python3 - "$HOME/Downloads/iphone_harvest" <<'PY'
import json, os, sys, collections
base = sys.argv[1]
devs = {}
for d in sorted(os.listdir(base)):
    f = os.path.join(base, d, "inventory.json")
    if os.path.isfile(f):
        try: devs[d] = json.load(open(f))
        except Exception: pass
# Оборванный сбор нельзя сравнивать с полным: его отсутствующие ключи
# выглядели бы как «зависит от модели», хотя на деле их просто не успели снять.
if devs:
    # Полнота определяется отметкой самого харвестера, а не объёмом описи:
    # оборванный сбор может быть большим и всё равно негодным для сравнения.
    # У описей, снятых до появления отметки, смотрим на долю отвеченных имён.
    def incomplete(v):
        m = v.get("_meta/complete")
        if m is not None: return m != "yes"
        a, g = v.get("_meta/asked"), v.get("_meta/answered")
        if a and g: return g < a * 0.5
        return len(v) < 40000
    skipped = {d: len(v) for d, v in devs.items() if incomplete(v)}
    for d in skipped: del devs[d]
    if skipped:
        print("Пропущены незавершённые сборы — телефон отключили до конца опроса:")
        for d, n in skipped.items(): print("  %s — собрано %d значений, пересними этот аппарат" % (d, n))
        print()

if len(devs) < 2:
    print("Собран %d аппарат. Для сравнения нужно минимум два:" % len(devs))
    print("подключи следующий телефон и запусти harvest.sh ещё раз.")
    raise SystemExit(0)

print("Аппаратов в сравнении: %d" % len(devs))
for d, v in devs.items():
    print("  %s  (%d значений)" % (d, len(v)))

allk = set()
for v in devs.values(): allk |= set(v)
const, vary, partial = [], [], []
for k in sorted(allk):
    present = [d for d in devs if k in devs[d]]
    if len(present) < len(devs):
        partial.append((k, len(present))); continue
    vals = {str(devs[d][k]) for d in devs}
    (const if len(vals) == 1 else vary).append(k)

print()
print("ПОСТОЯННЫЕ (есть у всех, значение одно)    : %d" % len(const))
print("РАЗЛИЧАЮТСЯ (есть у всех, значения разные) : %d  <- здесь сигналы" % len(vary))
print("ЕСТЬ НЕ ВЕЗДЕ (зависят от модели/прошивки) : %d" % len(partial))

out = os.path.join(base, "_compare")
os.makedirs(out, exist_ok=True)
with open(out+"/constant.txt","w") as f:
    for k in const: f.write("%s = %s\n" % (k, list(devs.values())[0][k]))
with open(out+"/varying.txt","w") as f:
    for k in vary:
        f.write("%s\n" % k)
        for d in devs: f.write("    %s = %s\n" % (d[:8], devs[d][k]))
with open(out+"/partial.txt","w") as f:
    for k, n in partial: f.write("%s  (есть у %d из %d)\n" % (k, n, len(devs)))

# ---- накопительный справочник заводских констант по моделям ----
# Заводская ёмкость батареи, объём памяти и состав камер у конкретной модели
# одинаковы на всех экземплярах. Накопив их с реальных аппаратов, получаем
# эталон, с которым можно сверять: неоригинальная батарея обычно рапортует
# другую DesignCapacity. Справочник растёт сам по мере сбора новых телефонов,
# и строится он на НАБЛЮДАЕМЫХ значениях, а не на цифрах из рекламы Apple
# (у iPhone 12 Apple пишет 2815 мА·ч, аппараты отдают 2798).
# Второе поле: одинаково ли значение у ВСЕХ экземпляров модели.
# Батарея — да, одна на модель. Память — нет, модель выпускается в разных
# объёмах, и разные значения здесь норма, а не повод «разобраться».
REF = {
    "Ёмкость батареи": ("AppleSmartBattery/IORegistry/BatteryData/DesignCapacity", True),
    "Объём памяти":    ("DOMAIN:com.apple.disk_usage/TotalDiskCapacity", False),
    "Модель чипа NAND":("AppleANS3NVMeController/IORegistry/Model Number", False),
}
# Отпечаток батареи: эти поля постоянны внутри модели и различны между
# моделями, поэтому по ним ловится неоригинальный пак и пак от чужой модели.
# У ChemID модельно-постоянна только СТАРШАЯ половина — младшая привязана
# к экземпляру, сравнивать целиком нельзя.
# Код детали сидит в серийнике пака на позициях 11..13.
DERIVED = {
    "Химия ячейки hi": lambda v: (
        "0x%04X" % (int(v["AppleSmartBattery/IORegistry/BatteryData/ChemID"]) >> 16)
        if "AppleSmartBattery/IORegistry/BatteryData/ChemID" in v else None),
    "Алгоритм химии hi": lambda v: (
        "0x%04X" % (int(v["AppleSmartBattery/IORegistry/BatteryData/AlgoChemID"]) >> 16)
        if "AppleSmartBattery/IORegistry/BatteryData/AlgoChemID" in v else None),
    "Код детали пака": lambda v: (
        str(v["AppleSmartBattery/IORegistry/BatteryData/Serial"])[11:14]
        if len(str(v.get("AppleSmartBattery/IORegistry/BatteryData/Serial",""))) >= 14 else None),
}
ref = {}
for d, v in devs.items():
    model = str(v.get("_meta/ProductType", "?"))
    for name, (key, _) in REF.items():
        if key in v:
            ref.setdefault(model, {}).setdefault(name, set()).add(str(v[key]))
    for name, fn in DERIVED.items():
        try: val = fn(v)
        except Exception: val = None
        if val: ref.setdefault(model, {}).setdefault(name, set()).add(val)
if ref:
    print()
    print("СПРАВОЧНИК ЗАВОДСКИХ КОНСТАНТ (растёт с каждым собранным аппаратом)")
    for model in sorted(ref):
        print("  %s" % model)
        for name, vals in sorted(ref[model].items()):
            one_per_model = REF[name][1] if name in REF else True
            mark = ("   <- эталон модели" if len(vals) == 1 and one_per_model else
                    "   <- РАЗНЫЕ ЗНАЧЕНИЯ У ОДНОЙ МОДЕЛИ, разобраться"
                    if len(vals) > 1 and one_per_model else
                    "   (зависит от конфигурации, разные значения — норма)"
                    if len(vals) > 1 else "")
            print("    %-18s %s%s" % (name, ", ".join(sorted(vals)), mark))
    print()
    print("  Строка для BATT_REF в diag.sh (скопировать, если модели там ещё нет):")
    for model in sorted(ref):
        r = ref[model]
        try:
            print('    "%s": (%s, %s, %s, "%s"),' % (
                model,
                sorted(r["Ёмкость батареи"])[0],
                sorted(r["Химия ячейки hi"])[0],
                sorted(r["Алгоритм химии hi"])[0],
                sorted(r["Код детали пака"])[0]))
        except KeyError:
            print('    %s — данных для отпечатка не хватает' % model)
    with open(out + "/reference.txt", "w") as f:
        for model in sorted(ref):
            for name, vals in sorted(ref[model].items()):
                f.write("%s\t%s\t%s\n" % (model, name, ", ".join(sorted(vals))))

print()
print("Разложено по файлам в %s" % out)
print("  varying.txt  - кандидаты в правила")
print("  constant.txt - в правила не годятся")
PY
