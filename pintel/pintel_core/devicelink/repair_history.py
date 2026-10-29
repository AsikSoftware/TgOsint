# -*- coding: utf-8 -*-
"""Вердикт Apple «Запчасти и история обслуживания» — из системного журнала.

По USB вердикт не отдаётся никем (проверено: lockdown-домены, IORegistry,
MobileGestalt — пусто; вопрос в libimobiledevice #1301 без ответа с 2022).
Но его пишет в журнал сам телефон при ПЕРЕХОДЕ в раздел Настройки → Основные →
Об этом устройстве → Запчасти и история обслуживания (на iOS 26 — процесс
Preferences(CoreRepairCore), строка repairHistoryForUI:{…CRRepairHistoryItem…}).
Уже открытый экран отдаёт кэш — нужен именно переход внутрь.

Слушатель (Listener) живёт всё время, пока телефон на кабеле: стартует сразу
после «Доверять», переподключается при обрыве потока (на живом iPhone 12 поток
обрывался через ~20 с) и собирает записи, когда бы клиент ни открыл раздел.

ДВА ФОРМАТА (сверено по живым аппаратам):
  iOS 26   — Preferences(CoreRepairCore): repairHistoryForUI:{ … CRRepairHistoryItem … }
             — список деталей с isRepaired/isUsed, даже если ничего не меняли.
  iOS 18.7 — таких строк НЕТ. corerepaird сверяет живые детали с заводской
             печатью (FDR seal) и пишет:
               fetched RCHL successfully: (null) length = 0   — список ремонтов Apple пуст
               No delta components found / delta components: { }  — отличий от печати нет
             Пустая дельта + пустой RCHL = Apple не нашёл ни замен, ни ремонтов.
             Непустая дельта = детали, которых нет в печати («неизвестная деталь»).
"""
import asyncio
import re
import time

from pymobiledevice3.services.syslog import SyslogService

RU = {"Battery": "Аккумулятор", "Display": "Экран", "Camera": "Камера",
      "FaceID": "Face ID", "MTUB": "Верхний модуль", "LogicBoard": "Материнская плата",
      "BackGlass": "Заднее стекло", "Enclosure": "Корпус", "RearSystem": "Задняя система",
      "FrontCamera": "Фронтальная камера", "RearCamera": "Основная камера"}

# Код 1029 встречался и как MTUB, и как LogicBoard — опираемся на ИМЯ.
# Запись разбираем как набор полей «ключ:значение:», а не жёстким шаблоном: Apple может
# добавить поле (например, о неизвестной детали), и его нельзя молча потерять.
ITEM = re.compile(r"componentName:(\w+):((?:\s*\w+:[^:\n\]\"]*:)*)")
FIELD = re.compile(r"(\w+):([^:\n\]\"]*):")
KNOWN_FIELDS = ("componentType", "isRepaired", "isUsed", "repairDate")
# Модели, у которых Apple ведёт «Запчасти и история обслуживания»: iPhone XR/XS и новее
# (ProductType iPhone11,x и выше), iOS 15.2+. У iPhone X и старше раздела нет вообще —
# ждать клиента бессмысленно.
def supported(product_type, ios_version):
    """→ (True/False, причина)."""
    import re as _re
    m = _re.match(r"iPhone(\d+),", str(product_type or ""))
    if not m:
        return False, "не iPhone"
    if int(m.group(1)) < 11:
        return False, "у этой модели Apple не ведёт историю обслуживания (iPhone X и старше)"
    parts = [int(x) for x in _re.findall(r"\d+", str(ios_version or ""))[:2]] + [0, 0]
    if (parts[0], parts[1]) < (15, 2):
        return False, "историю обслуживания Apple показывает с iOS 15.2"
    return True, ""


# Подтвердить подлинность детали телефон может только там, где пишет словарь состояния
# (systemhealth) или сверку с заводской печатью. По прошивкам (прочитаны целиком):
#   15.2.1 — словаря НЕТ, только отказы isTrustedForUI и preflight;
#   15.6.1 — словарь «systemhealth %@» уже ЕСТЬ, как и во всех версиях дальше.
# Где именно он появился между 15.3 и 15.5, мы не проверяли, поэтому граница стоит по
# доказанному: до 15.6 подтверждения не обещаем. Ошибка в эту сторону безопасна — мы
# просим сотрудника сверить экран там, где, возможно, справилась бы автоматика; обратная
# ошибка заставила бы ждать вердикта, которого телефон не отдаст.
ПОДТВЕРЖДЕНИЕ_С = (15, 6)


def подтверждение_возможно(ios_version):
    """Может ли эта версия iOS вообще подтвердить, что деталь оригинальная. → True/False."""
    import re as _re
    parts = [int(x) for x in _re.findall(r"\d+", str(ios_version or ""))[:2]] + [0, 0]
    return (parts[0], parts[1]) >= ПОДТВЕРЖДЕНИЕ_С


