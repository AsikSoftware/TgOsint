#!/bin/bash
# ХАРВЕСТЕР. Выгребает с подключённого iPhone всё, что он отдаёт по кабелю.
# Имена записей НЕ угадываются: сначала снимается карта реестра с самого
# аппарата, потом опрашивается каждое имя из неё. Поэтому покрытие полное.
#
# Это инструмент РАЗРАБОТКИ, он идёт ~10-15 минут. Для приёмки есть diag.sh.
# Запуск: bash ~/Downloads/harvest.sh
export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH
set -u
BASE="$HOME/Downloads/iphone_harvest"
FAIL=0

# В macOS нет команды timeout. Её отсутствие уже один раз молча уронило
# четыре этапа сбора из пяти, поэтому таймаут здесь свой.
run_to() {
  local s=$1; shift; "$@" & local p=$!
  ( sleep "$s"; kill -9 "$p" 2>/dev/null ) & local w=$!
  wait "$p" 2>/dev/null; local rc=$?
  kill -9 "$w" 2>/dev/null; wait "$w" 2>/dev/null; return $rc
}
# Служба диагностики на телефоне иногда отказывает с первого раза — например,
# если к ней только что обращались. Один отказ не должен стоить всего сбора,
# поэтому важные запросы повторяются.
retry_to() {
  local tries=$1 secs=$2 dest=$3; shift 3
  local i
  for i in $(seq 1 "$tries"); do
    run_to "$secs" "$@" > "$dest" 2>/dev/null
    ok_plist "$dest" && return 0
    sleep 2
  done
  rm -f "$dest"; return 1
}
ok_plist() { [ -s "$1" ] && [ "$(wc -c < "$1" | tr -d ' ')" -gt 220 ] && ! grep -q 'Deprecated' "$1" 2>/dev/null; }

UDID=$(idevice_id -l 2>/dev/null | head -1)
if [ -z "$UDID" ]; then
  echo "Телефон не подключён или не доверяет компьютеру."
  echo "Подключи кабелем, разблокируй экран, нажми «Доверять»."
  exit 1
fi
# Каждый аппарат в свою папку: сравнение нескольких телефонов - единственный
# способ отличить настоящий сигнал от константы прошивки (см. compare.sh).
OUT="$BASE/$UDID"; rm -rf "$OUT"; mkdir -p "$OUT"/{planes,entries,domains,diag}
PT=$(ideviceinfo -k ProductType 2>/dev/null); IOS=$(ideviceinfo -k ProductVersion 2>/dev/null)
echo "Аппарат: $PT, iOS $IOS"
echo "Папка  : $OUT"
echo "Идёт 10-15 минут. Телефон не отключай."
echo

# ---------- 1. Карта реестра ----------
echo "[1/4] карта IORegistry"
for P in IOService IODeviceTree IOPower IOUSB; do
  retry_to 3 180 "$OUT/planes/$P.plist" idevicediagnostics -u "$UDID" ioreg "$P" \
    && echo "      $P: $(wc -c < "$OUT/planes/$P.plist" | tr -d ' ') байт"
done
[ -z "$(ls -A "$OUT/planes" 2>/dev/null)" ] && { echo "  ОШИБКА: карта реестра не снялась"; FAIL=1; }

# ---------- 2. Имена из карты ----------
echo "[2/4] имена записей"
python3 - "$OUT" <<'PY'
import plistlib, sys, os, glob
out = sys.argv[1]; names = set()
def walk(o):
    if isinstance(o, dict):
        for k in ("name", "className"):
            v = o.get(k)
            if isinstance(v, str) and v and len(v) < 64 and "/" not in v: names.add(v)
        for v in o.values(): walk(v)
    elif isinstance(o, list):
        for v in o: walk(v)
for f in glob.glob(os.path.join(out, "planes", "*.plist")):
    try: walk(plistlib.load(open(f, "rb")))
    except Exception: pass
open(os.path.join(out, "all_names.txt"), "w").write("\n".join(sorted(names)))
print("      снято с аппарата: %d имён" % len(names))
PY

# ---------- 3. Опрос каждого имени ----------
echo "[3/4] опрос записей"
TOT=$(wc -l < "$OUT/all_names.txt" | tr -d ' '); I=0; GOT=0
while IFS= read -r NAME; do
  I=$((I+1)); [ -z "$NAME" ] && continue
  SAFE=$(printf '%s' "$NAME" | tr -c 'A-Za-z0-9._-' '_')
  F="$OUT/entries/$SAFE.plist"
  # Телефон могли отключить или подменить прямо во время сбора. Смешать в одной
  # описи данные двух аппаратов — хуже, чем не собрать ничего: сравнение потом
  # покажет ложные различия. Поэтому сверяемся с UDID каждые 50 запросов.
  if [ $((I % 50)) -eq 0 ] && ! idevice_id -l 2>/dev/null | grep -q "^$UDID$"; then
    echo "      ОШИБКА: аппарат $UDID отключён или подменён на $I-м запросе"
    echo "      Данные неполны и смешивать их нельзя. Подключи тот же телефон и повтори."
    exit 3
  fi
  retry_to 2 12 "$F" idevicediagnostics -u "$UDID" ioregentry "$NAME" && GOT=$((GOT+1))
  [ $((I % 100)) -eq 0 ] && echo "      $I/$TOT, ответили $GOT"
