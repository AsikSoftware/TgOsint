#!/bin/bash
# Полная диагностика сдаваемого iPhone по кабелю. Без приложений и джейлбрейка.
#   bash ~/Downloads/diag.sh          — отчёт для человека
#   bash ~/Downloads/diag.sh --json   — то же в JSON, для бота
B=/opt/homebrew/bin
JSON=0; REPAIR=""
# Заведомо ремонтный аппарат можно пометить при проверке:
#   bash diag.sh --ремонт "экран неоригинал, батарея менялась"
# Без такой пометки ремонтный телефон в выборке бесполезен для калибровки:
# по отсутствию флага нельзя понять, промахнулось правило или честно
# промолчало, потому что сверки для этой детали нет вовсе.
while [ $# -gt 0 ]; do
  case "$1" in
    --json)   JSON=1 ;;
    --ремонт|--repair) shift; REPAIR="$1" ;;
    *) echo "Неизвестный аргумент: $1"; echo "Использование: diag.sh [--json] [--ремонт \"что менялось\"]"; exit 1 ;;
  esac
  shift
done
export DIAG_REPAIR="$REPAIR"
U=$($B/idevice_id -l 2>/dev/null | head -1)
if [ -z "$U" ]; then
  [ $JSON = 1 ] && echo '{"error":"Телефон не найден"}' \
                || { echo "❌ Телефон не найден."; echo "   Подключи кабелем и нажми «Доверять» на экране телефона."; }
  exit 1
fi

D=$(mktemp -d); trap 'rm -rf "$D"' EXIT
$B/ideviceinfo    -u "$U" --xml                        > "$D/info.xml"   2>/dev/null
$B/ideviceinfo    -u "$U" -q com.apple.disk_usage --xml > "$D/disk.xml"  2>/dev/null
# имена записей отличаются между поколениями iPhone — снимаем все варианты
for e in AppleSmartBattery AppleCLCD2 AppleMultitouchDevice \
         device-tree product AppleProxHIDEventDriver \
         AppleANS3NVMeController AppleANS2NVMeController AppleEmbeddedNVMeController \
         AppleANS3CGv2Controller AppleANS2CGv2Controller AppleANS2CGNVMeController \
         AppleHapticsSupportArcEEPROM AppleHapticsSupportLEAP haptics-support-interface \
         AIDBus options AppleARMBacklight \
         AppleCamera AppleH13CamIn AppleH14CamIn AppleH16CamIn \
         AppleBCMWLANCore AppleWLANCore; do
  # Служба диагностики на телефоне отказывает с первого раза заметно часто —
  # особенно если к ней только что обращались. Один отказ оборачивался
  # пропавшим вердиктом по детали, поэтому повторяем.
  for try in 1 2 3; do
    $B/idevicediagnostics -u "$U" ioregentry "$e" 2>/dev/null > "$D/$e.xml"
    grep -q 'IORegistry' "$D/$e.xml" 2>/dev/null && break
    sleep 1
  done
done

# Связь могла оборваться ПОСЛЕ стартовой проверки: кабель дёрнули, телефон
# заблокировался, отозвали доверие. Тогда файлы приходят пустые, и без этой
# проверки скрипт выдал бы «ЗАМЕНЕНА» по каждой детали — то есть отказ
# клиенту с исправным телефоном из-за плохого контакта. Лучше честно
# сказать «связь потеряна», чем выдать уверенный неправильный вердикт.
# Аппарат могли подменить за те секунды, что шёл сбор. Тогда часть данных
# была бы от одного телефона, часть от другого, а вердикт — ни о том, ни о
# другом. Сверяем, что это всё ещё тот же UDID.
if ! $B/idevice_id -l 2>/dev/null | grep -q "^$U$"; then
  [ $JSON = 1 ] && echo '{"error":"Телефон подменили или отключили во время проверки"}' \
                || { echo "❌ Телефон подменили или отключили во время проверки."; \
                     echo "   Подключи один аппарат и повтори."; }
  exit 1
fi
if ! grep -q 'SerialNumber' "$D/info.xml" 2>/dev/null; then
  [ $JSON = 1 ] && echo '{"error":"Связь с телефоном потеряна во время проверки"}' \
                || { echo "❌ Связь с телефоном потеряна во время проверки."; \
                     echo "   Проверь кабель, разблокируй экран и повтори."; }
  exit 1
fi
if ! grep -lq 'IORegistry' "$D"/Apple*.xml 2>/dev/null; then
  [ $JSON = 1 ] && echo '{"error":"Телефон не отдал данные о деталях"}' \
                || { echo "❌ Телефон не отдал данные о деталях."; \
                     echo "   Разблокируй экран и повтори — вердикт по деталям без них недостоверен."; }
  exit 1
fi

JSON=$JSON DIR="$D" UDID="$U" python3 <<'PY'
import plistlib, os, json, sys, re, struct
D, AS_JSON = os.environ["DIR"], os.environ["JSON"] == "1"

def plist(name, inner=None):
    try:
        with open(f"{D}/{name}.xml", "rb") as f:
            d = plistlib.load(f)
        return d.get(inner, d) if inner else d
    except Exception:
        return {}

