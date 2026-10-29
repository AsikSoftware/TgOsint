# -*- coding: utf-8 -*-
"""Sickw: Apple GSX + реестр GSMA — чёрный список, цвет, заводская
конфигурация, iCloud/«Найти iPhone», оператор. Независимо от телефона —
подделке со стороны аппарата неподвластно.

ДЕНЬГИ: кредит списывается даже при неудачном ответе. Поэтому: проверка
Luhn до запроса, кэш по IMEI+служба (на сервере — общий на всю сеть точек),
ошибки не кэшируем.
  GET https://sickw.com/api.php?format=json&key=…&imei=…&service=61
  ответ: {"status": "success|error", "result": "<Метка: значение<br>…>", "imei": …}

Служб может быть несколько ([sickw] services = [61, 54] в config.toml):
результаты складываются в один паспорт, сырой ответ каждой службы хранится
в кэше — разбор можно поправить задним числом, не тратя кредиты.

Сырой result — HTML. Sickw красит ON/OFF и CLEAN/BLACKLISTED тегами
(<font color=…>OFF</font>), поэтому inline-теги СНИМАЕМ, а в перенос
строки превращаем только блочные (<br>, <p>, <div>, <li>, <tr>). Иначе
метка и значение разъезжаются по разным строкам и теряются.
"""
import html, json, os, re, time, urllib.parse, urllib.request

API = "https://sickw.com/api.php"
SERVICE_FULL = 61          # iPHONE CARRIER & FMI & BLACKLIST — аппарат на кабеле
SERVICE_SEALED = 147       # запечатанный: по IMEI с коробки — модель, объём, цвет, активация
DEFAULT_SERVICES = (SERVICE_FULL,)

_BLOCK_TAG = re.compile(r"<\s*/?\s*(br|p|div|li|tr|td|th|h[1-6]|ul|ol|table|tbody|hr)\b[^>]*>", re.I)
_ANY_TAG = re.compile(r"<[^>]+>")


def luhn_ok(imei):
    d = [int(c) for c in str(imei) if c.isdigit()]
    if len(d) != 15:
        return False
    t = 0
    for i, x in enumerate(d[:14]):
        if i % 2:
            x *= 2
            x = x - 9 if x > 9 else x
        t += x
    return (10 - t % 10) % 10 == d[14]


def _get(params, timeout=60):
    q = urllib.parse.urlencode({"format": "json", **params})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": "PintelKiosk/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    try:
        return json.loads(body)
    except Exception:
        raise RuntimeError(f"Sickw ответил не JSON: {body[:200]}")


def balance(key):
    """Баланс/проверка ключа — бесплатный запрос."""
    return _get({"key": key, "action": "balance"}, timeout=30)


def parse_result(result):
    """HTML/текст/словарь result → {Метка: значение}. Метка без значения на
    своей строке (<p><b>Blacklist:</b></p><p>CLEAN</p>) подхватывает следующую строку."""
    if isinstance(result, dict):
        return {str(k).strip(): str(v).strip() for k, v in result.items()
                if v not in (None, "") and str(k).strip()}
    if isinstance(result, (list, tuple)):
        result = "\n".join(str(x) for x in result)
    s = _BLOCK_TAG.sub("\n", str(result or ""))
    s = _ANY_TAG.sub("", s)
    s = html.unescape(s).replace("\r", "").replace("\xa0", " ")
    f, pending = {}, None
    for line in (l.strip() for l in s.split("\n")):
        if not line:
            continue
        if pending is not None:
            f[pending] = line
            pending = None
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                f[k] = v
            elif k:
                pending = k
    return f


_parse_result = parse_result      # старое имя


def _pick(f, *names):
    for n in names:
        for k in f:
            if k.lower() == n.lower():
                return f[k]
    return ""


def _find(f, *subs):
    """Первое значение, чья метка содержит подстроку (без регистра)."""
    for s in subs:
        for k in f:
            if s in k.lower():
                return f[k]
    return ""


def _words(v):
    return set(re.findall(r"[a-zа-я]+", str(v or "").lower()))


def _flag(v, yes, no):
    """Строка → True/False/None. Сначала отрицания ('not blacklisted' содержит 'blacklist')."""
    if not v:
        return None
    l = v.lower()
    if any(p in l for p in no):
        return False
    if any(p in l for p in yes):
        return True
    return None


def fmi_flag(v):
    w = _words(v)
    if w & {"off", "disabled", "inactive", "clean", "unlocked", "no"}:
        return False
    if w & {"on", "enabled", "active", "locked", "yes"}:
        return True
    return None


def blacklist_flag(v):
    return _flag(v, yes=("blacklist", "lost", "stolen", "barred", "blocked", "reported"),
                 no=("clean", "clear", "not black", "not reported", "not found", "not lost"))


