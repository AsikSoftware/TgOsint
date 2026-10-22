"""Внешняя база Sickw: данные Apple GSX + реестр GSMA.

Даёт то, чего по кабелю нет вообще: чёрный список, цвет, заводскую
конфигурацию, статусы оператора и iCloud, даты активации и покупки.
И главное — НЕЗАВИСИМО от телефона, то есть подделке со стороны аппарата
неподвластно.

Спецификация выяснена опытным путём: страница API у Sickw за логином, но
endpoint сам называет обязательные параметры в сообщениях об ошибках.
  GET https://sickw.com/api.php?format=json&key=…&imei=…&service=…
  ответ: {"status": "success|error", "result": "<блок Метка: значение>", "imei": …}

ДЕНЬГИ: кредит списывается ДАЖЕ при неудачном ответе. Поэтому кэш по IMEI
и проверка контрольной цифры до запроса.
"""
import html, json, os, re, time, urllib.parse, urllib.request

API = "https://sickw.com/api.php"
SERVICE_FULL = 61      # CARRIER & FMI & BLACKLIST — чёрный список, iCloud,
                       # оператор, SIM-lock, гарантия, модель с цветом и объёмом
from .paths import beside
CACHE = beside("data", "sickw_cache")  # рядом с программой, переживает перезапуск


def key_available():
    if os.environ.get("SICKW_KEY"):
        return True
    return os.path.isfile(os.path.expanduser("~/.sickw_key"))


def _key():
    k = os.environ.get("SICKW_KEY")
    if k:
        return k.strip()
    p = os.path.expanduser("~/.sickw_key")
    if os.path.isfile(p):
        return open(p, encoding="utf-8").read().strip()
    raise RuntimeError("Нет ключа Sickw: впиши его в Настройках")


def key_tail():
    """Последние 4 знака ключа — показать «какой ключ стоит», не раскрывая его."""
    try:
        return _key()[-4:]
    except Exception:
        return ""


def save_key(key):
    """Сохраняет ключ из окна настроек в ~/.sickw_key. Пустая строка — удалить.
    Ключ по-прежнему живёт в файле у пользователя, не внутри программы."""
    p = os.path.expanduser("~/.sickw_key")
    key = str(key or "").strip()
    if key:
        with open(p, "w", encoding="utf-8") as f:
            f.write(key + "\n")
    else:
        try:
            os.remove(p)
        except FileNotFoundError:
            pass


def luhn_ok(imei):
    """Контрольная цифра. Проверяется ДО запроса: опечатка иначе стоила бы
    оплаченного запроса."""
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


def _parse_result(result):
    """result приходит одним блоком «Метка: значение», разделённым <br>."""
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


def lookup(imei, service=SERVICE_FULL, use_cache=True):
    """Возвращает dict с разобранными полями. Бросает исключение при отказе."""
    os.makedirs(CACHE, exist_ok=True)
    cf = os.path.join(CACHE, f"{imei}_{service}.json")
    if use_cache and os.path.isfile(cf) and os.path.getsize(cf) > 2:
        return json.load(open(cf, encoding="utf-8"))

    if not luhn_ok(imei):
        raise ValueError(f"IMEI {imei} не проходит проверку контрольной цифры — записан неверно")

    q = urllib.parse.urlencode({"format": "json", "key": _key(),
                                "imei": imei, "service": service})
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": "PintelCheck/1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode("utf-8", "replace")
    try:
        d = json.loads(body)
    except Exception:
        raise RuntimeError(f"Sickw ответил не JSON: {body[:200]}")
    if str(d.get("status", "")).lower() != "success":
        # Ошибку НЕ кэшируем, иначе она застрянет навсегда.
        raise RuntimeError(f"Sickw: {d.get('result')}")

    f = _parse_result(d.get("result"))
    model = _pick(f, "Model", "Model Description", "Description")
    cap = re.search(r"\b(\d+)\s?(GB|TB)\b", model, re.I)
    colour = re.sub(r"\[.*?\]", "", model)
    colour = re.sub(r"\b\d+\s?(GB|TB)\b", "", colour, flags=re.I)
    colour = re.sub(r"^\s*iPhone[\w\s]*?(Pro Max|Pro|Plus|mini|Air|SE)?\s*\d*\s*",
                    "", colour, flags=re.I).strip(" -,")
    out = {
        "модель_строка": model,
        "объём_гб": (int(cap.group(1)) * (1024 if cap.group(2).upper() == "TB" else 1)) if cap else None,
        "цвет": colour or None,
        "чёрный_список": _pick(f, "Blacklist Status"),
        "icloud": _pick(f, "iCloud Lock"),
        "sim_lock": _pick(f, "SIM-Lock", "SIM Lock"),
        "оператор": _pick(f, "Locked Carrier"),
        "страна_политики": _pick(f, "Locked Activation Policy Country"),
        "гарантия": _pick(f, "Warranty Status"),
        "дата_покупки": _pick(f, "Estimated Purchase Date", "Purchase Date"),
        "дата_активации": _pick(f, "First Activation Date", "Activation Status"),
        "замена_по_гарантии": _pick(f, "Replaced Device"),
        "подменный": _pick(f, "Loaner Device"),
        "все_поля": f,          # в бэкенд — максимум, как и просили
        "служба": service,
        "получено": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    json.dump(out, open(cf, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out