def deep(obj, key):
    """Ищем ключ на любой глубине: Apple прячет нужное во вложенных разделах
    (температура — в BatteryData/LifetimeData, iCloud — в NonVolatileRAM)."""
    if isinstance(obj, dict):
        if key in obj and not isinstance(obj[key], (dict, list)):
            return obj[key]
        for v in obj.values():
            r = deep(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = deep(v, key)
            if r is not None:
                return r
    return None

def txt(v):
    """Серийники лежат байтами с нулём на конце — приводим к строке."""
    if isinstance(v, bytes):
        t = v.rstrip(b"\x00")
        return t.decode("ascii", "replace") if t else ""
    return str(v or "")

info = plist("info"); disk = plist("disk")
batt = plist("AppleSmartBattery", "IORegistry")
# камера: на новых моделях запись называется AppleCamera, на старых AppleH13CamIn
cam = {}
for nm in ("AppleCamera", "AppleH13CamIn", "AppleH14CamIn", "AppleH16CamIn"):
    cam = plist(nm, "IORegistry")
    if cam:
        break
disp = plist("AppleCLCD2",        "IORegistry")
mt   = plist("AppleMultitouchDevice", "IORegistry")
wifi = plist("AppleBCMWLANCore", "IORegistry") or plist("AppleWLANCore", "IORegistry")

MODELS = {
 # 17 и 18 серия — по everymac.com/devices/by-identifier/all-iphone-model-identifiers.html,
 # обновление страницы 17.10.2026. Источник проверен на известных данных:
 # его строки по iPhone16,x и iPhone17,x совпали с тем, что было в справочнике
 # до обращения к нему. По памяти эти соответствия я ранее вписывал неверно и
 # снимал — поэтому только из источника, не из головы.
 # iPhone 18 Pro Max публикуется под ДВУМЯ кодами (19,3 для США, 19,7 для
 # остальных регионов). Название одно, поэтому в цене это не путает.
 # iPhone19,1 в источнике отсутствует, домыслов тут нет.
 "iPhone18,1":"iPhone 17 Pro", "iPhone18,2":"iPhone 17 Pro Max",
 "iPhone18,3":"iPhone 17", "iPhone18,4":"iPhone Air",
 "iPhone18,5":"iPhone 17e",
 "iPhone19,2":"iPhone 18 Pro", "iPhone19,3":"iPhone 18 Pro Max",
 "iPhone19,7":"iPhone 18 Pro Max",

 # Старые модели: в Казахстане их сдают до сих пор. Соответствия давно
 # устоялись, дубли кодов (9,1/9,3 и т.п.) — это варианты модема, модель одна.
 "iPhone8,1":"iPhone 6s","iPhone8,2":"iPhone 6s Plus","iPhone8,4":"iPhone SE 2016",
 "iPhone9,1":"iPhone 7","iPhone9,3":"iPhone 7","iPhone9,2":"iPhone 7 Plus",
 "iPhone9,4":"iPhone 7 Plus","iPhone10,1":"iPhone 8","iPhone10,4":"iPhone 8",
 "iPhone10,2":"iPhone 8 Plus","iPhone10,5":"iPhone 8 Plus",
 "iPhone10,3":"iPhone X","iPhone10,6":"iPhone X",
 "iPhone11,2":"iPhone XS","iPhone11,4":"iPhone XS Max","iPhone11,6":"iPhone XS Max",
 "iPhone11,8":"iPhone XR",
 "iPhone12,1":"iPhone 11","iPhone12,3":"iPhone 11 Pro","iPhone12,5":"iPhone 11 Pro Max",
 "iPhone12,8":"iPhone SE 2020","iPhone13,1":"iPhone 12 mini","iPhone13,2":"iPhone 12",
 "iPhone13,3":"iPhone 12 Pro","iPhone13,4":"iPhone 12 Pro Max","iPhone14,4":"iPhone 13 mini",
 "iPhone14,5":"iPhone 13","iPhone14,2":"iPhone 13 Pro","iPhone14,3":"iPhone 13 Pro Max",
 "iPhone14,6":"iPhone SE 2022","iPhone14,7":"iPhone 14","iPhone14,8":"iPhone 14 Plus",
 "iPhone15,2":"iPhone 14 Pro","iPhone15,3":"iPhone 14 Pro Max","iPhone15,4":"iPhone 15",
 "iPhone15,5":"iPhone 15 Plus","iPhone16,1":"iPhone 15 Pro","iPhone16,2":"iPhone 15 Pro Max",
 "iPhone17,3":"iPhone 16","iPhone17,4":"iPhone 16 Plus","iPhone17,1":"iPhone 16 Pro",
 "iPhone17,2":"iPhone 16 Pro Max","iPhone17,5":"iPhone 16e"}
# Модели 17/18 серии сюда не вписаны намеренно: я не могу подтвердить соответствие
# кодов, а ошибка с моделью в системе выкупа дороже, чем показанный сырой код.
# Подключите такой аппарат, сверьте с коробкой — и добавим точно.
# Цвет по кабелю НЕ ОПРЕДЕЛЯЕТСЯ. Поле DeviceColor равнялось "1" на всех шести
# собранных аппаратах разных моделей и, судя по всему, цвет не кодирует вовсе;
# поля DeviceEnclosureColor в данных нет. Прежняя таблица сопоставляла "1" с
# «Чёрный / Тёмный» и потому писала «чёрный» для любого телефона — то есть
# врала на всех нечёрных. Лучше не показывать ничего, чем показывать выдумку.
# Настоящий цвет кодирует номер модели (MGJ53 против другого кода того же
# объёма), но таблицы соответствий у нас нет — её даёт внешняя проверка
# по серийнику либо накопление с витрины.
COLORS = {}

def i(k, d=""): return info.get(k, d)
def n(v):
    try: return int(v)
    except Exception: return 0

pt = i("ProductType")
res = {
 "udid": os.environ["UDID"],
 "model": MODELS.get(pt, f"{pt} — модель не в справочнике"), "product_type": pt,
 "model_number": f'{i("ModelNumber")}{i("RegionInfo")}',
 "serial": i("SerialNumber"),
 "imei": i("InternationalMobileEquipmentIdentity"),
 "imei2": i("InternationalMobileEquipmentIdentity2"),
 "color": COLORS.get(str(i("DeviceColor")), "по кабелю не определяется — записать глазами"),
 "ios": i("ProductVersion"),
 "mlb_serial": i("MLBSerialNumber"),
 "storage_gb": n(disk.get("TotalDiskCapacity")) // 10**9,
 "free_gb":    n(disk.get("TotalDataAvailable")) // 10**9,
}

# ---- батарея ----
des = n(deep(batt,"DesignCapacity"))
# Здоровье = фактическая ёмкость / заводская. Именно NominalChargeCapacity
# даёт ту цифру, что показывают Настройки (проверено на iPhone 12:
# 2248/2798 = 80%, в Настройках тоже 80).
# MaxCapacity здесь НЕ используется намеренно: это не процент здоровья, а
# константа шкалы, она равна 100 даже на убитой батарее с 1687 циклами.
# Старый запасной вариант через неё показывал «100% — идеал» на мёртвой батарее.
raw = n(deep(batt,"NominalChargeCapacity")) or n(deep(batt,"AppleRawMaxCapacity"))
tmax = n(deep(batt,"MaximumTemperature")) // 10
res["battery"] = {
 # ёмкости не прочитались — честно говорим «не определилось», а не выдумываем
 "health_pct": (min(raw*100//des, 100) if (des and raw) else 0),
 "cycles": n(deep(batt,"CycleCount")),
 "capacity_mah": raw, "design_mah": des,
 "serial": deep(batt,"Serial") or "",
 "temp_c": n(deep(batt,"Temperature"))//100,
 "max_temp_c": tmax if 0 <= tmax <= 90 else None,
 "operating_years": round(n(deep(batt,"TotalOperatingTime"))/8760, 1) or None,
 "cell_disconnects": n(deep(batt,"BatteryCellDisconnectCount")),
}

# ---- детали: серийники модулей. Замена детали меняет серийник,
#      а статусы проверки Apple перестают быть Pass/Valid ----
res["parts"] = {
 "back_camera":     deep(cam,"BackCameraModuleSerialNumString") or "",
 "ultrawide_camera":deep(cam,"BackSuperWideCameraModuleSerialNumString") or "",
 "tele_camera":    deep(cam,"BackTeleCameraModuleSerialNumString") or "",
 "front_camera":    deep(cam,"FrontCameraModuleSerialNumString") or "",
 "faceid_camera":   deep(cam,"FrontIRCameraModuleSerialNumString") or "",
 "faceid_projector":deep(cam,"FrontIRStructuredLightProjectorSerialNumString") or "",
 "display_panel_id":str(deep(disp,"Panel_ID") or "")[:48],
 "touch_id":        str(deep(mt,"Multitouch ID") or ""),
}
res["validation"] = {k: (deep(cam,k) or "") for k in
  ("CmClValidationStatus","CmPMValidationStatus","FCClValidationStatus",
   "SavageDATFileStatus","YonkersDATFileStatus","RomeoStatus")}

res["touch"] = {
 "rows": n(deep(mt,"Sensor Rows")), "cols": n(deep(mt,"Sensor Columns")),
 "scan_rate": n(deep(mt,"ScanRate")),
 "resets": n(deep(mt,"ResetCount")), "critical_errors": n(deep(mt,"Critical Errors")),
}
res["wifi_chipset"] = str(deep(wifi,"ChipSet") or "")

# ---------- ВЕРДИКТ ПО ДЕТАЛЯМ ----------
# Логика опирается на два наблюдаемых факта:
#   1) исправный оригинальный модуль ВСЕГДА называет свой серийный номер;
#      пустой серийник при том, что деталь в этой модели предусмотрена, —
#      это либо неоригинал, либо модуль не отвечает;
#   2) проверки Apple лежат в той же записи, что и камеры, и относятся к ним
#      и к Face ID. Не Pass/Valid — Apple не подтверждает подлинность.
# Чего логика НЕ знает: какой серийник стоял на заводе. Это знает только Apple,
# поэтому «оригинал» здесь = «деталь честно представилась и Apple не возражает».
# Три состояния проверки, и путать их нельзя:
#   Pass/Valid — проверка прошла;
#   Invalid    — проверка проведена и ПРОВАЛЕНА, это сигнал;
#   Unknown    — проверка не проводилась, данных нет. НЕ сигнал.
# Привязка проверок к деталям — по кодовым именам Apple (Savage/Yonkers/Romeo —
# модули TrueDepth, FC — front camera, Cm — camera module). Это вывод по именам,
# а не документация Apple: проверено на двух аппаратах, не на выборке.
# Ни одно поле *ValidationStatus в вердикт НЕ идёт — ни при каком значении.
# Причина: это константы семейства чипа, различающиеся между поколениями
# (SavageNVMRev = 0xaa на iPhone 12 и 0x00 на iPhone 14 Pro), а не признаки
# конкретного аппарата. На четырёх аппаратах весь набор совпал символ в символ.
# Отклонение от такой константы означает «другое поколение», а не «замена».
# Значения по-прежнему пишутся в JSON как справочные.
VAL_PART = {}
# FCCl по-прежнему собирается в res["validation"] для записи в JSON,
# но в вердикт не идёт — отсюда .get(), а не прямое обращение.
failed  = {VAL_PART[k] for k, v in res["validation"].items()
           if v == "Invalid" and k in VAL_PART}
unknown = sorted(k.replace("ValidationStatus","").replace("Status","")
                 for k, v in res["validation"].items() if v == "Unknown")

def verdict(serial, expected, suspect=False, kind="деталь"):
    if serial:
        if suspect:
            return ("ПОД ВОПРОСОМ", "Apple не подтверждает — возможна замена или сбита калибровка")
        return ("ОРИГИНАЛ", "")
    if expected:
        return ("ЗАМЕНЕНА ИЛИ НЕ РАБОТАЕТ", "модуль не называет серийный номер")
    # Два совершенно разных случая, и раньше они сливались в один:
    #   запись камеры ответила, но этой камеры в модели нет (у iPhone 12 нет
    #     телефото) — это НОРМА, вердикту по аппарату мешать не должно;
    #   запись не ответила вовсе — данных нет, вердикт выдавать нельзя.
    # Пока они были слиты, каждый не-Pro аппарат навсегда застревал в
    # «ПРОВЕРКА НЕПОЛНАЯ» и не мог получить ни «ИДЕАЛ», ни «ХОРОШИЙ».
    if cam:
        return ("НЕТ В МОДЕЛИ", "")
    return ("НЕТ ДАННЫХ", "запись камеры не ответила")

P = res["parts"]
parts_verdict = {}
for label, key, exp_key, suspect in (
    ("Основная камера",  "back_camera",      "BackCameraExpected",          "rear"   in failed),
    ("Сверхширокая",     "ultrawide_camera", "BackSuperWideCameraExpected", "rear"   in failed),
    ("Телефото",         "tele_camera",      "BackTeleCameraExpected",      "rear"   in failed),
    ("Фронтальная",      "front_camera",     "FrontCameraExpected",         "front"  in failed),
    ("Face ID",          "faceid_camera",    "FrontIRCameraExpected",       "faceid" in failed),
):
    exp = bool(deep(cam, exp_key))
    v, why = verdict(P[key], exp, suspect)
    parts_verdict[label] = {"verdict": v, "why": why}

# экран: опознаётся по Panel ID
# Разделяем два разных случая, которые раньше сливались в один вердикт:
#   запись дисплея вообще не ответила  -> данных нет, молчим;
#   запись ответила, но Panel_ID пуст  -> панель себя не называет, это сигнал.
# Раньше оба давали «ЗАМЕНЁН», и достаточно было не прочитаться записи,
# чтобы исправный экран объявили заменённым.
if not disp:
    parts_verdict["Экран"] = {"verdict": "НЕТ ДАННЫХ", "why": "запись дисплея не ответила"}
elif P["display_panel_id"]:
    parts_verdict["Экран"] = {"verdict": "ОРИГИНАЛ", "why": ""}
else:
    parts_verdict["Экран"] = {"verdict": "ЗАМЕНЁН ИЛИ НЕ ОПОЗНАН", "why": "панель не называет себя"}
# батарея: серийник + износ
bs, bh = res["battery"]["serial"], res["battery"]["health_pct"]
if not batt:
    parts_verdict["Батарея"] = {"verdict": "НЕТ ДАННЫХ", "why": "запись батареи не ответила"}
elif bs:
    parts_verdict["Батарея"] = {"verdict": "ОРИГИНАЛ", "why": f"износ {bh}%" if bh else ""}
else:
    parts_verdict["Батарея"] = {"verdict": "ЗАМЕНЕНА ИЛИ НЕ ОПОЗНАНА", "why": "нет серийного номера"}
# тачскрин: единственное, что кабель проверяет на РАБОТУ, а не на подлинность
te = res["touch"]["critical_errors"]
parts_verdict["Тачскрин"] = ({"verdict": "ИСПРАВЕН", "why": "ошибок нет"} if not te
                             else {"verdict": "СБОИ", "why": f"критических ошибок: {te}"})
res["parts_verdict"] = parts_verdict

# ---- SIM / eSIM ----
# Лоток и вставленная симка — разные вещи: лоток может быть пустым, а на моделях
# «только eSIM» лотка нет вовсе. Второй IMEI означает поддержку eSIM.
SIM_ST = {
 "kCTSIMSupportSIMStatusNotInserted": "симки нет",
 "kCTSIMSupportSIMStatusReady":       "симка вставлена и работает",
 "kCTSIMSupportSIMStatusPINLocked":   "симка заблокирована PIN-кодом",
 "kCTSIMSupportSIMStatusPUKLocked":   "симка заблокирована PUK-кодом",
}
TRAY_ST = {
 "kCTSIMSupportSIMTrayInsertedNoSIM":   ("есть", False),
 "kCTSIMSupportSIMTrayInsertedWithSIM": ("есть", True),
 "kCTSIMSupportSIMTrayNotInserted":     ("лоток вынут", False),
 "kCTSIMSupportSIMTrayAbsent":          ("нет (только eSIM)", False),
}
sim_raw  = str(i("SIMStatus"))
tray_raw = str(i("SIMTrayStatus"))
tray_txt, sim_in = TRAY_ST.get(tray_raw, (tray_raw or "не определился", False))
has_esim = bool(res["imei2"])
has_tray = tray_raw.startswith("kCTSIMSupportSIMTrayInserted")

if has_tray and has_esim:  sim_kind = "Физическая SIM + eSIM"
elif has_esim and tray_raw and not has_tray: sim_kind = "Только eSIM"
elif has_tray:             sim_kind = "Только физическая SIM"
else:                      sim_kind = "не определился"

# перевод в словарь бота Оценки: поле sim принимает ровно эти значения
BOT_SIM = {"Физическая SIM + eSIM":"Dual Sim", "Только eSIM":"E-sim",
           "Только физическая SIM":"Стандарт", "не определился":"Прочее"}
res["sim"] = {
 "kind": sim_kind,
 "bot_value": BOT_SIM.get(sim_kind, "Прочее"),
 "tray": tray_txt,
 "status": SIM_ST.get(sim_raw, sim_raw or "—"),
 "inserted": sim_raw == "kCTSIMSupportSIMStatusReady" or sim_in,
 "esim_capable": has_esim,
 "mcc": i("MobileSubscriberCountryCode"), "mnc": i("MobileSubscriberNetworkCode"),
 "baseband": i("BasebandVersion"),
 "raw_status": sim_raw, "raw_tray": tray_raw,
}

# ---- юридический статус ----
# «Найти iPhone» лежит в ДВУХ независимых местах: в lockdown-домене и в
# записи options реестра. На пяти аппаратах они всегда совпадали. Расхождение
# означает, что одно из значений подменили, — это повод не принимать аппарат,
# а не выбирать, какому верить.
fm_opt = txt(deep(plist("options", "IORegistry"), "fm-activation-locked")).strip().upper()
fm = deep(info, "fm-activation-locked")
if isinstance(fm, bytes): fm = fm.decode(errors="ignore")
res["icloud_lock"] = {"NO":"выключен","YES":"включён"}.get(str(fm).strip(), "неизвестно")
res["icloud_channels_agree"] = (None if not fm_opt or res["icloud_lock"] == "неизвестно"
                                else fm_opt == str(fm).strip().upper())

# Корпоративный надзор: аппарат под управлением организации перепродать
# нельзя, новый владелец получит чужие политики и не сможет их снять.
# Читается тремя независимыми ключами; на пяти аппаратах все три False,
# поэтому True — осмысленный сигнал, а не вариант нормы.
sup = any(deep(plist(_e, "IORegistry"), _k) is True for _e, _k in (
    ("AIDBus", "TRM_TransportSupervised"),
    ("Port-Lightning", "SupervisedTransportsRestricted"),
    ("IOAccessoryTRM", "SupervisedTransportsRestricted")))
res["supervised"] = sup
res["activation"] = i("ActivationState")
res["passcode"]   = bool(deep(info,"PasswordProtected"))

# ---- выводы ----
# Записи, нужные сразу нескольким проверкам ниже.
dtree = plist("device-tree", "IORegistry")
prod  = plist("product", "IORegistry")
prox  = plist("AppleProxHIDEventDriver", "IORegistry")
# Имя контроллера памяти зависит от поколения: ANS3 на A14+, ANS2 раньше.
nvme = {}
# Имя узла контроллера памяти зависит от процессора: ANS2CGNVMe на A13,
# ANS3NVMe на A14, ANS3CGv2 на A15 и A16. Без полного перечня сверка объёма
# молча пропускалась на части моделей.
for _nm in ("AppleANS3NVMeController", "AppleANS2NVMeController",
            "AppleANS3CGv2Controller", "AppleANS2CGv2Controller",
            "AppleANS2CGNVMeController", "AppleEmbeddedNVMeController"):
    nvme = plist(_nm, "IORegistry")
    if nvme: break

# ---- Face ID: криптографическая привязка ----
# В 20 байтах SavageSNUM крипточипа TrueDepth зашиты идентификаторы самого
# чипа и СЕРИЙНИК ИК-КАМЕРЫ Face ID. Если ИК-камеру меняли, привязка рвётся.
# Это единственная найденная проверка замены, которая опирается на
# криптографию, а не на косвенные признаки.
# Порядок байтов: DeviceID и DeviceRev лежат в SNUM в обратном порядке.
# Проверено побайтно на четырёх аппаратах (два iPhone 12, iPhone 11 Pro,
# iPhone 13/14-поколения). Без разворота проверка проваливается на здоровом
# аппарате — то есть пометила бы заменённым каждый телефон.
def raw(name, key):
    """Сырые байты из записи камеры: тут важны именно байты, не текст."""
    v = deep(plist(name, "IORegistry") if isinstance(name, str) else name, key)
    return v if isinstance(v, bytes) else None

sn   = raw(cam, "SavageSNUM")
did  = raw(cam, "SavageDeviceID")
drev = raw(cam, "SavageDeviceRev")
ir   = raw(cam, "FrontIRCameraSerialNumber")
# ВАЖНО про порядок байтов: у SavageDeviceID он НЕ одинаков между поколениями.
# На iPhone 12 это 5061 и совпадает с SNUM[0:2] напрямую, на более новых
# аппаратах 6150 и требует разворота. Жёсткое требование любого из вариантов
# помечало «Face ID заменена» на половине исправных телефонов — поймано
# прогоном по всей собранной выборке. Поэтому сверка идентификаторов чипа
# принимает оба порядка, а решающей служит привязка серийника ИК-камеры:
# SNUM[4:12] == FrontIRCameraSerialNumber одинакова на всех аппаратах.
if sn and ir and len(sn) >= 12 and len(ir) == 8:
    # Сверяется РОВНО одно равенство. SavageDeviceID и SavageDeviceRev сюда
    # не входят сознательно: это константы семейства чипа, а не признаки
    # экземпляра, и они меняются между поколениями (на iPhone 14 Pro
    # SavageNVMRev=00 против 0xaa на iPhone 12). Их сверка ничего не
    # доказывает, зато создаёт поверхность для ложных срабатываний.
    if sn[4:12] == ir:
        parts_verdict["Face ID"] = {"verdict": "ОРИГИНАЛ",
            "why": "криптопривязка модуля к чипу сошлась"}
    else:
        parts_verdict["Face ID"] = {"verdict": "ЗАМЕНЕНА",
            "why": "криптопривязка ИК-камеры к чипу TrueDepth нарушена"}
# Если полей нет# Если полей нет — другое поколение чипа. Молчим, вердикт остаётся прежним.

# Фронтальная RGB-камера: криптопривязки у неё НЕТ, SavageSNUM связывает
# только ИК-камеру. Утверждать «оригинал» по одному наличию серийника —
# выдавать желаемое за действительное и создавать у приёмщика ложную
# уверенность. Честнее сказать, что подлинность не устанавливается.
if parts_verdict.get("Фронтальная", {}).get("verdict") == "ОРИГИНАЛ":
    parts_verdict["Фронтальная"] = {"verdict": "НА МЕСТЕ",
        "why": "подлинность по кабелю не проверяется, только наличие"}

# ---- Taptic Engine ----
# Редкий случай: у этой детали есть ПРЯМОЙ флаг подлинности от самой Apple,
# IsArcSerialNumberValid. На трёх аппаратах он True, то есть у здоровых всегда
# подтверждается — значит False осмысленно. Плюс серийник из EEPROM должен
# совпадать с началом ModuleSerial: это вторая независимая точка.
arc  = plist("AppleHapticsSupportArcEEPROM", "IORegistry")
hsi  = plist("haptics-support-interface", "IORegistry")
if arc:
    arc_sn = txt(deep(arc, "ArcSerialNumber"))
    arc_ok = deep(arc, "IsArcSerialNumberValid")
    # Сопряжение модуля с платой: серийник, записанный в самом модуле
    # (ArcSerialNumber), должен встречаться в калибровке со стороны платы
    # (pscl-cal). Если таптик меняли, не перепрошивая плату, они разойдутся.
    # Это сильнее флага подлинности: доказывает, что стоит именно тот модуль,
    # под который плату настраивали. Проверено на живом аппарате.
    pscl = deep(hsi, "pscl-cal")
    pscl = pscl.decode("ascii", "replace") if isinstance(pscl, bytes) else str(pscl or "")
    if arc_ok is False:
        parts_verdict["Taptic Engine"] = {"verdict": "НЕОРИГИНАЛ",
            "why": "Apple не признаёт серийник модуля"}
    elif arc_sn and pscl and arc_sn in pscl:
        parts_verdict["Taptic Engine"] = {"verdict": "ОРИГИНАЛ",
            "why": "модуль сопряжён с платой"}
    elif arc_sn and pscl:
        parts_verdict["Taptic Engine"] = {"verdict": "ЗАМЕНЕНА",
            "why": "модуль не тот, под который прошита плата"}
    elif arc_sn:
        parts_verdict["Taptic Engine"] = {"verdict": "НА МЕСТЕ",
            "why": "сопряжение с платой не прочиталось"}

# ---- Экран: калибровка панели против ожидаемой ----
# AppleARMBacklight держит ДВА набора значений, и имена различают их прямо:
#   lMinPanel / lMidPanel / lMaxPanel     — характеристики УСТАНОВЛЕННОЙ панели
#   lMinProduct / lMidProduct / lMaxProduct — то, что аппарат ОЖИДАЕТ
# На шести исправных аппаратах наборы совпали, при этом значения разные по
# моделям (lMinPanel 262144 у iPhone 12, 655360 у 13, 131072 у 14 Pro) —
# то есть это настоящая характеристика детали, а не константа прошивки.
# Неоригинальная или непарная панель должна дать расхождение.
#
# ВАЖНО, чем это отличается от снятой проверки Panel_ID: там значение
# сравнивалось с самим собой, потому что драйвер в IOKit наследует свойства
# узла дерева устройства, к которому подключился. Здесь же имена Panel и
# Product разделены в одной записи — это два разных набора, а не копия.
# Но подтвердить это может только аппарат с заведомо менянным экраном,
# поэтому вердикт пока мягкий: ПОД ВОПРОСОМ, а не ЗАМЕНЁН.
bl = plist("AppleARMBacklight", "IORegistry")
_cal = [(n(deep(bl, a)), n(deep(bl, b))) for a, b in
        (("lMinPanel", "lMinProduct"), ("lMidPanel", "lMidProduct"),
         ("lMaxPanel", "lMaxProduct"))]
_cal = [(a, b) for a, b in _cal if a and b]
res["screen_cal_ok"] = (None if len(_cal) < 3 else all(a == b for a, b in _cal))
if res["screen_cal_ok"] is False:
    parts_verdict["Экран"] = {"verdict": "ПОД ВОПРОСОМ",
        "why": "калибровка панели не совпадает с ожидаемой — вероятна замена"}

# ---- Экран: что о нём на самом деле известно ----
# Сверки «стекло против панели» НЕ СУЩЕСТВУЕТ, хотя выглядит, будто есть:
# product/coverglass-serial-number — это буквальный срез
# product/raw-panel-serial-number с позиции 39, а AppleCLCD2/Panel_ID побайтно
# равен raw-panel-serial-number. Проверено на четырёх аппаратах. Сравнение этих
# полей — сравнение строки с самой собой, оно не может не пройти.
# Такая «проверка» хуже отсутствия проверки: приёмщик видит зелёную галочку и
# считает экран подтверждённым, хотя не проверено ничего.
# Честно: панель называет себя, значит она на месте и читается. Подлинность
# экрана по кабелю установить нечем — как и у фронтальной камеры.
if parts_verdict.get("Экран", {}).get("verdict") == "ОРИГИНАЛ":
    parts_verdict["Экран"] = ({"verdict": "ОРИГИНАЛ",
        "why": "калибровка панели совпадает с ожидаемой"} if res["screen_cal_ok"]
        else {"verdict": "НА МЕСТЕ",
              "why": "панель отвечает, калибровку сверить не удалось"})


# ---- Память: возраст NAND против возраста батареи ----
# В домене com.apple.disk_usage лежит NANDInfo — 52 КБ телеметрии контроллера.
# Формат: записи «ключ uint32 + количество uint32 + N значений по 8 байт».
# Разбор сходится ровно до конца буфера на четырёх аппаратах; если не сошёлся —
# другое поколение прошивки, и вердикт по памяти выдавать нельзя.
# Запись 0x038 — дата появления NAND, 0x2a8 — версия прошивки (ею же
# проверяется правильность разбора).
#
# Зачем: тройная сверка объёма НЕ ловит «апгрейд памяти» 64→256 ГБ, потому что
# после перепайки все три источника честно рапортуют НОВЫЙ объём. А вот дата
# рождения NAND остаётся от донорского чипа. Сверяем её с началом службы
# батареи того же аппарата: на трёх исправных телефонах расхождение составило
# +4, -51 и +26 суток, то есть обе детали заводские. Порог в год даёт
# семикратный запас от наблюдаемого разброса.
# Оговорки: единица TotalOperatingTime (часы) не документирована, лишь
# арифметически согласуется; расхождение говорит, что одна из двух деталей
# менялась, но не какая именно; выборка — три аппарата.
nand = {}
try:
    blob = plist("disk", None).get("NANDInfo") if False else None
except Exception:
    blob = None
_disk_raw = {}
try:
    with open(f"{D}/disk.xml", "rb") as _f:
        _disk_raw = plistlib.load(_f)
except Exception:
    _disk_raw = {}
blob = _disk_raw.get("NANDInfo")
if isinstance(blob, (bytes, bytearray)):
    off = 0
    while off + 8 <= len(blob):
        _k, _c = struct.unpack_from("<II", blob, off); off += 8
        if _c > 4096 or off + _c * 8 > len(blob):
            nand = {}; break          # разбор рассинхронился — данным не верим
        nand.setdefault(_k, struct.unpack_from("<%dQ" % _c, blob, off)); off += _c * 8

res["nand_born"] = nand.get(0x038, (0,))[0] if nand else 0
bat_up = n(deep(batt, "UpdateTime"))
bat_op = n(deep(batt, "TotalOperatingTime"))
res["nand_vs_battery_days"] = None
if res["nand_born"] and bat_up and bat_op:
    res["nand_vs_battery_days"] = round((res["nand_born"] - (bat_up - bat_op * 3600)) / 86400)

# ---- Память: тройная сверка объёма ----
# Объём накопителя записан в трёх независимых местах, и перепаянная память
# или подменённый объём их рассогласует. Проверено на двух аппаратах
# (64 и 128 ГБ): контроллер, модель чипа и заявленный объём сходятся всюду.
# Если запись контроллера не ответила — молчим, а не обвиняем.
cap_ctl = n(deep(nvme, "capacity"))
cap_mod = txt(deep(nvme, "Model Number"))
m = re.search(r"AP(\d{3,4})", cap_mod)
cap_mod_gb = int(m.group(1)) if m else 0
cap_rep = res["storage_gb"]
if cap_ctl and cap_rep:
    sizes = {round(cap_ctl / 10**9), cap_rep}
    if cap_mod_gb: sizes.add(cap_mod_gb)
    res["storage_ok"] = len(sizes) == 1
else:
    res["storage_ok"] = None

# ---- Батарея: физически невозможные показания ----
# Проверено на аппарате, где Apple подтвердила замену батареи на Б/У деталь:
# мои правила её ПРОПУСТИЛИ, а в данных лежали три явные улики.
#
# 1. Ёмкость БОЛЬШЕ заводской. Настоящая батарея Apple с годами деградирует и
#    заводскую расчётную ёмкость не превышает. На том аппарате установленная
#    заявила 3630 мА·ч против заводских 3208 — на 13% больше. Это физически
#    невозможно для родной батареи: неоригинальный контроллер просто врёт,
#    чтобы показать «100% здоровья». Справочник для этой проверки НЕ нужен —
#    обе цифры читаются с самого аппарата, поэтому отравить её нечем.
# 2. Ноль циклов при реальной наработке. Батарея в аппарате 2021 года с нулём
#    циклов и полугодом наработки — это новый пак в старом телефоне.
# 3. Счётчик BatteryCellDisconnectCount показал 0 при фактической замене,
#    то есть замену он НЕ видит. Опираться на него как на признак замены
#    нельзя — оставлен только как признак вскрытия, и то под вопросом.
_des = n(deep(batt, "DesignCapacity"))
_now = n(deep(batt, "NominalChargeCapacity")) or n(deep(batt, "AppleRawMaxCapacity"))
_cyc = res["battery"]["cycles"]
_yrs = n(deep(batt, "TotalOperatingTime")) / 8760 if deep(batt, "TotalOperatingTime") else 0
# Порог двухступенчатый. Причина: в выборке нет ни одной почти новой родной
# батареи (все четыре исправных аппарата дают 76-87% от завода), поэтому
# потолок для родной неизвестен. Заводская ёмкость номинальная, разброс
# производства в несколько процентов нормален. Наблюдено на ремонтных:
# +13% (явная подделка) и +3.3% (пограничный случай).
# Обвинять на +3% нельзя — можно обвинить честного клиента с новой батареей.
batt_fake = []       # уверенное обвинение
batt_doubt = []      # повод посмотреть руками, без обвинения
if _des and _now:
    _r = _now / _des
    # Порог 1.03 обоснован сверкой с вердиктом Apple на шести аппаратах:
    #   три с заменённой батареей (Apple подтвердила, все три на Б/У) — выше 103%;
    #   два с родной батареей (чистый iPhone 15 Pro и iPhone 16 Pro Max, где
    #   менялось только заднее стекло) — ниже 103%.
    # Разделение чистое, поэтому обвинение начинается с 103%, а не с 108%.
    # Выше 108% выделено отдельно: там ошибка исключена (наблюдалось +13%).
    if _r > 1.08:
        batt_fake.append(f"заявляет {_now} мА·ч при заводских {_des} "
                         f"(+{(_r-1)*100:.0f}%) — для родной физически невозможно")
    elif _r > 1.03:
        batt_fake.append(f"заявляет {_now} мА·ч при заводских {_des} "
                         f"(+{(_r-1)*100:.0f}%) — выше заводской, у родной так не бывает")
if _des and _now and _now < _des * 0.45:
    batt_fake.append(f"заявляет {_now} мА·ч при заводских {_des} — ниже любого рабочего предела")
if _cyc == 0 and _yrs > 0.25:
    batt_fake.append(f"ноль циклов при наработке {_yrs:.1f} года — пак новее аппарата")
res["batt_fake"] = batt_fake
res["batt_doubt"] = batt_doubt
if batt_fake:
    parts_verdict["Батарея"] = {"verdict": "НЕОРИГИНАЛ", "why": batt_fake[0]}
elif batt_doubt:
    parts_verdict["Батарея"] = {"verdict": "ПОД ВОПРОСОМ", "why": batt_doubt[0]}

# ---- Батарея: отпечаток модели ----
# Четыре поля батареи постоянны внутри модели и различны между моделями.
# Проверено на двух iPhone 12 с совершенно разными серийниками пака
# (FG92027038HQ68CAT и F8Y21640FF4Q687A3): совпали все четыре.
# Неоригинальный пак почти наверняка ошибётся хотя бы в одном.
#   DesignCapacity          — заводская ёмкость
#   ChemID >> 16            — СТАРШИЕ 16 бит, младшие привязаны к экземпляру
#   AlgoChemID >> 16        — то же
#   Serial[11:14]           — код детали внутри серийника пака
# Модели нет в таблице — проверка просто не выполняется. Выдумывать эталон
# по рекламным цифрам Apple нельзя: для iPhone 12 там 2815, аппараты дают 2798.
# Одно расхождение — ПОД ВОПРОСОМ, два и больше — НЕОРИГИНАЛ: единичное
# отличие может оказаться вариантом поставщика, которых мы ещё не видели.
# ПЯТОЕ ЧИСЛО — на скольких НЕЗАВИСИМЫХ аппаратах эталон подтвердился.
# Это не формальность. Если эталон снят с телефона, где уже стоял китайский
# пак, то эталоном становится подделка — и тогда правило переворачивается:
# каждая РОДНАЯ батарея этой модели помечается неоригинальной. Отравленный
# эталон не пропускает обман, а обвиняет честного клиента, что хуже.
# Поэтому при подтверждении меньше чем на трёх аппаратах вердикт НЕ выносится,
# выводится только справочная строка. refs.sh печатает счётчик сам.
BATT_REF = {
    "iPhone13,2": (2798, 0x3C13, 0x3C1D, "Q68", 2),
    "iPhone14,5": (3208, 0x3C2D, 0x3C3E, "18F", 1),
    "iPhone15,2": (3181, 0x3C5A, 0x3C5A, "21P", 1),
}
BATT_REF_MIN = 3   # сколько аппаратов должно совпасть, чтобы верить эталону
res["batt_ref_n"] = 0; res["batt_mismatch"] = []   # batt_fake/batt_doubt посчитаны выше
ref = BATT_REF.get(res["product_type"])
if ref and batt:
    _des = n(deep(batt, "DesignCapacity"))
    _chem = n(deep(batt, "ChemID")); _algo = n(deep(batt, "AlgoChemID"))
    _sn = txt(deep(batt, "Serial"))
    mism = []
    if _des and _des != ref[0]:                      mism.append("ёмкость")
    if _chem and (_chem >> 16) != ref[1]:            mism.append("химия ячейки")
    if _algo and (_algo >> 16) != ref[2]:            mism.append("алгоритм химии")
    if len(_sn) >= 14 and _sn[11:14] != ref[3]:      mism.append("код детали")
    res["batt_ref_n"] = ref[4]
    res["batt_mismatch"] = mism
    if batt_fake:
        # Уже обвинена по физике — отпечаток только дополняет описание.
        if mism:
            parts_verdict["Батарея"]["why"] += "; расходится с эталоном: " + ", ".join(mism)
    elif ref[4] < BATT_REF_MIN:
        # Эталон слишком тонкий, чтобы на нём обвинять. Молчим о вердикте.
        pass
    elif len(mism) >= 2:
        parts_verdict["Батарея"] = {"verdict": "НЕОРИГИНАЛ",
            "why": "не совпадает с эталоном модели: " + ", ".join(mism)}
    elif mism:
        parts_verdict["Батарея"] = {"verdict": "ПОД ВОПРОСОМ",
            "why": "расходится с эталоном модели: " + mism[0]}

# ---- Апгрейд памяти: номер модели против объёма ----
# Номер модели лежит в syscfg НА ПЛАТЕ и задаёт заводской объём. При перепайке
# памяти 64->256 ГБ телефон честно рапортует НОВЫЙ объём во всех источниках —
# поэтому тройная сверка объёма такой обман не видит, а номер модели видит.
# Таблица копится с витрины: refs.sh печатает строки из журнала приёмок.
# Внешние списки номеров в открытом виде неполны, свои данные полны по тем
# моделям, что реально идут. MGJ53=64 ГБ дополнительно подтверждён извне.
# Номера нет в таблице — проверка молчит, ложного флага не будет.
# Второе число — на скольких НЕЗАВИСИМЫХ аппаратах объём подтверждён.
# Опасность та же, что и с эталоном батареи: если первый встреченный аппарат
# с этим номером был с перепаянной памятью, в таблицу попадёт ЕГО объём, и
# тогда правило начнёт обвинять в апгрейде все честные телефоны этой модели.
# Поэтому ниже порога вердикт не выносится. MGJ53=64 дополнительно сверен с
# внешним источником, остальные три — пока только с одного аппарата каждый.
MODEL_CAP = {
    "MGJ53": (64, 2), "MGJA3": (128, 1), "MLPF3": (128, 1), "MQ1G3": (256, 1),
}
MODEL_CAP_MIN = 3
_mn = re.match(r"([A-Z0-9]{5})", str(res["model_number"] or ""))
_e = MODEL_CAP.get(_mn.group(1)) if _mn else None
_cap, _capn = _e if _e else (None, 0)
res["model_cap_n"] = _capn
res["model_cap_expected"] = _cap
res["model_cap_ok"] = (None if not _cap or not res["storage_gb"] or _capn < MODEL_CAP_MIN
                       else _cap == res["storage_gb"])

# ---- перекрёстные сверки ----
# Один и тот же серийник лежит в реестре в нескольких независимых местах.
# Если они разошлись — данные подменены. Физическую замену детали это НЕ ловит:
# при честной замене изменятся оба места сразу. Это проверка на подлог,
# а не на ремонт. Найдено сравнением двух аппаратов, пары устойчивы на обоих.

crosschecks = []
for name, a, b in (
    ("серийник платы",      i("MLBSerialNumber"),        txt(deep(dtree, "mlb-serial-number"))),
    ("датчик приближения",  txt(deep(prox, "SerialNumber")), txt(deep(prod, "rosaline-serial-num"))),
):
    if a and b:
        crosschecks.append((name, a == b))
res["crosschecks"] = {n: ok for n, ok in crosschecks}

stop, todo, warn = [], [], []
if res["icloud_lock"] == "включён":
    todo.append("«Найти iPhone» включён — клиент должен выйти из Apple ID до сдачи")
if res["icloud_lock"] == "неизвестно": warn.append("статус «Найти iPhone» не определился")
if res["icloud_channels_agree"] is False:
    stop.append("статус «Найти iPhone» различается в двух источниках — данные подменены")
if res["supervised"]:
    stop.append("аппарат под корпоративным надзором (MDM) — перепродать нельзя")
if res["passcode"]: todo.append("на телефоне стоит пароль — попроси клиента снять")
if res["sim"]["inserted"]: todo.append("в телефоне осталась SIM-карта — отдай клиенту")
b = res["battery"]
if 0 < b["health_pct"] < 80: warn.append(f'износ батареи {b["health_pct"]}% — под замену')
if not b["health_pct"]: warn.append("износ батареи не определился — проверь в Настройках вручную")
if b["cycles"] > 800: warn.append(f'{b["cycles"]} циклов — ресурс батареи выработан')
# Счётчик физических отсоединений шлейфа батареи. Ноль — батарею ни разу не
# снимали. Ненулевое значение означает, что аппарат вскрывали: либо меняли
# батарею, либо лазили внутрь. Это признак ВСКРЫТИЯ, а не неисправности,
# поэтому идёт в «влияет на цену», а не в отказ.
# Калибровки нет: аппарата с заведомо менянной батареей в выборке не было,
# поэтому утверждается только факт ненулевого счётчика, без домыслов.
if b["cell_disconnects"]:
    warn.append(f'батарею снимали {b["cell_disconnects"]} раз — аппарат вскрывали')
# Порог по температуре предварительный. На честном iPhone 12 возрастом 4.8 года
# пожизненный максимум 50°C, и прежний порог 45°C давал на нём ложный флаг:
# телефон легко берёт 50°C на зарядке под солнцем. Уточнить по мере набора
# аппаратов через compare.sh.
if b["max_temp_c"] and b["max_temp_c"] >= 55: warn.append(f'батарея грелась до {b["max_temp_c"]}°C')
if res["model_cap_ok"] is False:
    stop.append(f'память перепаяна: по номеру модели {res["model_cap_expected"]} ГБ, '
                f'а стоит {res["storage_gb"]} ГБ')
if res["storage_ok"] is False:
    stop.append("объём памяти не сходится — возможна перепаянная память")
# Переменная названа не n: имя n занято функцией приведения к числу, и
# обычный цикл (в отличие от comprehension) затирал её на весь оставшийся
# модуль. Из-за этого молча падал весь код после — включая запись в журнал.
for _name, ok in res["crosschecks"].items():
    if not ok: stop.append(f"сверка «{_name}» не сошлась — данные аппарата подменены")
for lbl, pv in res["parts_verdict"].items():
    vd = pv["verdict"]
    if vd.startswith("ЗАМЕН") or vd == "СБОИ":
        stop.append(f"{lbl}: {vd.lower()}" + (f" ({pv['why']})" if pv["why"] else ""))
    elif vd == "ПОД ВОПРОСОМ":
        warn.append(f"{lbl}: Apple не подтверждает подлинность")
if res["activation"] != "Activated": warn.append(f'телефон не активирован ({res["activation"]})')
res["stop"], res["todo"], res["warn"] = stop, todo, warn

# Подсистемы, которые не ответили вовсе: нужны и вердикту, и выводу.
silent = [n for n, o in (("камеры", cam), ("дисплей", disp), ("тачскрин", mt)) if not o]

# ---- итоговый вердикт по аппарату ----
# Собирается из вердиктов по деталям. Главное правило: «идеал» не выдаётся,
# если хоть что-то не прочиталось. Отсутствие флагов и отсутствие проблем —
# разные вещи, и путать их здесь опаснее всего: на «идеале» платят больше.
pv = res["parts_verdict"]
no_data   = [l for l, v in pv.items() if v["verdict"] == "НЕТ ДАННЫХ"]
replaced  = [l for l, v in pv.items() if v["verdict"].startswith(("ЗАМЕН", "НЕОРИГ"))]
doubtful  = [l for l, v in pv.items() if v["verdict"] == "ПОД ВОПРОСОМ"]
broken    = [l for l, v in pv.items() if v["verdict"] == "СБОИ"]
opened    = res["battery"]["cell_disconnects"] > 0
hp        = res["battery"]["health_pct"]

if stop:
    overall = ("ПРОБЛЕМНЫЙ", "есть причины не принимать — смотри список ниже")
elif replaced or broken or opened:
    why = []
    if opened:   why.append("батарею снимали")
    if replaced: why.append("заменено: " + ", ".join(replaced))
    if broken:   why.append("сбоит: " + ", ".join(broken))
    overall = ("РЕМОНТИРОВАН", "; ".join(why))
elif no_data or silent:
    # Перечисляем подсистемы, а не каждую деталь: если не ответила запись камеры,
    # в список попадали все пять камер плюс сама «камеры» — читать невозможно.
    GROUP = {"Основная камера": "камеры", "Сверхширокая": "камеры", "Телефото": "камеры",
             "Фронтальная": "камеры", "Face ID": "камеры", "Экран": "дисплей",
             "Батарея": "батарея", "Тачскрин": "тачскрин"}
    missing = sorted({GROUP.get(x, x) for x in no_data} | set(silent))
    overall = ("ПРОВЕРКА НЕПОЛНАЯ",
               "не прочиталось: " + ", ".join(missing) + " — вердикт по аппарату не выдаётся")
elif doubtful:
    overall = ("ПОД ВОПРОСОМ", "сомнения по: " + ", ".join(doubtful))
else:
    # Не умалчиваем, что часть деталей проверить нечем. Иначе «идеал»
    # читается как «всё проверено», хотя экран и фронтальная камера по
    # кабелю не проверяются в принципе.
    unver = [l for l, v in pv.items() if v["verdict"] == "НА МЕСТЕ"]
    tail = (" (не проверяются по кабелю: " + ", ".join(unver).lower() + ")") if unver else ""
    if hp >= 85 and not warn:
        overall = ("ИДЕАЛ", "проверенные детали оригинальные, аппарат не вскрывался" + tail)
    else:
        overall = ("ХОРОШИЙ", "проверенные детали оригинальные, но есть износ" + tail)
res["overall"] = {"verdict": overall[0], "why": overall[1]}

# ---- журнал приёмок ----
# Каждая проверка дописывает строку в журнал. Смысл: через магазин проходят
# десятки телефонов, и раньше результат каждой приёмки просто выбрасывался.
# Теперь обычная работа приёмщика сама копит выборку, причём БЕЗ полного
# сбора: отпечаток батареи новой модели попадает в журнал за 15 секунд, а
# не за 15 минут харвеста. Из журнала потом достаётся строка для BATT_REF.
# Журнал никогда не должен ломать проверку, поэтому всё в try.
try:
    import datetime
    _log = os.path.expanduser("~/Downloads/iphone_diag_log.jsonl")
    # Откуда запись. regress.sh воспроизводит сохранённые описи через эту же
    # логику, и его прогоны попадали в журнал наравне с живыми приёмками —
    # один аппарат выглядел как девять. refs.sh учитывает только «приёмка».
    _rec = {
        "источник": os.environ.get("DIAG_SOURCE", "приёмка"),
        # Что, по словам владельца или по виду, в этом аппарате менялось.
        # Пустая строка — сведений нет, это НЕ значит «ничего не менялось».
        "известный_ремонт": os.environ.get("DIAG_REPAIR", ""),
        "время": datetime.datetime.now().isoformat(timespec="seconds"),
        "udid": res["udid"], "модель": res["product_type"],
        "название": res["model"], "ios": res["ios"],
        "серийник": res["serial"], "номер_модели": res["model_number"],
        "вердикт": res["overall"]["verdict"], "почему": res["overall"]["why"],
        "детали": {k: v["verdict"] for k, v in res["parts_verdict"].items()},
        "износ": res["battery"]["health_pct"], "циклы": res["battery"]["cycles"],
        "снимали_батарею": res["battery"]["cell_disconnects"],
        # отпечаток батареи — чтобы пополнять BATT_REF по новым моделям
        "батарея_эталон": {
            "ёмкость": n(deep(batt, "DesignCapacity")),
            "химия_hi": (n(deep(batt, "ChemID")) or 0) >> 16,
            "алгоритм_hi": (n(deep(batt, "AlgoChemID")) or 0) >> 16,
            "код_детали": txt(deep(batt, "Serial"))[11:14],
        },
        "объём_гб": res["storage_gb"],
        "найти_iphone": res["icloud_lock"], "mdm": res["supervised"],
        "стоп": res["stop"], "сделать": res["todo"], "внимание": res["warn"],
    }
    with open(_log, "a", encoding="utf-8") as _f:
        _f.write(json.dumps(_rec, ensure_ascii=False) + "\n")
except Exception:
    pass

if AS_JSON:
    print(json.dumps(res, ensure_ascii=False)); sys.exit()

p = res["parts"]; v = res["validation"]; t = res["touch"]
print("════════ ПАСПОРТ ════════")
print(f'  Модель          : {res["model"]}  ({pt})')
print(f'  Номер модели    : {res["model_number"]}')
print(f'  Серийный номер  : {res["serial"]}')
print(f'  Серийник платы  : {res["mlb_serial"]}')
print(f'  IMEI            : {res["imei"]}')
if res["imei2"]: print(f'  IMEI 2          : {res["imei2"]}')
print(f'  Цвет            : {res["color"]}')
print(f'  Память          : {res["storage_gb"]} ГБ  (свободно {res["free_gb"]} ГБ)')
print(f'  iOS             : {res["ios"]}')

print("\n════════ БАТАРЕЯ ════════")
if b["design_mah"]:
    if not b["health_pct"]:
        print('  ИЗНОС           : не определился ⚠️ — смотри Настройки вручную')
    else:
        mark = "   ⚠️ под замену" if b["health_pct"] < 80 else ("   ⚠️ на грани" if b["health_pct"] < 85 else "   ✅")
        print(f'  ИЗНОС           : {b["health_pct"]}%{mark}')
    print(f'  Циклов          : {b["cycles"]}' + ("   ⚠️ ресурс выработан" if b["cycles"] > 800 else ""))
    print(f'  Ёмкость         : {b["capacity_mah"]} из {b["design_mah"]} мА·ч заводских')
    print(f'  Серийник батареи: {b["serial"]}')
    if b["operating_years"]: print(f'  Отработала      : ≈{b["operating_years"]} лет')
    # Этот счётчик замену НЕ видит: на аппарате, где Apple подтвердила замену
    # батареи, он показал 0. Поэтому ноль ничего не доказывает, и зелёной
    # галочки здесь быть не должно — иначе приёмщик прочтёт её как «не лазили».
    if b["cell_disconnects"]:
        print(f'  Снимали батарею : {b["cell_disconnects"]} раз   ⚠️ аппарат вскрывали')
    else:
        print('  Снимали батарею : счётчик 0 — замену он не фиксирует, ни о чём не говорит')
    if b["max_temp_c"]: print(f'  Грелась до      : {b["max_temp_c"]}°C' + ("   ⚠️" if b["max_temp_c"] >= 55 else ""))
else:
    print("  не прочиталась")

MARK = {"ОРИГИНАЛ":"✅","ИСПРАВЕН":"✅","НА МЕСТЕ":"➖","ПОД ВОПРОСОМ":"⚠️","СБОИ":"⛔"}
print("\n════════ ДЕТАЛИ ════════")
for lbl in ("Экран","Основная камера","Сверхширокая","Телефото","Фронтальная","Face ID",
            "Батарея","Тачскрин","Taptic Engine"):
    pv = res["parts_verdict"].get(lbl)
    if not pv or pv["verdict"] in ("НЕТ ДАННЫХ", "НЕТ В МОДЕЛИ"):
        continue
    m = MARK.get(pv["verdict"], "⛔")
    tail = f'  — {pv["why"]}' if pv["why"] else ""
    print(f'  {m} {lbl:17}: {pv["verdict"]}{tail}')
if unknown:
    print("  Не проверялось Apple (не повод отказывать): " + ", ".join(unknown))
print("  Сила доказательства разная, и это важно при споре с клиентом:")
print("    Face ID, Taptic   — проверено сопряжение детали с платой или чипом,")
print("                        подделать это, не перепрошив плату, нельзя;")
print("    память            — сверен объём в трёх местах; возраст показан справочно;")
print("    батарея           — сверены ёмкость и циклы с заводскими: ёмкость выше")
print("                        заводской физически невозможна для родной;")
print("    задние камеры     — только наличие серийника, слабее;")
print("    экран, фронталка  — сверки нет, подлинность по кабелю не доказуема.")
print("  Работоспособность камер и динамика кабель не проверяет — это веб-тест.")

if silent:
    print("  ⚠️ НЕ ОТВЕТИЛИ: " + ", ".join(silent) +
          " — по ним вердикта нет, повтори проверку")
nvb = res["nand_vs_battery_days"]
if nvb is not None:
    # БЕЗ ВЕРДИКТА, сознательно. Поле 0x038 выглядело как дата рождения NAND и
    # на трёх аппаратах сходилось с возрастом батареи в пределах 51 суток. Но
    # на четвёртом (iPhone 13, анонс 2021) оно показало февраль 2025 — на 1263
    # суток позже выпуска модели, что для даты изготовления невозможно.
    # Вероятнее всего поле перезаписывается при низкоуровневом восстановлении.
    # А клиент перед сдачей телефон восстанавливает почти всегда — значит
    # правило било бы по честным аппаратам массово, прямо в рабочем потоке
    # приёмки. Вернуть его можно только после опыта: снять 0x038, прогнать
    # DFU-восстановление, снять снова. Переживёт — правило оживает.
    print(f'  ℹ️ Память инициализирована на {abs(nvb)} сут. '
          f'{"позже" if nvb > 0 else "раньше"} начала службы батареи'
          f'   (справочно, вердикт по этому не выносится)')
if res["model_cap_n"] and res["model_cap_n"] < MODEL_CAP_MIN:
    _same = res["model_cap_expected"] == res["storage_gb"]
    print(f'  ⚠️ Заводской объём для номера {res["model_number"]} подтверждён лишь на '
          f'{res["model_cap_n"]} {"аппарате" if res["model_cap_n"] == 1 else "аппаратах"}'
          f' — вердикт об апгрейде не выносится'
          + ("" if _same else f' (в таблице {res["model_cap_expected"]} ГБ, стоит {res["storage_gb"]} ГБ)'))
for _f in res["batt_fake"]:
    print("  ⛔ БАТАРЕЯ: " + _f)
for _f in res["batt_doubt"]:
    print("  ⚠️ БАТАРЕЯ: " + _f)
if res["batt_ref_n"] and res["batt_ref_n"] < BATT_REF_MIN and not res["batt_fake"]:
    _m = res["batt_mismatch"]
    print(f'  ⚠️ Эталон батареи для этой модели подтверждён лишь на '
          f'{res["batt_ref_n"]} {"аппарате" if res["batt_ref_n"] == 1 else "аппаратах"}'
          f' — вердикт по подлинности батареи не выносится'
          + (f' (расхождение: {", ".join(_m)})' if _m else ' (расхождений нет)'))
if res["model_cap_ok"] is False:
    print(f'  ⛔ АПГРЕЙД ПАМЯТИ: номер модели {res["model_number"]} — это '
          f'{res["model_cap_expected"]} ГБ с завода, а стоит {res["storage_gb"]} ГБ')
elif res["model_cap_ok"]:
    print(f'  ✅ Объём соответствует номеру модели ({res["model_cap_expected"]} ГБ)')
if res["storage_ok"] is False:
    print("  ⛔ ОБЪЁМ ПАМЯТИ НЕ СХОДИТСЯ — возможна перепаянная память")
elif res["storage_ok"]:
    print(f'  ✅ Объём памяти сходится в трёх местах ({cap_rep} ГБ)')

if crosschecks:
    bad = [n for n, ok in crosschecks if not ok]
    if bad:
        print("  ⛔ СВЕРКА НЕ СОШЛАСЬ: " + ", ".join(bad) + " — данные подменены")
    else:
        print("  ✅ Перекрёстные сверки сошлись (" +
              ", ".join(n for n, _ in crosschecks) + ")")
print("  Серийники модулей — в режиме --json")

print("\n════════ ЭКРАН И ТАЧСКРИН ════════")
# Ноль здесь означает «не прочиталось», а не «ноль герц» — показываем это явно.
sr = f', опрос {t["scan_rate"]} Гц' if t["scan_rate"] else " (частота опроса не читается)"
print(f'  Сетка сенсора   : {t["rows"]}×{t["cols"]}{sr}')
print(f'  Сбросов         : {t["resets"]}   Критических ошибок: {t["critical_errors"]}'
      + ("   ⚠️" if t["critical_errors"] else "   ✅"))
print(f'  Wi-Fi чип       : {res["wifi_chipset"]}')

sm = res["sim"]
print("\n════════ SIM ════════")
print(f'  Тип             : {sm["kind"]}   → в сделку: «{sm["bot_value"]}»')
print(f'  Лоток           : {sm["tray"]}')
print(f'  Сейчас          : {sm["status"]}' + ("   📋 вернуть клиенту" if sm["inserted"] else ""))
print(f'  Поддержка eSIM  : {"да (есть второй IMEI)" if sm["esim_capable"] else "нет"}')
if sm["mcc"] or sm["mnc"]: print(f'  Оператор        : MCC {sm["mcc"]} / MNC {sm["mnc"]}')
if sm["baseband"]: print(f'  Модем           : {sm["baseband"]}')

print("\n════════ ЮРИДИЧЕСКИЙ СТАТУС ════════")
print("  Найти iPhone          : " + {"выключен":"✅ выключен, можно принимать",
       "включён":"⚠️ ВКЛЮЧЁН — клиент должен выйти из Apple ID"}
      .get(res["icloud_lock"], "не определилось"))
if res["icloud_channels_agree"] is False:
    print("  Сверка двух каналов   : ⛔ РАСХОЖДЕНИЕ — данные подменены")
print("  Корпоративный надзор  : " +
      ("⛔ ЕСТЬ (MDM) — перепродать нельзя" if res["supervised"] else "✅ нет"))
print(f'  Активирован           : {res["activation"]}')
print(f'  Пароль на телефоне    : {"стоит — попроси снять" if res["passcode"] else "нет"}')


MARK_ALL = {"ИДЕАЛ": "🟢", "ХОРОШИЙ": "🟢", "РЕМОНТИРОВАН": "🟡",
            "ПОД ВОПРОСОМ": "🟡", "ПРОВЕРКА НЕПОЛНАЯ": "⚪", "ПРОБЛЕМНЫЙ": "🔴"}
print("\n════════ ВЕРДИКТ ПО АППАРАТУ ════════")
print(f"  {MARK_ALL[overall[0]]} {overall[0]}")
print(f"     {overall[1]}")

print("\n════════ ИТОГ ════════")
if stop:
    print("  ⛔ НЕ ПРИНИМАТЬ:")
    for x in stop: print(f"     • {x}")
if todo:
    print("  📋 Сделать до приёмки:")
    for x in todo: print(f"     • {x}")
if warn:
    print("  ⚠️ Влияет на цену / проверить:")
    for x in warn: print(f"     • {x}")
if not stop and not todo and not warn: print("  ✅ Замечаний нет")
PY