# ---------------------------------------------------------------- iOS 26: проверка компонентов
# На iPhone 15 Pro (iOS 26.6.1) экран показывал «Дисплей — Неизвестно», а записи
# CRRepairHistoryItem пришли со всеми нулями: это НЕ вердикт, а список ремонтов Apple
# (их на аппарате не было). Сам вердикт телефон пишет отдельными строками, и они
# совпали с экраном слово в слово:
#   systemhealth { … Display = "-1"; … }      значения сверены на ДВУХ эталонах:
#       1  — деталь в порядке (чистый iPhone 14 Pro: Battery/Display/Camera/FaceID = 1)
#      -1  — деталь не подтверждена; на экране телефона «Неизвестно» (15 Pro: Display)
#       0  — Apple её у этой модели не отслеживает (BackGlass: 1 у 15 Pro, 0 у 14 Pro)
#      RCameraFailed = 1 стоит и на чистом аппарате — смысл не ясен, вердикт по нему не строим
#   mobilerepaird: Display failed preflight    явный отказ по детали
#   component: X isComponentRepairedUsingRCHL|FDR|CAA: 1   ремонт Apple по этой детали
#   Battery Health State{ IOPSBatteryHealthServiceState = 1 }  аккумулятор требует обслуживания (износ, не замена)
#   AuthCP Components { ComponentName = TouchController; isTrusted = 0 }  модуль не доверенный
#      Второй источник того же вердикта, сверен на тех же двух аппаратах: у 15 Pro дисплей
#      пришёл с isTrusted = 0, у чистого 14 Pro — с 1, при AuthPassed = 1 у обоих. Держим как
#      страховку: если на другой iOS не окажется строк systemhealth, вердикт даст это.
SYSHEALTH_RE = re.compile(r"systemhealth \{(.*?)\n\}", re.S)
REPAIRED_RE = re.compile(r"component: (\w+) isComponentRepairedUsing(\w+): (\d)")
# iOS 26 пишет «Display failed preflight», а в прошивке iOS 17.7 строка другая:
# «%{public}@ result: failed preflight checks». Ловим обе, иначе на iOS 17 отказ по детали
# прошёл бы мимо: имя компонента стоит перед «result:», а не перед «failed».
PREFLIGHT_RE = re.compile(r"\b(\w+)(?:\s+result:)?\s+failed preflight")
AUTHCP_RE = re.compile(r"(?:AuthCP )?Components: \((.*?)\n\)", re.S)
BATTERY_STATE_RE = re.compile(r"Battery Health State\{(.*?)\n\}", re.S)
# iOS 15 и 16 пишут доверие к модулю отдельной строкой, а не словарём AuthCP: в прошивках
# есть «isTrustedForUI: %@», «isTrustedForUI failed» и ключи аналитики
# com.apple.accessories.hwComponent.isTrustedForUI.failure.battery_/.display_ — то есть
# на этих версиях отказ по детали приходит именно так. «missing» вердиктом НЕ считаем:
# это внутреннее «ключа нет», а не «деталь не наша».
TRUST_LINE_RE = re.compile(r"\b(\w+)\s+isTrustedForUI(?::\s*(\w+)|\s+(failed))")
# Живого аппарата на iOS 15–17 у нас нет, поэтому порядок слов в строке мы знаем только из
# формата «isTrustedForUI: %@» — а что стоит ПЕРЕД ним, прошивка не говорит. Чтобы отказ не
# прошёл мимо из-за порядка слов, ловим его отдельно и имя детали ищем в любом месте строки.
# Если деталей в строке несколько или ни одной — вердикт не ставим: приписать отказ не к той
# детали хуже, чем не прочитать его вовсе.
TRUST_FAIL_RE = re.compile(r"isTrustedForUI(?:\s*[:=]\s*(?:0|false|no)\b|\s+failed)", re.I)
# Страховка на будущие версии. Apple уже трижды меняла слова (iOS 16 — systemhealth,
# 18 — delta components, 26 — isComponentRepairedUsing), и каждый раз мы узнавали об этом
# по живому аппарату. Форма при этом не менялась: процесс CoreRepair печатает блок
# «Имя = число;» по деталям. Ловим ЛЮБОЙ такой блок, даже если слово новое.
# ВАЖНО: по неизвестному формату мы не выдаём подтверждения Apple — только ловим плохие
# детали. Неизвестное обязано делать проверку строже, а не разрешать зелёный.
ANY_DICT_RE = re.compile(r"([\w.]+)\s*\{(.*?)\n\}", re.S)
МИНИМУМ_ДЕТАЛЕЙ = 2
# iOS 16 пишет ремонт Apple одной записью на событие, а не по деталям:
# «[CRRepairHistory: timeStr:…: repairDate:… repairCenter:…: dataClasses:…:»
# timeStr содержит двоеточия времени, поэтому до «: repairDate:» идём нежадно
CRHIST_RE = re.compile(r"CRRepairHistory: timeStr:(.*?): repairDate:(\S*) repairCenter:(.*?):")
# «fetched RCHL successfully: (null) length = 0» (iOS 18) и «fetched RCHL successfully:%@»
# (iOS 16) — во втором случае длины нет вовсе, но непустая выдача уже значит, что записи есть
RCHL_ANY_RE = re.compile(r"fetched RCHL successfully:\s*(\S*)")
_KV_RE = re.compile(r'^\s*"?([A-Za-z]\w*)"?\s*=\s*"?(-?\d+)"?\s*;', re.M)
# Имена компонентов телефона → наши детали
COMPONENT_ALIAS = {"CoverGlass": "Display", "TouchController": "Display", "RCamera": "Camera",
                   "FrontCamera": "FrontCamera", "LogicBoard": "LogicBoard"}
