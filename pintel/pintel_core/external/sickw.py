# -*- coding: utf-8 -*-
"""Sickw: Apple GSX + реестр GSMA — чёрный список, цвет, заводская
конфигурация, iCloud, оператор. Независимо от телефона — подделке со
стороны аппарата неподвластно.

ДЕНЬГИ: кредит списывается даже при неудачном ответе. Поэтому: проверка
Luhn до запроса, кэш по IMEI (на сервере — общий на всю сеть точек).
  GET https://sickw.com/api.php?format=json&key=…&imei=…&service=61
  ответ: {"status": "success|error", "result": "<Метка: значение<br>…>", "imei": …}
"""
import html, json, os, re, time, urllib.parse, urllib.request

API = "https://sickw.com/api.php"
SERVICE_FULL = 61          # CARRIER & FMI & BLACKLIST


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


def _parse_result(result):
    raw = html.unescape(re.sub(r"<[^>]+>", "\n", str(result or "")))
    f = {}
    for line in raw.split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                f[k] = v
    return f


def _pick(f, *names):
    for n in names:
        for k in f:
            if k.lower() == n.lower():
                return f[k]
    return ""


def normalize(raw_fields):
    f = raw_fields
    model = _pick(f, "Model", "Model Description", "Description")
    cap = re.search(r"\b(\d+)\s?(GB|TB)\b", model, re.I)
    colour = re.sub(r"\[.*?\]", "", model)
    colour = re.sub(r"\b\d+\s?(GB|TB)\b", "", colour, flags=re.I)
    colour = re.sub(r"^\s*iPhone[\w\s]*?(Pro Max|Pro|Plus|mini|Air|SE)?\s*\d*\s*",
                    "", colour, flags=re.I).strip(" -,")
    blk = _pick(f, "Blacklist Status", "Blacklist")
    fmi = _pick(f, "iCloud Lock", "Find My iPhone", "FMI", "FMI Status", "iCloud Status")
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
        "в_чёрном_списке": (bool(blk) and blk.strip().upper() not in ("CLEAN", "CLEAR")) if blk else None,
        "icloud": fmi or None,
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


def lookup(imei, key, cache_dir=None, service=SERVICE_FULL, use_cache=True):
    """Полная проверка. Кэш по IMEI+service. Исключение — с человеческим текстом."""
    if not luhn_ok(imei):
        raise ValueError(f"IMEI {imei} не проходит контрольную цифру — записан неверно")
    cf = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cf = os.path.join(cache_dir, f"{imei}_{service}.json")
        if use_cache and os.path.isfile(cf) and os.path.getsize(cf) > 2:
            return json.load(open(cf, encoding="utf-8"))
    d = _get({"key": key, "imei": imei, "service": service})
    if str(d.get("status", "")).lower() != "success":
        raise RuntimeError(f"Sickw: {d.get('result') or d}")      # ошибку не кэшируем
    out = normalize(_parse_result(d.get("result")))
    out["служба"] = service
    out["получено"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if cf:
        json.dump(out, open(cf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out
