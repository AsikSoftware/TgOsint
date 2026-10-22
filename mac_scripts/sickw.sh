#!/bin/bash
# Проверка аппарата во внешней базе Sickw (данные Apple GSX + реестр GSMA).
# Даёт то, чего по кабелю нет вообще: ЧЁРНЫЙ СПИСОК, цвет, заводскую
# конфигурацию, статус оператора и iCloud — и всё это НЕЗАВИСИМО от телефона,
# то есть подделке со стороны аппарата неподвластно.
#
#   bash ~/Downloads/sickw.sh            — взять IMEI с подключённого телефона
#   bash ~/Downloads/sickw.sh 35xxxxxxxxxxxxx  — проверить конкретный IMEI
#   bash ~/Downloads/sickw.sh --да       — не спрашивать подтверждение
#
# КЛЮЧ. Скрипт его не содержит и никуда не записывает. Положи свой ключ
# в файл ~/.sickw_key одной строкой:
#     echo 'ТВОЙ_КЛЮЧ' > ~/.sickw_key && chmod 600 ~/.sickw_key
# либо передай через переменную окружения SICKW_KEY.
#
# ДЕНЬГИ. Каждый запрос платный (услуга 61 — около $0.10) и списывается ДАЖЕ
# при неудачном ответе. Поэтому: подтверждение перед запросом, и кэш — один
# и тот же IMEI повторно не оплачивается.
export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH
set -u
SERVICE=61          # iPHONE CARRIER & FMI & BLACKLIST: чёрный список, iCloud,
                    # оператор, SIM-lock, гарантия, модель с цветом и объёмом
CACHE="$HOME/Downloads/sickw_cache"
mkdir -p "$CACHE"

KEY="${SICKW_KEY:-}"
[ -z "$KEY" ] && [ -f "$HOME/.sickw_key" ] && KEY=$(tr -d ' \t\r\n' < "$HOME/.sickw_key")
if [ -z "$KEY" ]; then
  echo "Нет ключа Sickw. Положи его в файл:"
  echo "    echo 'ТВОЙ_КЛЮЧ' > ~/.sickw_key && chmod 600 ~/.sickw_key"
  echo "Ключ нужен один раз; в скрипте он не хранится."
  exit 1
fi

AUTO=0; IMEI=""
for A in "$@"; do
  case "$A" in
    --да|--yes) AUTO=1 ;;
    *[0-9]*) IMEI="$A" ;;
  esac
done

if [ -z "$IMEI" ]; then
  U=$(idevice_id -l 2>/dev/null | head -1)
  [ -z "$U" ] && { echo "Телефон не подключён, и IMEI не указан."; exit 1; }
  IMEI=$(ideviceinfo -u "$U" -k InternationalMobileEquipmentIdentity 2>/dev/null)
  PT=$(ideviceinfo -u "$U" -k ProductType 2>/dev/null)
  GB=$(ideviceinfo -u "$U" -q com.apple.disk_usage 2>/dev/null | awk -F': ' '/TotalDiskCapacity/{printf "%d", $2/1000000000}')
  echo "С телефона: $PT, ${GB} ГБ"
else
  PT=""; GB=""
fi
[ -z "$IMEI" ] && { echo "IMEI не получен."; exit 1; }

# Проверка контрольной цифры по Луну — бесплатно и до траты денег:
# опечатка в IMEI иначе обошлась бы в оплаченный запрос.
python3 - "$IMEI" <<'PY'
import sys
s=[c for c in sys.argv[1] if c.isdigit()]
if len(s)!=15:
    print("  ⚠️ в IMEI %d цифр вместо 15 — проверь" % len(s)); sys.exit(0)
d=[int(c) for c in s]; t=0
for i,x in enumerate(d[:14]):
    if i%2: x*=2; x=x-9 if x>9 else x
    t+=x
print("  контрольная цифра: %s" % ("сходится" if (10-t%10)%10==d[14] else "НЕ СХОДИТСЯ — IMEI записан неверно"))
PY

C="$CACHE/${IMEI}.json"
if [ -s "$C" ]; then
  echo "  (из кэша, повторно не оплачивается)"
else
  if [ "$AUTO" -ne 1 ]; then
    echo
    echo "Запрос платный: услуга $SERVICE, около \$0.10, списывается и при неудаче."
    echo "IMEI $IMEI будет отправлен в Sickw (внешний сервис, данные Apple GSX)."
    printf "Отправлять? [y/N] "
    read -r ANS
    case "$ANS" in y|Y|д|Д) ;; *) echo "Отменено, деньги не списаны."; exit 0 ;; esac
  fi
  curl -sL --max-time 60 --get "https://sickw.com/api.php" \
    --data-urlencode "format=json" \
    --data-urlencode "key=$KEY" \
    --data-urlencode "imei=$IMEI" \
    --data-urlencode "service=$SERVICE" > "$C"
  if ! grep -q '"status"' "$C" 2>/dev/null; then
    echo "  Сервис ответил непонятно:"; head -c 300 "$C"; echo
    rm -f "${C:?}"; exit 2
  fi