# Что из systemhealth вообще считаем деталью (остальное — узлы связи и звук)
HEALTH_PARTS = {"Battery", "Display", "Camera", "FaceID", "BackGlass", "MTUB", "Enclosure",
                "CoverGlass", "TouchID", "FrontCamera", "LogicBoard"}

# Сила формата: по ней решается, какой источник главнее, когда их несколько. На iOS 26
# записи и словарь состояния приходят ОДНИМ всплеском, и до этой правки запись, пришедшая
# второй, затирала вердикт проверки компонентов целиком: тот же телефон давал «замену» или
# «все детали родные» в зависимости от порядка строк в журнале.
СИЛА_ФОРМАТА = (("проверка компонентов", 3), ("сверка с заводской печатью", 3),
                ("заключение FDR", 3),
                ("записи обслуживания", 2), ("записи о ремонте", 2),
                ("новый формат словаря", 1), ("доверие к модулям", 1))


def сила_формата(fmt):
    for начало, вес in СИЛА_ФОРМАТА:
        if str(fmt or "").startswith(начало):
            return вес
    return 0


# Сколько строк журнала кладём в слепок. Из 400 у iPhone Air на iOS 27 не поместились
# строки проверки компонентов, и по такому слепку разбор уже не повторить — а именно по
# ним мы и чиним разбор, когда он ошибся. Эталон при этом весит сотню килобайт.
ПРЕДЕЛ_СТРОК = 1500
MARKER = "CRRepairHistoryItem"
RELATED = ("repair", "CoreRepair", "mobilerepaird")
# признаки, что раздел на телефоне открыт (iOS 18): UI Настроек и демон проснулись
OPENED = ("updateSpecifiersWithCompletionHandler", "corerepair.preflightControl", "Getting local sealing manifest",
          "fetched RCHL", "delta components", "No delta components found", "repairHistoryForUI",
          "Preferences(CoreRepair", "CoreRepairUI", "Unsealed:", "systemhealth", "isComponentRepairedUsing",
          "failed preflight", "AuthCP Components", "isTrustedForUI", "CRRepairHistory")
# детали, которые показывает раздел на iOS 18 у всех моделей с Face ID
BASE_COMPONENTS = ("Battery", "Display", "Camera", "FaceID")
DELTA_RE = re.compile(r"delta components:\s*\{(.*?)\}\s*$", re.S)
UNSEALED_RE = re.compile(r"Unsealed:\s*\{(.*?)\}\s*$", re.S)
RCHL_RE = re.compile(r"fetched RCHL successfully:.*?length = (\d+)")
SEAL_RE = re.compile(r"_copyIdentifierListForSealingMapEntry: Using value (.+?) for key (\w+) from query cache")
# iOS 18 пишет вывод словами: «FDR data indicates no repair happened on this device.»
# Это и есть ответ Apple на вопрос «был ли ремонт», тот же, что видно в разделе на экране.
FDR_ИТОГ = re.compile(r"FDR data indicates (.+?)\.?\s*$", re.I | re.M)
FDR_БЕЗ_РЕМОНТА = re.compile(r"no repair happened", re.I)
FDR_ПРОВЕРКА = re.compile(r"FDR Validation status:\s*(\w+)", re.I)


def _dict_keys(body):
    """Ключи верхнего уровня из печати словаря Apple: '    Display =     {…};' → Display."""
    keys, depth = [], 0
    for ln in body.split("\n"):
        if depth == 0:
            m = re.match(r"^\s*\"?([A-Za-z]\w*)\"?\s*=", ln)
            if m:
                keys.append(m.group(1))
        depth += ln.count("{") + ln.count("(") - ln.count("}") - ln.count(")")
        depth = max(depth, 0)
    return keys


def parse_delta(line):
    """'delta components: {\n    Display = …;\n}' → ['Display']; пустые скобки → []; не та строка → None."""
    m = DELTA_RE.search(line)
    return _dict_keys(m.group(1)) if m else None


