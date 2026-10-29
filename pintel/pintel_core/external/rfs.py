# -*- coding: utf-8 -*-
"""Реестр IMEI РФС РК (imei.rfs.gov.kz): верифицирован ли аппарат в Казахстане.

Стандартная библиотека, без браузера и капчи: сайт принимает статический токен `web`
(сервер его не проверяет), так что проверка — один HTTP-запрос. Проверяем оба IMEI
аппарата при любом сценарии: и по кабелю, и для запечатанного по коробке.

Что проверено на боевом объёме (2500+ IMEI за прогон):
  * реестр сверяет IMEI по ПЕРВЫМ 14 цифрам (15-я — контрольная) — обрезаем сами;
  * сервер держит около одного запроса в секунду, параллелить НЕЛЬЗЯ — сразу 503, поэтому
    проверка строго последовательная с паузой REQUEST_DELAY;
  * вердикт — ПО ТЕКСТУ, а не по цвету alert: красным сайт красит и «не верифицирован»,
    это не блокировка;
  * из Казахстана реестр открыт, из-за рубежа может не отвечать — тогда прокси KZ
    (`rfs_proxy` в kiosk.toml или переменная RFS_PROXY).

Результат одной проверки — словарь:
    {"imei": "353665852059610", "verdict": "verified|not_verified|blocked|unknown",
     "status_text": "Верифицирован", "deadline": "31.12.2026" | None,
     "text": "<чистый текст ответа>", "ok": True}      # ok=False — проверка не удалась

Ответ кэшируется на точке (КЭШ_ЧАСОВ): переподключили телефон — реестр не дёргаем снова.
Неудачу не кэшируем.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

__all__ = ["check_imei", "check_imeis", "registry_up", "analyze", "проверить", "словами",
           "сводка", "VERIFIED", "NOT_VERIFIED", "BLOCKED", "UNKNOWN"]

BASE_URL = "https://imei.rfs.gov.kz"
API_PATH = "/api/proxy.php"
TOKEN = "web"            # статический токен; сервер его не проверяет
LANG = "r"               # r=ru, e=en, k=kk
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

HTTP_TIMEOUT = 20.0      # сек на запрос
REQUEST_DELAY = 0.5      # пауза перед каждым запросом (сервер ~1 rps)
RETRIES = 2              # повторы при 429/503/сетевых сбоях (на точке ждать долго нельзя)
КЭШ_ЧАСОВ = 6            # статус в реестре меняется днями, а телефон переподключают минутами

VERIFIED = "verified"
NOT_VERIFIED = "not_verified"
BLOCKED = "blocked"
UNKNOWN = "unknown"

STATUS_TEXT = {
    VERIFIED: "Верифицирован",
    NOT_VERIFIED: "Не верифицирован",
    BLOCKED: "Заблокирован",
    UNKNOWN: "Неизвестно",
}

_TAG = re.compile(r"(?is)<[^>]+>")
_BREAKS = re.compile(r"(?is)<br\s*/?>|</p>|</div>|</li>")
_SPACES = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\s*\n\s*\n+")
_ALERT = re.compile(r"alert-(success|warning|danger|info)", re.I)
_DEADLINE = re.compile(r"до\s+(\d{2}\.\d{2}\.\d{4})")


# ─── Разбор ответа сайта ────────────────────────────────────────────────────

def _extract_html(data) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for key in ("raw", "html", "message", "result", "data", "response"):
            v = data.get(key)
            if isinstance(v, str) and v:
                return v
        return ""                        # HTML нет — только структура, её читает _structured_fallback
    return str(data)


def _html_to_text(raw: str) -> str:
    text = _BREAKS.sub("\n", raw)
    text = _TAG.sub("", text)
    text = _html.unescape(text)
    text = _SPACES.sub(" ", text)
    return _BLANK_LINES.sub("\n", text).strip()


def _classify(raw_html: str, text_lower: str) -> str:
    # По тексту, а не по цвету alert: красный бывает и у «не верифицирован».
    blocked = any(w in text_lower for w in
                  ("заблокир", "блокир", "чёрн", "черн", "blacklist", "blocked"))
    not_blocked = any(w in text_lower for w in
                      ("не заблок", "не блокир", "разблок"))
    if blocked and not not_blocked:
        return BLOCKED
    if any(w in text_lower for w in
           ("не верифиц", "не зарегистр", "не прош", "не пройд", "временно",
            "not verified", "not registered")):
        return NOT_VERIFIED
    if any(w in text_lower for w in
           ("верифиц", "зарегистр", "verified", "registered")):
        return VERIFIED
    alert = _ALERT.search(raw_html)
    kind = alert.group(1).lower() if alert else None
    if kind == "success":
        return VERIFIED
    if kind in ("warning", "danger"):
        return NOT_VERIFIED
    return UNKNOWN


def _structured_fallback(data):
    """Запас на случай, если реестр однажды отдаст нормальный JSON."""
    if not isinstance(data, dict):
        return None
    inner = data
    for key in ("data", "result", "response"):
        if isinstance(data.get(key), dict):
            inner = data[key]
            break
    if str(inner.get("status", "")).lower() in {"blocked", "заблокирован"}:
        return BLOCKED
    for key in ("verified", "registered", "status"):
        v = inner.get(key)
        if isinstance(v, bool):
            return VERIFIED if v else NOT_VERIFIED
    return None


def analyze(data):
    """Ответ сайта → (verdict, чистый текст, срок 'ДД.ММ.ГГГГ' или None)."""
    raw_html = _extract_html(data)
    if not raw_html and isinstance(data, dict):
        # чистый JSON без HTML: слово «verified» в ключе — не вердикт, читаем структуру
        text = json.dumps(data, ensure_ascii=False)
        verdict = _structured_fallback(data) or UNKNOWN
    else:
        text = _html_to_text(raw_html)
        verdict = _classify(raw_html, text.lower())
        if verdict == UNKNOWN:
            verdict = _structured_fallback(data) or UNKNOWN
    m = _DEADLINE.search(text)
    return verdict, text, (m.group(1) if m else None)


# ─── HTTP ───────────────────────────────────────────────────────────────────

def _opener(proxy: str | None = None):
    proxy = (proxy or os.getenv("RFS_PROXY", "") or "").strip()
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener()


def _fail(imei, reason):
    return {"imei": imei, "verdict": UNKNOWN, "status_text": STATUS_TEXT[UNKNOWN],
            "deadline": None, "text": str(reason)[:200], "ok": False}


def _request(imei14: str, timeout: float, proxy: str | None = None):
    params = urllib.parse.urlencode(
        {"endpoint": "imeiCheck", "l": LANG, "data": imei14, "token": TOKEN})
    req = urllib.request.Request(
        f"{BASE_URL}{API_PATH}?{params}",
        headers={"User-Agent": _UA,
                 "Accept": "application/json, text/plain, */*",
                 "Referer": BASE_URL + "/",
                 "Origin": BASE_URL,
                 "X-Requested-With": "XMLHttpRequest"})
    with _opener(proxy).open(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def _backoff(attempt: int, retry_after=None) -> float:
    try:
        if retry_after is not None:
            return max(1.0, min(float(retry_after), 60.0))
    except (TypeError, ValueError):
        pass
    return min(5.0 * (2 ** attempt), 30.0)


def imei14(imei) -> str:
    """Реестр сверяет первые 14 цифр; пусто — в строке нет 14 цифр."""
    цифры = re.sub(r"\D", "", str(imei or ""))
    return цифры[:14] if len(цифры) >= 14 else ""


def check_imei(imei, timeout: float = HTTP_TIMEOUT, retries: int = RETRIES,
               proxy: str | None = None) -> dict:
    """Проверить ОДИН IMEI. Всегда возвращает словарь (не бросает исключений)."""
    imei = str(imei).strip()
    i14 = imei14(imei)
    if not i14:
        return _fail(imei, "IMEI короче 14 цифр")
    for attempt in range(retries + 1):
        try:
            status, body = _request(i14, timeout, proxy)
            if status != 200 or not body.strip():
                if attempt < retries:
                    time.sleep(_backoff(attempt))
                    continue
                return _fail(imei, f"HTTP {status}")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {"raw": body}
            verdict, text, deadline = analyze(data)
            return {"imei": imei, "verdict": verdict,
                    "status_text": STATUS_TEXT[verdict],
                    "deadline": deadline, "text": text, "ok": True}
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries:
                time.sleep(_backoff(attempt, e.headers.get("Retry-After")))
                continue
            if attempt < retries:
                time.sleep(_backoff(attempt))
                continue
            return _fail(imei, f"HTTP {e.code}")
        except Exception as e:                       # сеть, таймаут, DNS, прокси
            if attempt < retries:
                time.sleep(_backoff(attempt))
                continue
            return _fail(imei, e)
    return _fail(imei, "не удалось после повторов")


def check_imeis(imeis, on_progress=None, delay: float = REQUEST_DELAY,
                retry_passes: int = 1, proxy: str | None = None) -> list:
    """Проверить СПИСОК IMEI последовательно (сервер не терпит параллельности).

    on_progress(done, total) — необязательный колбэк прогресса. В конце — доп. проходы по
    упавшим: гос-сервер регулярно отваливается точечно, повтор закрывает почти все пропуски.
    """
    items = [str(x).strip() for x in imeis if str(x or "").strip()]
    total = len(items)
    results = []
    for i, imei in enumerate(items, 1):
        if delay:
            time.sleep(delay)
        results.append(check_imei(imei, proxy=proxy))
        if on_progress:
            on_progress(i, total)

    for attempt in range(max(0, retry_passes)):
        failed = [i for i, r in enumerate(results) if not r["ok"]]
        if not failed:
            break
        time.sleep(3 + 2 * attempt)                  # дать серверу «выдохнуть»
        for i in failed:
            if delay:
                time.sleep(delay)
            results[i] = check_imei(results[i]["imei"], proxy=proxy)
    return results


def registry_up(timeout: float = 8.0, proxy: str | None = None) -> bool:
    """Жив ли реестр: один запрос без повторов. False — лёг или нет доступа."""
    try:
        status, body = _request("35296334304074", timeout, proxy)
        return status == 200 and bool(body.strip())
    except Exception:
        return False


# ─── Для киоска: кэш на точке и слова для экрана ───────────────────────────

def _кэш_файл(cache_dir, imei):
    if not cache_dir:
        return None
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{imei14(imei) or 'x'}.json")


def проверить(imeis, cache_dir: str | None = None, proxy: str | None = None,
              свежесть_часов: float = КЭШ_ЧАСОВ, on_progress=None) -> list:
    """Оба IMEI аппарата → список результатов check_imei, в порядке входа.

    Пустые и повторяющиеся значения выбрасываются; второй IMEI у eSIM-аппарата бывает
    пустым. Свежий ответ берётся из кэша — переподключили кабель, реестр не дёргаем.
    Неудача (ok=False) не кэшируется: следующий раз спросим снова."""
    имеи = list(dict.fromkeys(str(x).strip() for x in (imeis or []) if str(x or "").strip()))
    итог, спросить = {}, []
    for imei in имеи:
        f = _кэш_файл(cache_dir, imei)
        try:
            if f and os.path.isfile(f) and time.time() - os.path.getmtime(f) < свежесть_часов * 3600:
                с = json.load(open(f, encoding="utf-8"))
                if с.get("ok"):
                    итог[imei] = {**с, "imei": imei, "из_кэша": True}
                    continue
        except Exception:                                        # noqa: BLE001 — битый кэш = нет кэша
            pass
        спросить.append(imei)
    for r in check_imeis(спросить, on_progress=on_progress, proxy=proxy):
        итог[r["imei"]] = {**r, "из_кэша": False}
        f = _кэш_файл(cache_dir, r["imei"])
        if f and r.get("ok"):
            try:
                json.dump(r, open(f, "w", encoding="utf-8"), ensure_ascii=False)
            except OSError:
                pass
    return [итог[i] for i in имеи]


def словами(r: dict) -> str:
    """Одна строка для экрана, карточки и чека: «верифицирован», «не верифицирован
    (временный доступ до 31.12.2026)», «ЗАБЛОКИРОВАН», «реестр не ответил»."""
    if not r or not r.get("ok"):
        return "реестр не ответил"
    v = r.get("verdict")
    if v == BLOCKED:
        return "ЗАБЛОКИРОВАН"
    if v == VERIFIED:
        return "верифицирован"
    if v == NOT_VERIFIED:
        return "не верифицирован" + (f" (временный доступ до {r['deadline']})" if r.get("deadline") else "")
    return "статус не разобран"


def в_отчёт(results) -> tuple:
    """Результаты по IMEI → (стоп, внимание, не_прочиталось) для отчёта.

    Заблокирован — стоп. Не верифицирован — предупреждение: после срока временного доступа
    телефон не будет работать в сетях Казахстана, и это решает оценщик. Реестр не ответил —
    отсутствие данных, а не вердикт."""
    стоп, внимание, нет = [], [], []
    for r in results or []:
        imei = r.get("imei")
        if not r.get("ok") or r.get("verdict") == UNKNOWN:
            нет.append(f"реестр РФС не ответил — IMEI {imei} не сверен")
        elif r.get("verdict") == BLOCKED:
            стоп.append(f"IMEI {imei} заблокирован в реестре РФС РК")
        elif r.get("verdict") == NOT_VERIFIED:
            внимание.append(f"IMEI {imei} не верифицирован в реестре РФС РК"
                            + (f" — временный доступ до {r['deadline']}" if r.get("deadline") else ""))
    return стоп, внимание, нет


def сводка(results) -> dict:
    """Итог по всем IMEI: худший вердикт решает. → {вердикт, строки:[«3505… — верифицирован»]}.

    Порядок строгости: заблокирован > не верифицирован > не ответил > верифицирован."""
    results = list(results or [])
    строки = [f"{r.get('imei')} — {словами(r)}" for r in results]
    if not results:
        return {"вердикт": None, "строки": []}
    if any(r.get("ok") and r.get("verdict") == BLOCKED for r in results):
        вердикт = BLOCKED
    elif any(r.get("ok") and r.get("verdict") == NOT_VERIFIED for r in results):
        вердикт = NOT_VERIFIED
    elif any(not r.get("ok") or r.get("verdict") == UNKNOWN for r in results):
        вердикт = UNKNOWN
    else:
        вердикт = VERIFIED
    сроки = [r["deadline"] for r in results if r.get("ok") and r.get("deadline")]
    return {"вердикт": вердикт, "строки": строки, "срок": сроки[0] if сроки else None}