fi

python3 - "$C" "$IMEI" "$PT" "$GB" <<'PY'
import json, re, sys, os, datetime, html
path, imei, pt, gb = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
d = json.load(open(path, encoding="utf-8"))
if str(d.get("status","")).lower() != "success":
    print("  ⛔ Сервис вернул ошибку: %s" % d.get("result"))
    print("     Кредит при этом списан — так работает Sickw.")
    os.remove(path)          # не кэшируем ошибку, иначе она застрянет навсегда
    raise SystemExit(2)

# result приходит одним блоком «Метка: значение», разделённым <br>
raw = html.unescape(re.sub(r"<[^>]+>", "\n", str(d.get("result",""))))
f = {}
for line in raw.split("\n"):
    if ":" in line:
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if k and v: f[k] = v

def get(*names):
    for n in names:
        for k in f:
            if k.lower() == n.lower(): return f[k]
    return ""

model = get("Model","Model Description","Description")
print("════════ ВНЕШНЯЯ ПРОВЕРКА (Sickw / Apple GSX) ════════")
print("  Модель с завода : %s" % (model or "не пришло"))
for label, keys in (
    ("Чёрный список",   ("Blacklist Status",)),
    ("iCloud / Find My",("iCloud Lock",)),
    ("SIM-lock",        ("SIM-Lock","SIM Lock")),
    ("Оператор",        ("Locked Carrier",)),
    ("Страна политики", ("Locked Activation Policy Country",)),
    ("Гарантия",        ("Warranty Status",)),
    ("Дата покупки",    ("Estimated Purchase Date","Purchase Date")),
    ("Замена по гарантии",("Replaced Device",)),
    ("Подменный аппарат",("Loaner Device",)),
):
    v = get(*keys)
    if v: print("  %-16s: %s" % (label, v))

# Цвет и объём зашиты в строку модели, отдельных полей у сервиса нет
cap = re.search(r"\b(\d+)\s?(GB|TB)\b", model, re.I)
col = re.sub(r"\[.*?\]", "", model)
col = re.sub(r"\b\d+\s?(GB|TB)\b", "", col, flags=re.I)
col = re.sub(r"^\s*iPhone[\w\s]*?(Pro Max|Pro|Plus|mini|Air|SE)?\s*\d*\s*", "", col, flags=re.I).strip(" -,")
print()
print("  Объём с завода  : %s" % (cap.group(0).upper() if cap else "не вычленился"))
print("  Цвет с завода   : %s" % (col or "не вычленился"))

# ---- сверка с тем, что сказал сам телефон ----
if gb and cap:
    want = int(cap.group(1)) * (1024 if cap.group(2).upper()=="TB" else 1)
    have = int(gb)
    ok = abs(want-have) <= max(8, want*0.1)
    print()
    if ok:
        print("  ✅ Объём совпал с тем, что рапортует телефон (%s ГБ)" % have)
    else:
        print("  ⛔ ОБЪЁМ НЕ СОВПАЛ: завод %s, телефон рапортует %s ГБ" % (cap.group(0), have))
        print("     Вероятна перепаянная память. Это та проверка, которую")
        print("     кабель в одиночку сделать не может: внешняя база не зависит")
        print("     от аппарата, и подделать её со стороны телефона нельзя.")

bl = get("Blacklist Status")
if bl and bl.strip().upper() not in ("CLEAN","CLEAR"):
    print()
    print("  ⛔⛔ ЧЁРНЫЙ СПИСОК: %s — НЕ ПРИНИМАТЬ, это юридический риск" % bl)
ic = get("iCloud Lock")
if ic and ic.strip().upper() == "ON":
    print("  ⛔ iCloud ВКЛЮЧЁН — клиент должен выйти из Apple ID до сдачи")

try:
    log = os.path.expanduser("~/Downloads/iphone_sickw.jsonl")
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "время": datetime.datetime.now().isoformat(timespec="seconds"),
            "imei": imei, "модель_с_телефона": pt, "объём_с_телефона": gb,
            "поля": f,
        }, ensure_ascii=False) + "\n")
    print()
    print("  Записано в ~/Downloads/iphone_sickw.jsonl")
except Exception:
    pass
PY