def parse_unsealed(line):
    m = UNSEALED_RE.search(line)
    return _dict_keys(m.group(1)) if m else None


def synthesize(meta):
    """Итог по сверке с заводской печатью:
      дельта пуста и RCHL пуст      → базовые детали «не меняли»
      дельта пуста, RCHL не пуст    → у Apple есть записи о ремонте, но в журнал они не вышли:
                                      вердикт «есть записи» (не «всё родное»!)
      дельта/Unsealed не пусты       → эти детали «неизвестного происхождения».

    Достаточно ЛЮБОЙ из двух строк. В прошивке iOS 17.7 (iPhone15,2) есть `Unsealed: %@`,
    а строки `delta components` нет вовсе — раньше по такому журналу вердикт не собирался
    вообще, то есть целое поколение iOS молча уходило в «проверка неполная»."""
    delta, unsealed = meta.get("дельта"), meta.get("unsealed")
    if delta is None and unsealed is None:
        return {}
    unknown = list(dict.fromkeys(list(delta or []) + list(unsealed or [])))
    rchl = meta.get("rchl_байт") or (1 if meta.get("rchl_непусто") else None)
    items = {}
    if rchl:
        items["RepairRecords"] = {"деталь": "Записи о ремонте Apple", "код": 0, "меняли": True, "бу": False,
                                  "дата": "", "записи_без_деталей": True, "источник": "сверка с заводской печатью"}
    elif rchl == 0 or rchl is None:
        for comp in BASE_COMPONENTS:
            items[comp] = {"деталь": RU.get(comp, comp), "код": 0, "меняли": False, "бу": False, "дата": "",
                           "источник": "сверка с заводской печатью"}
    for comp in unknown:
        items[comp] = {"деталь": RU.get(comp, comp), "код": 0, "меняли": True, "бу": False, "дата": "",
                       "неизвестная": True, "источник": "сверка с заводской печатью"}
    return items


def _flag(v):
    return str(v).strip().lower() in ("1", "true", "yes")


def parse(text):
    """Записи CRRepairHistoryItem → {компонент: {...}}. Одна и та же запись печатается
    несколько раз (кэш, затем после загрузки списка ремонтов), поэтому признаки
    накапливаются: раз помеченное «меняли»/«б/у»/«неизвестная» поздней строкой не снимается,
    дата берётся первая непустая. Неизвестные поля сохраняются в «поля»."""
    items = {}
    for m in ITEM.finditer(text):
        comp, body = m.groups()
        f = dict(FIELD.findall(body))
        date = re.sub(r"\\U([0-9a-fA-F]{4})", lambda g: chr(int(g.group(1), 16)), f.get("repairDate", "").strip())
        if date in ("(null)", ""):
            date = ""
        extra = {k: v.strip() for k, v in f.items() if k not in KNOWN_FIELDS}
        low = {k.lower(): v for k, v in extra.items()}
        unknown = any(_flag(v) for k, v in low.items() if "unknown" in k or "unseal" in k or "nongenuine" in k)
        unknown = unknown or any(not _flag(v) for k, v in low.items() if k in ("isgenuine", "genuine"))
        serviced = any(_flag(v) for k, v in low.items() if "service" in k or "replaced" in k)
        cur = items.get(comp) or {"деталь": RU.get(comp, comp), "код": 0, "меняли": False, "бу": False, "дата": ""}
        try:
            cur["код"] = int(f.get("componentType") or cur["код"])
        except ValueError:
            pass
        cur["меняли"] = cur["меняли"] or _flag(f.get("isRepaired")) or serviced or unknown
        cur["бу"] = cur["бу"] or _flag(f.get("isUsed"))
        cur["дата"] = cur["дата"] or date
        if unknown:
            cur["неизвестная"] = True
        if extra:
            cur["поля"] = {**cur.get("поля", {}), **extra}
        items[comp] = cur
    return items


def signature(items):
    """Отпечаток записей — чтобы заметить, что вердикт изменился после повторной печати."""
    import json
    return json.dumps(items or {}, sort_keys=True, ensure_ascii=False)