def _all(f, exact, subs):
    """Все значения, чья метка либо из списка точных, либо содержит подстроку."""
    ex = {e.lower() for e in exact}
    return [v for k, v in f.items() if v and (k.lower() in ex or any(s in k.lower() for s in subs))]


def _strictest(vals, flag):
    """Из нескольких полей одного смысла: если хоть одно тревожное — оно и побеждает."""
    flags = [flag(v) for v in vals]
    if True in flags:
        return vals[flags.index(True)], True
    if vals:
        return vals[0], (False if False in flags else None)
    return "", None


BLK_EXACT = ("Blacklist Status", "Blacklist", "GSMA Blacklist Status", "WW Blacklist Status")
BLK_SUBS = ("blacklist", "black list", "lost/stolen", "stolen")
FMI_EXACT = ("iCloud Lock", "Find My iPhone", "FMI", "FMI Status", "iCloud Status",
             "Find My iPhone Status", "Activation Lock", "Activation Lock Status")
FMI_SUBS = ("find my", "fmi", "icloud", "activation lock")


# Код/слово цвета из GSX → по-русски. Коды вида ORN видны в Model Description
# («IPHONE 17 PRO,NAJP,256GB,ORN»), слова — в поле Model («iPhone 12 64GB Black»).
COLOURS = {
    "BLACK": "чёрный", "BLK": "чёрный", "WHITE": "белый", "WHT": "белый",
    "SILVER": "серебристый", "SLV": "серебристый", "GOLD": "золотой", "GLD": "золотой",
    "BLUE": "синий", "BLU": "синий", "GREEN": "зелёный", "GRN": "зелёный", "RED": "красный",
    "YELLOW": "жёлтый", "YLW": "жёлтый", "PINK": "розовый", "PNK": "розовый",
    "PURPLE": "фиолетовый", "PRP": "фиолетовый", "ORANGE": "оранжевый", "ORN": "оранжевый",
    "GRAY": "серый космос", "GREY": "серый космос", "GRY": "серый космос", "SPACE GRAY": "серый космос",
    "SPG": "серый космос", "MIDNIGHT": "тёмная ночь", "MDN": "тёмная ночь",
    "STARLIGHT": "сияющая звезда", "STR": "сияющая звезда", "GRAPHITE": "графитовый", "GRA": "графитовый",
    "SIERRA BLUE": "сьерра-блю", "PACIFIC BLUE": "тихоокеанский синий", "NATURAL": "натуральный титан",
    "NAT": "натуральный титан", "NATURAL TITANIUM": "натуральный титан", "DESERT": "пустынный титан",
    "DST": "пустынный титан", "DESERT TITANIUM": "пустынный титан", "TEAL": "бирюзовый", "TEL": "бирюзовый",
    "ULTRAMARINE": "ультрамарин", "ULT": "ультрамарин", "LAVENDER": "лавандовый", "LAV": "лавандовый",
    "SAGE": "шалфейный", "SGE": "шалфейный", "MIST BLUE": "туманно-голубой", "MST": "туманно-голубой",
    "SKY BLUE": "небесно-голубой", "SKY": "небесно-голубой", "CLOUD WHITE": "облачно-белый",
    "CLD": "облачно-белый", "DEEP BLUE": "тёмно-синий", "DBL": "тёмно-синий", "DEEP PURPLE": "тёмно-фиолетовый",
    "DPR": "тёмно-фиолетовый", "SPACE BLACK": "чёрный космос", "SPB": "чёрный космос",
    "CORAL": "коралловый", "CRL": "коралловый", "ROSE GOLD": "розовое золото", "RSG": "розовое золото",
    "JET BLACK": "чёрный оникс", "ALPINE GREEN": "альпийский зелёный", "COSMIC ORANGE": "оранжевый",
    "BLACK TITANIUM": "чёрный титан", "WHITE TITANIUM": "белый титан", "BLUE TITANIUM": "синий титан",
}


def colour_ru(word):
    w = str(word or "").strip()
    return COLOURS.get(w.upper(), w.title() if w else None)


def parse_gsx_description(desc):
    """'IPHONE 17 PRO,NAJP,256GB,ORN' → {модель, регион_gsx, объём_гб, цвет_код}.
    Последний элемент — цвет, объём — элемент вида 256GB, второй — регион партии."""
    parts = [p.strip() for p in str(desc or "").split(",")]
    if len(parts) < 2 or not parts[0]:
        return {}
    out = {"модель": re.sub(r"(?i)^iphone", "iPhone", parts[0].title())}
    rest = []
    for p in parts[1:]:
        m = re.fullmatch(r"(\d+)\s?(GB|TB)", p, re.I)
        if m:
            out["объём_гб"] = int(m.group(1)) * (1024 if m.group(2).upper() == "TB" else 1)
        elif p:
            rest.append(p)
    if rest:
        out["цвет_код"] = rest[-1]
        if len(rest) > 1:
            out["регион_gsx"] = rest[0]
    return out


