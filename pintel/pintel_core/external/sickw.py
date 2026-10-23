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
SERVICE_FULL = 61          # iPHONE CARRIER & FMI & BLACKLIST
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


def normalize(raw_fields):
    f = raw_fields
    model = _pick(f, "Model", "Model Description", "Description")
    cap = re.search(r"\b(\d+)\s?(GB|TB)\b", model, re.I)
    colour = re.sub(r"\[.*?\]", "", model)
    colour = re.sub(r"\b\d+\s?(GB|TB)\b", "", colour, flags=re.I)
    colour = re.sub(r"^\s*iPhone[\w\s]*?(Pro Max|Pro|Plus|mini|Air|SE)?\s*\d*\s*",
                    "", colour, flags=re.I).strip(" -,")
    blk, blk_flag = _strictest(_all(f, BLK_EXACT, BLK_SUBS), blacklist_flag)
    fmi, fmi_on = _strictest(_all(f, FMI_EXACT, FMI_SUBS), fmi_flag)
    carrier = _pick(f, "Locked Carrier", "Carrier", "Sim-Lock Status")
    simlock = _pick(f, "SIM-Lock", "SIM Lock", "Simlock")
    if not simlock and carrier:
        simlock = "разблокирован" if "unlock" in carrier.lower() else carrier
    warranty = _pick(f, "Warranty Status", "Coverage", "Repairs and Service Coverage")
    exp = _pick(f, "Repairs and Service Expiration Date", "Coverage Expiration Date")
    if exp and not warranty:
        warranty = f"обслуживание до {exp}"
        by = _pick(f, "Repairs and Service Expired By")
        if by:
            warranty += f" (истекло: {by})"
    return {
        "модель_строка": model,
        "объём_гб": (int(cap.group(1)) * (1024 if cap.group(2).upper() == "TB" else 1)) if cap else None,
        "цвет": colour or None,
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
        "замена_по_гарантии": _pick(f, "Replaced Device"),
        "подменный": _pick(f, "Loaner Device"),
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