def parse_components(text):
    """Строки проверки компонентов (iOS 26) → что телефон думает о каждой детали.
    → {детали: {ключ: {...}}, здоровье: {...}, ремонты: {...}, доверие: {...},
       преflight: [...], аккумулятор: {...}}. Пусто — таких строк не было."""
    out = {"детали": {}, "здоровье": {}, "ремонты": {}, "доверие": {}, "преflight": [], "аккумулятор": {}}

    def part(name):
        return COMPONENT_ALIAS.get(name, name)

    def item(key, источник="проверка компонентов"):
        """Источник у детали разный, и это важно: словарь состояния — подтверждение Apple,
        а одна строка доверия к модулю подтверждением НЕ является. Иначе «Battery
        isTrustedForUI: 1» на iOS 15 выдала бы зелёный по всему аппарату."""
        it = out["детали"].setdefault(key, {"деталь": RU.get(key, key), "код": 0, "меняли": False,
                                            "бу": False, "дата": "", "источник": источник})
        if источник == "проверка компонентов":
            it["источник"] = источник                 # словарь состояния сильнее доверия
        return it

    m = SYSHEALTH_RE.search(text)
    if not m:
        # слова не узнали — ищем словарь по форме: блок, где не меньше двух НАШИХ деталей
        # и все значения числовые. Такой набор ключей больше нигде в журнале не встречается.
        for имя, тело in ANY_DICT_RE.findall(text):
            пары = _KV_RE.findall(тело)
            свои = [k for k, _ in пары if k in HEALTH_PARTS or COMPONENT_ALIAS.get(k) in HEALTH_PARTS]
            if len(пары) >= МИНИМУМ_ДЕТАЛЕЙ and len(свои) >= МИНИМУМ_ДЕТАЛЕЙ and \
                    any(k in ("Battery", "Display", "CoverGlass", "TouchController") for k in свои):
                out["новый_формат"] = имя[:40]
                for name, val in пары:
                    key = part(name)
                    if (key in HEALTH_PARTS or name in HEALTH_PARTS) and int(val) < 0:
                        it = item(key, "новый формат")       # подтверждения не даём, только СТОП
                        it["меняли"], it["неизвестная"] = True, True
                    out["здоровье_по_форме"] = out.get("здоровье_по_форме", {})
                    out["здоровье_по_форме"][name] = int(val)
                break
    if m:
        for name, val in _KV_RE.findall(m.group(1)):
            out["здоровье"][name] = int(val)
            key = part(name)
            if key not in HEALTH_PARTS and name not in HEALTH_PARTS:
                continue
            if int(val) < 0:                      # -1 = деталь не подтверждена, на экране «Неизвестно»
                it = item(key)
                it["меняли"], it["неизвестная"] = True, True
            elif int(val) > 0:
                item(key)                         # 1 = в порядке; 0 = не оценивалась, молчим
    for name, канал, val in REPAIRED_RE.findall(text):
        out["ремонты"].setdefault(part(name), {})[канал] = int(val)
        if int(val):
            it = item(part(name))
            it["меняли"] = True
    for name in PREFLIGHT_RE.findall(text):
        key = part(name)
        if key in HEALTH_PARTS or name in HEALTH_PARTS:
            out["преflight"].append(key)
            it = item(key)
            it["меняли"], it["неизвестная"] = True, True
    m = AUTHCP_RE.search(text)
    if m:
        for block in re.split(r"\}\s*,?", m.group(1)):
            kv = dict(_KV_RE.findall(block))
            nm = re.search(r"ComponentName\s*=\s*(\w+)", block)
            if nm:
                out["доверие"][part(nm.group(1))] = {k: int(v) for k, v in kv.items()}
    for name, val, fail in TRUST_LINE_RE.findall(text):
        key = part(name)
        if key in HEALTH_PARTS or name in HEALTH_PARTS:
            плохо = bool(fail) or str(val).strip().lower() in ("0", "false", "no")
            out["доверие"].setdefault(key, {})["isTrustedForUI"] = 0 if плохо else 1
    for строка in text.splitlines():
        if not TRUST_FAIL_RE.search(строка):
            continue
        названные = {part(k) for k in list(HEALTH_PARTS) + list(COMPONENT_ALIAS)
                     if re.search(rf"\b{k}\b", строка)}
        if len(названные) == 1:
            out["доверие"].setdefault(названные.pop(), {})["isTrustedForUI"] = 0
        else:
            out.setdefault("доверие_без_детали", []).append(строка.strip()[-120:])
    # Доверие к модулю — второй источник того же вердикта. Смысл подтверждён на двух эталонах:
    # у 15 Pro с «Неизвестно» на экране TouchController (это дисплей) пришёл с isTrusted = 0,
    # у чистого 14 Pro — с 1, при AuthPassed = 1 у обоих (значит дело не в самой проверке подписи).
    # Держим как страховку: если на другой iOS не окажется строк systemhealth, вердикт даст это.
    for key, vals in out["доверие"].items():
        if (key in HEALTH_PARTS) and (vals.get("isTrusted") == 0 or vals.get("isTrustedForUI") == 0):
            it = item(key, "доверие к модулю")
            it["меняли"], it["неизвестная"] = True, True
    m = BATTERY_STATE_RE.search(text)
    if m:
        out["аккумулятор"] = {k: int(v) for k, v in _KV_RE.findall(m.group(1))}
    return out if any(out.get(k) for k in ("детали", "здоровье", "ремонты", "преflight",
                                           "аккумулятор", "здоровье_по_форме",
                                           # строку, которую не смогли приписать детали, тоже
                                           # возвращаем: она уедет в эталон и поможет разобрать
                                           "доверие_без_детали")) else {}