# Слова, которые в описании модели не являются цветом: сама модель, её вариант, объём и
# номер модели вида A2891. Раньше цвет вырезался одной регуляркой «от начала строки», и она
# срезала только «iPhone 14 », оставляя вариант: в Оценку уезжало «Цвет: Pro A2891» и
# «Pro Space Black». Теперь выбрасываем эти слова независимо от их места в строке.
_НЕ_ЦВЕТ = re.compile(r"(?i)\b(iphone|pro\s+max|pro|plus|mini|air|se|max|xs|xr|x|"
                      r"\d+\s?(?:gb|tb)|a\d{4}|\d+)\b")


def цвет_из_описания(model):
    """'iPhone 14 Pro Space Black 256GB' → 'Space Black'; 'iPhone 14 Pro A2891' → ''.
    Что осталось после выброса модельных слов, то и цвет."""
    s = re.sub(r"\[.*?\]", " ", str(model or ""))
    s = _НЕ_ЦВЕТ.sub(" ", s)
    return re.sub(r"[\s,\-/]+", " ", s).strip(" -,/")


def модель_без_цвета(model):
    """'iPhone 14 Pro Space Black 256GB' → 'iPhone 14 Pro'; 'iPhone 12 64GB Black' → 'iPhone 12'.

    Для запечатанного это единственный источник модели: кабеля нет, а в сделке Оценки
    `model` должен совпадать со строкой её прайса — без объёма и цвета."""
    s = re.sub(r"\[.*?\]", " ", str(model or ""))
    s = re.sub(r"(?i)\b\d+\s?(gb|tb)\b", " ", s)
    s = re.sub(r"(?i)\ba\d{4}\b", " ", s)
    for w in цвет_из_описания(model).split():
        s = re.sub(rf"(?i)\b{re.escape(w)}\b", " ", s)
    s = re.sub(r"[\s,\-/]+", " ", s).strip(" -,/")
    return re.sub(r"(?i)^iphone", "iPhone", s) if s else ""


def активация_flag(v):
    """'Activated' / 'Not Activated' / 'Unactivated' → True/False/None. Для запечатанного
    «не активирован» — главный признак того, что коробку действительно не вскрывали."""
    l = str(v or "").strip().lower()
    if not l:
        return None
    if any(p in l for p in ("not activ", "unactiv", "inactive", "никогда", "не актив")):
        return False
    if any(p in l for p in ("activ", "yes", "актив")) or re.search(r"\d{4}", l):
        return True
    return None


def _yes(v):
    l = str(v or "").strip().lower()
    return True if l in ("yes", "true", "1") else (False if l in ("no", "false", "0") else None)


def normalize(raw_fields):
    f = raw_fields
    gsx = parse_gsx_description(_pick(f, "Model Description"))
    model = _pick(f, "Model", "Description") or gsx.get("модель", "")
    cap = re.search(r"\b(\d+)\s?(GB|TB)\b", model, re.I)
    colour_raw = цвет_из_описания(_pick(f, "Model")) or gsx.get("цвет_код", "")
    colour = colour_ru(colour_raw)
    blk, blk_flag = _strictest(_all(f, BLK_EXACT, BLK_SUBS), blacklist_flag)
    fmi, fmi_on = _strictest(_all(f, FMI_EXACT, FMI_SUBS), fmi_flag)
    carrier = _pick(f, "Locked Carrier", "Carrier")
    simlock = _pick(f, "SIM-Lock", "SIM Lock", "Simlock", "Sim-Lock Status")
    probe = (simlock or carrier).lower()
    if probe:
        simlock = "разблокирован" if "unlock" in probe else (
            f"заблокирован под оператора: {carrier or simlock}" if "lock" in probe else (simlock or carrier))
    warranty = _pick(f, "Warranty Status", "Coverage", "Repairs and Service Coverage")
    exp = _pick(f, "Repairs and Service Expiration Date", "Coverage Expiration Date")
    if exp and not warranty:
        warranty = f"обслуживание до {exp}"
        by = _pick(f, "Repairs and Service Expired By")
        if by:
            warranty += f" (истекло: {by})"
    активация = _pick(f, "Activation Status", "Activated", "Activation", "Activation Date",
                      "First Activation Date")
    return {
        "модель_строка": model,
        "модель": gsx.get("модель") or модель_без_цвета(_pick(f, "Model", "Description")) or None,
        "объём_гб": ((int(cap.group(1)) * (1024 if cap.group(2).upper() == "TB" else 1)) if cap
                     else gsx.get("объём_гб")),
        "активация": активация or None,
        "активирован": активация_flag(активация),
        "продано": _pick(f, "Sold By", "Sold To", "Sold by", "Seller", "Sales Channel") or None,
        "цвет": colour or None,
        "цвет_исходный": colour_raw or None,
        "регион_gsx": gsx.get("регион_gsx"),
        "подменный": _yes(_pick(f, "Loaner Device")),
        "демо": _yes(_pick(f, "Demo Unit")),
        "восстановленный": _yes(_pick(f, "Refurbished Device")),
        "замена_по_гарантии": _yes(_pick(f, "Replaced Device")),
        "applecare": _yes(_pick(f, "AppleCare Eligible")),
        "гарантия_до": _pick(f, "Repairs and Service Expiration Date", "Coverage Expiration Date") or None,
        "регистрация": _pick(f, "Registration Status") or None,
        "чёрный_список": blk or None,                   # None = услуга не отдаёт
        "в_чёрном_списке": blk_flag,                    # True/False/None
        "icloud": fmi or None,
        "fmi_включён": fmi_on,                          # True/False/None
        "sim_lock": simlock or None,
        "оператор": carrier or None,
        "страна_политики": _pick(f, "Locked Activation Policy Country") or None,
        "страна_покупки": _pick(f, "Purchase Country") or None,
        "гарантия": warranty or None,
        "дата_покупки": _pick(f, "Estimated Purchase Date", "Purchase Date") or None,
        "описание": _pick(f, "Model Description") or None,
        "дата_активации": _pick(f, "First Activation Date", "Activation Status"),
        "все_поля": f,
    }