done < "$OUT/all_names.txt"
echo "      итого ответили: $GOT из $TOT"
[ "$GOT" -eq 0 ] && { echo "  ОШИБКА: ни одна запись не ответила"; FAIL=1; }

# ---------- 4. Домены и diagnostics ----------
echo "[4/4] lockdown-домены и diagnostics"
ideviceinfo -u "$UDID" --xml > "$OUT/domains/_root.plist" 2>/dev/null
for D in com.apple.mobile.battery com.apple.disk_usage com.apple.disk_usage.factory \
  com.apple.mobile.debug com.apple.iqagent com.apple.purplebuddy com.apple.mobile.chaperone \
  com.apple.mobile.third_party_termination com.apple.mobile.lockdownd com.apple.mobile.lockdown_cache \
  com.apple.xcode.developerdomain com.apple.international com.apple.mobile.data_sync \
  com.apple.mobile.tethered_sync com.apple.mobile.mobile_application_usage com.apple.mobile.backup \
  com.apple.mobile.nikita com.apple.mobile.restriction com.apple.mobile.user_preferences \
  com.apple.mobile.sync_data_class com.apple.mobile.software_behavior com.apple.mobile.internal \
  com.apple.mobile.wireless_lockdown com.apple.fairplay com.apple.iTunes com.apple.mobile.iTunes \
  com.apple.mobile.iTunes.store com.apple.mobile.iTunes.accessories com.apple.fmip com.apple.Accessibility ; do
  ideviceinfo -u "$UDID" -q "$D" --xml > "$OUT/domains/$D.plist" 2>/dev/null
  ok_plist "$OUT/domains/$D.plist" || rm -f "$OUT/domains/$D.plist"
done
N=$(ls "$OUT/domains" | wc -l | tr -d ' '); echo "      доменов ответило: $N"
[ "$N" -eq 0 ] && { echo "  ОШИБКА: lockdown-домены не ответили"; FAIL=1; }
# MobileGestalt не опрашиваем: Apple его закрыла, отдаёт MobileGestaltDeprecated.
for T in All GasGauge HDMI; do
  run_to 60 idevicediagnostics -u "$UDID" diagnostics "$T" > "$OUT/diag/$T.plist" 2>/dev/null
  ok_plist "$OUT/diag/$T.plist" || rm -f "$OUT/diag/$T.plist"
done

# ---------- Опись ----------
python3 - "$OUT" "$PT" "$IOS" <<'PY'
import plistlib, sys, os, glob, json
out, pt, ios = sys.argv[1], sys.argv[2], sys.argv[3]
flat = {}
def walk(o, path):
    if isinstance(o, dict):
        for k, v in o.items(): walk(v, path + [str(k)])
    elif isinstance(o, list):
        for i, v in enumerate(o): walk(v, path + [str(i)])
    else:
        if isinstance(o, bytes):
            # Больше четверти байтовых значений — обычный текст: серийники
            # модулей, идентификаторы, имена. Раньше они уходили в заглушку
            # «<N байт>», и вместе с ними терялись готовые сигналы
            # (например rosaline-serial-num = серийник датчика приближения,
            # который должен совпадать с AppleProxHIDEventDriver/SerialNumber).
            t = o.rstrip(b"\x00")
            o = (t.decode("ascii") if t and len(t) <= 64
                 and all(32 <= c < 127 for c in t) else "<%d байт>" % len(o))
        flat["/".join(path)] = o
for sub, pref in (("entries", ""), ("domains", "DOMAIN:"), ("diag", "DIAG:")):
    for f in glob.glob(os.path.join(out, sub, "*.plist")):
        try: d = plistlib.load(open(f, "rb"))
        except Exception: continue
        walk(d, [pref + os.path.basename(f).replace(".plist", "")])
flat["_meta/ProductType"] = pt; flat["_meta/ProductVersion"] = ios
# Отметка полноты: сравнивать оборванный сбор с полным нельзя — его
# недостающие ключи выглядят как «зависит от модели», хотя их просто
# не успели снять. Судить по объёму ненадёжно, поэтому пишем факт.
names = os.path.join(out, "all_names.txt")
asked = sum(1 for _ in open(names)) if os.path.exists(names) else 0
got = len(glob.glob(os.path.join(out, "entries", "*.plist")))
flat["_meta/asked"] = asked
flat["_meta/answered"] = got
flat["_meta/complete"] = "yes" if asked and got >= asked * 0.5 else "no"
json.dump(flat, open(os.path.join(out, "inventory.json"), "w"), ensure_ascii=False, indent=0, default=str)
with open(os.path.join(out, "inventory.txt"), "w") as f:
    for k in sorted(flat): f.write("%s = %s\n" % (k, flat[k]))
print()
print("ГОТОВО: %d значений" % len(flat))
print("  опись: %s/inventory.txt" % out)
PY

if [ "$FAIL" -ne 0 ]; then
  echo
  echo "СБОР НЕПОЛНЫЙ - выше указано, что не ответило. Опись использовать нельзя."
  exit 2
fi
echo "  Собери так же ещё хотя бы один телефон и запусти compare.sh -"
echo "  он отделит настоящие сигналы от констант прошивки."
exit 0