class Listener:
    """Непрерывное чтение журнала с переподключением.

    items — разобранные записи (пусто, пока раздел не открыли)
    raw   — сырые строки с записями + заметки об обрывах + (если записей нет)
            строки, похожие на тему, чтобы разбираться по файлу, а не по догадке
    """

    def __init__(self, ld, log=None, max_reconnects=30, reconnect_delay=1.0):
        self.ld, self.log = ld, (log or (lambda *_: None))
        self.max_reconnects, self.reconnect_delay = max_reconnects, reconnect_delay
        self.items, self.buf, self.notes, self.related = {}, [], [], []
        # метаданные формата iOS 18: раздел открыт?, дельта, размер RCHL, значения печати
        self.meta = {"раздел_открыт": False, "дельта": None, "unsealed": None, "rchl_байт": None, "печать": {},
                     "формат": None, "строк_по_теме": 0, "компоненты": None}
        self.last_related_at = None
        self.found_at = None
        self.connects = 0
        self.reconnects = 0
        self.lines = 0
        self._task = None
        self._stop = False

    async def start(self):
        self._task = asyncio.create_task(self._run())
        return self

    async def _run(self):
        while not self._stop and self.reconnects <= self.max_reconnects:
            svc = SyslogService(self.ld)
            try:
                await svc.connect()
                self.connects += 1
                async for line in svc.watch():
                    if self._stop:
                        break
                    self._feed(line)
                else:
                    raise EOFError("поток журнала закончился")
            except asyncio.CancelledError:
                raise
            except Exception as e:                      # noqa: BLE001
                if self._stop:
                    break
                self.reconnects += 1
                note = f"# syslog оборвался ({type(e).__name__}: {e}), переподключение {self.reconnects}\n"
                self.notes.append(note)
                self.log(note.strip())
                await asyncio.sleep(self.reconnect_delay)
            finally:
                try:
                    await svc.close()
                except Exception:                       # noqa: BLE001
                    pass
            if self._stop:
                break

    def _feed(self, line):
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        self.lines += 1
        if MARKER in line:
            self.buf.append(line if line.endswith("\n") else line + "\n")
            parsed = parse("".join(self.buf))
            if parsed:
                self._слить(parsed)              # не затирать: вердикт мог прийти раньше записей
                self._apply_seal()
                self._формат("записи обслуживания (iOS 26)")
                self.meta["раздел_открыт"] = True
                self.last_related_at = time.monotonic()
                if not self.found_at:
                    self.found_at = time.monotonic()
                    self.log(f"история Apple: {len(self.items)} записей")
            return
        low = line.lower()
        if not any(k.lower() in low for k in RELATED):
            return
        self.meta["строк_по_теме"] += 1
        self.last_related_at = time.monotonic()
        if len(self.related) < ПРЕДЕЛ_СТРОК:
            self.related.append(line[:600])
        else:
            self.meta["строк_обрезано"] = self.meta.get("строк_обрезано", 0) + 1
        if any(k in line for k in OPENED) and not self.meta["раздел_открыт"]:
            self.meta["раздел_открыт"] = True
            self.log("на телефоне открыт раздел «Об этом устройстве» / история обслуживания")
        похоже_на_словарь = "{" in line and "=" in line and ";" in line
        if похоже_на_словарь or any(k in line for k in (
                "systemhealth", "isComponentRepairedUsing", "failed preflight",
                "AuthCP Components", "Components: (", "ComponentName",
                "Battery Health State", "isTrustedForUI")):
            self.buf.append(line if line.endswith("\n") else line + "\n")
            self._apply_components()
        m = RCHL_RE.search(line)
        if m:
            self.meta["rchl_байт"] = int(m.group(1))
        else:
            m = RCHL_ANY_RE.search(line)
            if m and m.group(1) and not m.group(1).startswith("(null)"):
                self.meta["rchl_непусто"] = True        # длины нет (iOS 16), но выдача непустая
        m = CRHIST_RE.search(line)
        if m:
            self._apply_repair_record(m.group(2).strip(), m.group(3).strip())
        m = SEAL_RE.search(line)
        if m and len(self.meta["печать"]) < 60:
            self.meta["печать"][m.group(2)] = m.group(1)[:120]
        if "No delta components found" in line and self.meta["дельта"] is None:
            self.meta["дельта"] = []
        m = FDR_ПРОВЕРКА.search(line)
        if m:
            self.meta["fdr_печать"] = m.group(1)          # Pass — заводская печать сошлась
        m = FDR_ИТОГ.search(line)
        if m:
            self.meta["fdr"] = m.group(1).strip()[:120]
            if FDR_БЕЗ_РЕМОНТА.search(m.group(1)):
                # Apple сказала прямым текстом: ремонта не было. Это тот же вывод, что
                # даёт пустая «delta components», только словами — и на втором заходе в
                # раздел телефон печатает ТОЛЬКО его: словарь печати он не повторяет.
                if self.meta["дельта"] is None:
                    self.meta["дельта"] = []
        delta = parse_delta(line)
        if delta is not None:
            self.meta["дельта"] = delta
            self.buf.append(line if line.endswith("\n") else line + "\n")
        unsealed = parse_unsealed(line)
        if unsealed is not None:
            self.meta["unsealed"] = unsealed
            if unsealed:
                self.buf.append(line if line.endswith("\n") else line + "\n")
        if (self.meta["дельта"] is not None or self.meta["unsealed"] is not None) and not self.items:
            self._слить(synthesize(self.meta))
            self._формат("заключение FDR: ремонта не было (iOS 18)" if self.meta.get("fdr")
                         and not self.meta.get("печать") else "сверка с заводской печатью (iOS 17/18)")
            if self.items and not self.found_at:
                self.found_at = time.monotonic()
                замен = len(self.meta["дельта"] or []) + len(self.meta["unsealed"] or [])
                self.log(f"история Apple (сверка с печатью): замен {замен}, "
                         f"RCHL {self.meta['rchl_байт']}")
        elif self.items and (delta is not None or unsealed is not None):
            self._apply_seal()                     # записи уже есть — сверка их дополняет, а не теряется

    def _формат(self, новый):
        """Поставить формат, только если он не слабее уже стоящего: по формату решается
        право выдать зелёный, и слабый источник не имеет права вытеснить сильный."""
        if сила_формата(новый) >= сила_формата(self.meta.get("формат")):
            self.meta["формат"] = новый

    def снимок(self):
        """Копия разобранного для вызывающего. Слияние меняет записи на месте, а значит
        без копии отчёт, собранный по раннему вердикту, молча поменялся бы задним числом,
        когда телефон допечатает журнал."""
        return {k: dict(v) for k, v in self.items.items()}

    def _слить(self, новые):
        """Добавить разобранное к тому, что уже есть. Признаки «меняли», «б/у» и
        «неизвестная» только накапливаются: раз телефон сказал про деталь плохое, поздняя
        строка этого не отменяет — иначе порядок строк в журнале решал бы вердикт."""
        for key, it in новые.items():
            cur = self.items.get(key)
            if cur is None:
                self.items[key] = dict(it)
                continue
            cur["меняли"] = bool(cur.get("меняли")) or bool(it.get("меняли"))
            cur["бу"] = bool(cur.get("бу")) or bool(it.get("бу"))
            if it.get("неизвестная"):
                cur["неизвестная"] = True
            if it.get("записи_без_деталей"):
                cur["записи_без_деталей"] = True
            for поле in ("дата", "код", "центр"):
                if it.get(поле) and not cur.get(поле):
                    cur[поле] = it[поле]
            cur.setdefault("источник", it.get("источник", ""))

    def _apply_components(self):
        """Вердикт iOS 26 из строк проверки компонентов. Он главнее записей о ремонтах:
        записи говорят, что Apple чинила, а эти строки — что телефон думает о детали сейчас."""
        comp = parse_components("".join(self.buf))
        if not comp:
            return
        self.meta["компоненты"] = {k: v for k, v in comp.items() if k != "детали"}
        if not comp["детали"]:
            return               # попалось только состояние аккумулятора — это ещё не вердикт по деталям
        for key, it in comp["детали"].items():
            cur = self.items.get(key)
            if cur is None:
                self.items[key] = dict(it)
            else:
                cur["меняли"] = cur["меняли"] or it["меняли"]
                if it.get("неизвестная"):
                    cur["неизвестная"] = True
                cur.setdefault("источник", it["источник"])
        # Словарь состояния — это подтверждение Apple; одно доверие к модулю — нет, и формат
        # обязан это различать: по нему строится право выдать зелёный.
        self._формат("проверка компонентов (iOS 26)" if comp.get("здоровье")
                     else f"новый формат словаря «{comp['новый_формат']}»" if comp.get("новый_формат")
                     else "доверие к модулям (iOS 15/16)")
        self.meta["раздел_открыт"] = True
        self.last_related_at = time.monotonic()
        if not self.found_at:
            self.found_at = time.monotonic()
            плохие = [v["деталь"] for v in comp["детали"].values() if v.get("неизвестная")]
            self.log("проверка компонентов Apple: " + (", ".join(плохие) + " — не подтверждены" if плохие
                                                       else "замечаний нет"))

    def _apply_repair_record(self, дата, центр):
        """Запись о ремонте Apple из журнала iOS 16: событие с датой и сервисным центром,
        без разбивки по деталям. Какие детали меняли, такая запись не говорит, поэтому
        вердикт по ней один: у Apple есть записи — смотреть на экране телефона."""
        self.items.setdefault("RepairRecords", {
            "деталь": "Записи о ремонте Apple", "код": 0, "меняли": True, "бу": False,
            "дата": дата if re.match(r"\d{4}-\d{2}-\d{2}", дата or "") else "",
            "записи_без_деталей": True, "источник": "записи о ремонте",
            "центр": центр[:40] if центр else ""})
        self.meta["раздел_открыт"] = True
        self.meta.setdefault("ремонт_apple", {"дата": дата, "центр": центр})
        self._формат("записи о ремонте (iOS 16)")
        self.last_related_at = time.monotonic()
        if not self.found_at:
            self.found_at = time.monotonic()
            self.log(f"у Apple есть запись о ремонте{' от ' + дата if дата else ''}")

    def _apply_seal(self):
        """Детали, которых нет в заводской печати (delta/Unsealed), — «неизвестного происхождения»,
        даже если записи обслуживания про них молчат: записи — это ремонты Apple, а подмену
        детали видит только сверка."""
        unknown = list(dict.fromkeys(list(self.meta.get("дельта") or []) + list(self.meta.get("unsealed") or [])))
        for comp in unknown:
            cur = self.items.get(comp) or {"деталь": RU.get(comp, comp), "код": 0, "бу": False, "дата": ""}
            if not cur.get("неизвестная"):
                self.items[comp] = {**cur, "меняли": True, "неизвестная": True,
                                    "источник": "сверка с заводской печатью"}

    @property
    def raw(self):
        """Записи + заметки об обрывах + все строки по теме: по ним разбираем новые форматы
        iOS без догадок (сырьё едет в слепок и видно сотруднику в карточке сделки)."""
        out = "".join(self.buf) + "".join(self.notes)
        out += "".join(f"# похожее: {l}\n" for l in self.related[:400])
        return out

    @property
    def state(self):
        """found | opened_unknown | waiting — для экрана и отчёта."""
        if self.items:
            return "found"
        if self.meta["раздел_открыт"]:
            return "opened_unknown"
        return "waiting"

    async def wait(self, seconds, keep_going=None, on_tick=None, grace=2.0, unknown_quiet=8.0, settle=5.0):
        """Ждать вердикт не дольше seconds (или пока keep_going() истинно).
        После первой записи — добрать grace секунд (записи идут пачкой; если у Apple
        есть записи о ремонте, а деталей ещё нет — ждём их дольше), а пока журнал по теме
        не затих — ещё до settle секунд: телефон допечатывает записи после подгрузки
        списка ремонтов, и ранний выход отдал бы «всё родное» из кэша.
        Если раздел открыт, но ни один известный формат не встретился, а журнал по
        теме затих на unknown_quiet секунд — выходим: формат этой iOS не распознан,
        сырьё сохранено, клиента дальше не держим.
        → (items, raw, секунд_ждали)."""
        start = time.monotonic()
        while True:
            now = time.monotonic()
            if self.found_at:
                g = grace * 3 if "RepairRecords" in self.items else grace
                quiet = now - (self.last_related_at or self.found_at) >= 1.0
                if now - self.found_at >= g and (quiet or now - self.found_at >= g + settle):
                    break
            elif (unknown_quiet and self.meta["раздел_открыт"] and self.last_related_at
                  and now - self.last_related_at >= unknown_quiet):
                self.meta["формат"] = self.meta["формат"] or "не распознан"
                break
            if not self.found_at and (now - start >= seconds or (keep_going and not keep_going())):
                break
            if on_tick:
                on_tick(int(now - start))
            await asyncio.sleep(0.25)
        return self.снимок(), self.raw, round(time.monotonic() - start, 1)

    async def wait_change(self, seen, keep_going=None, grace=2.0):
        """Ждать, пока записи станут отличаться от отпечатка seen (signature) — телефон
        допечатал вердикт позже, — затем добрать grace секунд. Выход и по keep_going().
        → (items, raw, секунд_ждали); если изменений нет — items с тем же отпечатком."""
        start = time.monotonic()
        changed_at = None
        while True:
            now = time.monotonic()
            if changed_at is None and signature(self.items) != seen:
                changed_at = now
            if changed_at is not None and now - changed_at >= grace:
                break
            if keep_going and not keep_going():
                break
            await asyncio.sleep(0.25)
        return self.снимок(), self.raw, round(time.monotonic() - start, 1)

    async def stop(self):
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):    # noqa: BLE001
                pass


async def capture(ld, seconds=120, keep_going=None, on_tick=None, log=None):
    """Разовый захват (доктор): слушать до записей или до истечения времени.
    Возвращает (items, сырой_текст, секунд_ждали)."""
    lst = Listener(ld, log=log)
    await lst.start()
    try:
        return await lst.wait(seconds, keep_going=keep_going, on_tick=on_tick)
    finally:
        await lst.stop()