def _cache_file(cache_dir, imei, service):
    if not cache_dir:
        return None
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{imei}_{service}.json")


def lookup(imei, key, cache_dir=None, service=SERVICE_FULL, use_cache=True):
    """Одна служба. Кэш по IMEI+служба; в кэше лежит сырой ответ, и разбор
    при чтении из кэша делается заново — правки парсера применяются бесплатно.
    Старый кэш без сырого ответа (разбор мог потерять поля) перечитывается с сервера."""
    if not luhn_ok(imei):
        raise ValueError(f"IMEI {imei} не проходит контрольную цифру — записан неверно")
    cf = _cache_file(cache_dir, imei, service)
    if use_cache and cf and os.path.isfile(cf) and os.path.getsize(cf) > 2:
        try:
            c = json.load(open(cf, encoding="utf-8"))
        except Exception:
            c = {}
        if "сырой_ответ" in c:
            out = normalize(parse_result(c["сырой_ответ"]))
            out.update({k: c[k] for k in ("сырой_ответ", "служба", "получено") if k in c})
            out["из_кэша"] = True
            return out
    d = _get({"key": key, "imei": imei, "service": service})
    if str(d.get("status", "")).lower() != "success":
        raise RuntimeError(f"Sickw (служба {service}): {d.get('result') or d}")      # ошибку не кэшируем
    raw = d.get("result")
    out = normalize(parse_result(raw))
    out["сырой_ответ"] = raw if isinstance(raw, (str, dict, list)) else str(raw)
    out["служба"] = service
    out["получено"] = time.strftime("%Y-%m-%d %H:%M:%S")
    out["из_кэша"] = False
    if cf:
        json.dump(out, open(cf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


def merge(results):
    """Несколько служб → один паспорт. Поле берётся из первой службы, где оно непустое."""
    fields = {}
    for r in results:
        for k, v in (r.get("все_поля") or {}).items():
            if v and not fields.get(k):
                fields[k] = v
    out = normalize(fields)
    out["службы"] = [r.get("служба") for r in results]
    out["сырые_ответы"] = {str(r.get("служба")): r.get("сырой_ответ") for r in results}
    out["получено"] = max((r.get("получено") or "" for r in results), default="")
    out["из_кэша"] = all(r.get("из_кэша") for r in results)
    return out


def lookup_many(imei, key, services=DEFAULT_SERVICES, cache_dir=None, use_cache=True):
    """Все службы из конфига. Падение одной службы не губит остальные —
    оно записывается в «ошибки_служб». Если не ответила ни одна — исключение."""
    results, errors = [], {}
    for s in services or DEFAULT_SERVICES:
        try:
            results.append(lookup(imei, key, cache_dir, int(s), use_cache))
        except Exception as e:
            errors[str(s)] = str(e)
    if not results:
        raise RuntimeError("; ".join(errors.values()) or "Sickw: нет служб в конфиге")
    out = merge(results)
    out["ошибки_служб"] = errors
    return out


def raw_lines(result):
    """Сырой ответ службы — построчно, для глаз (и чтобы прислать разработчику)."""
    s = _BLOCK_TAG.sub("\n", str(result or "")) if not isinstance(result, dict) else \
        "\n".join(f"{k}: {v}" for k, v in result.items())
    s = html.unescape(_ANY_TAG.sub("", s))
    return [l.strip() for l in s.split("\n") if l.strip()]
