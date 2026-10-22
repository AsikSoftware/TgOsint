# -*- coding: utf-8 -*-
"""Прайс из Google Таблицы магазина.

Основной путь — Google Sheets API с сервис-аккаунтом: рядом с программой
лежит файл gservice.json (ключ сервис-аккаунта), а таблицей поделились
с его email как с читателем. Таблица остаётся ЗАКРЫТОЙ для всех остальных.
Если gservice.json нет — запасной путь через CSV-экспорт, он требует
доступа «все, у кого есть ссылка».

Парсер терпим к оформлению:
  • модели по строкам, объёмы по столбцам (шапка «64 / 128 / 256…»);
  • или объём прямо в названии («iPhone 13 Pro 256 GB» и цена в той же строке);
  • русские названия («Айфон 13 Про Макс») тоже понимает;
  • цены — с пробелами, ₸, тг: «150 000 ₸».

Что не распозналось — честно возвращается списком, а не выдумывается.
"""
import csv, io, json, re, time, urllib.parse, urllib.request

from . import price
from .paths import beside, bundled

SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"

# Таблица магазина по умолчанию; в Настройках ссылку можно заменить.
DEFAULT_URL = ("https://docs.google.com/spreadsheets/d/"
               "1TJWXvVC9eBFhKW38mfRBUvOftSUrWL_LmzsR-VlF-ZA/edit?gid=1917713663")

_TRANSLIT = [("айфон", "iphone"), ("про макс", "pro max"), ("промакс", "pro max"),
             ("про", "pro"), ("макс", "max"), ("мини", "mini"), ("плюс", "plus"),
             ("аир", "air"), ("эйр", "air")]
_CAP_RE = re.compile(r"(\d+)\s*(tb|тб|gb|гб)\b", re.I)
_KNOWN_GB = (16, 32, 64, 128, 256, 512, 1024, 2048)


def sheet_ids(url):
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", str(url or ""))
    if not m:
        raise ValueError("Это не ссылка на Google Таблицу")
    g = re.search(r"[#?&]gid=(\d+)", url)
    return m.group(1), (g.group(1) if g else "0")


def export_url(url):
    sid, gid = sheet_ids(url)
    return (f"https://docs.google.com/spreadsheets/d/{sid}"
            f"/export?format=csv&gid={gid}")


# ---------- сервис-аккаунт (Sheets API) ----------

def sa_path():
    return beside("gservice.json")


def sa_email():
    """Email сервис-аккаунта — с ним нужно поделиться таблицей."""
    try:
        return json.load(open(sa_path(), encoding="utf-8")).get("client_email", "")
    except Exception:
        return ""


def _google_error(resp):
    """Человеческий текст из ответа Google: что именно не так."""
    try:
        msg = resp.json()["error"]["message"]
    except Exception:
        msg = (resp.text or "")[:300]
    if "has not been used in project" in msg or "it is disabled" in msg:
        return ("В проекте сервис-аккаунта не включён Google Sheets API. "
                "Включи: console.cloud.google.com → APIs & Services → "
                "Library → Google Sheets API → Enable. Затем минуту подожди.\n"
                f"(Google: {msg[:160]})")
    if resp.status_code in (403, 404):
        return ("Таблица не открыта сервис-аккаунту. Поделись ею (Читатель) с: "
                + (sa_email() or "email из gservice.json")
                + f"\n(Google: {msg[:160]})")
    return f"Google ответил {resp.status_code}: {msg[:200]}"


def api_rows(url):
    """Строки листа через Sheets API от имени сервис-аккаунта."""
    import requests
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    sid, gid = sheet_ids(url)
    try:
        creds = service_account.Credentials.from_service_account_file(
            sa_path(), scopes=[SCOPE])
    except Exception as e:
        raise RuntimeError(f"gservice.json не читается: {e}") from None
    try:
        creds.refresh(Request())
    except Exception as e:
        raise RuntimeError(
            "Не удалось получить токен по gservice.json: "
            f"{e}\nПроверь, что это ключ СЕРВИС-АККАУНТА (JSON с private_key) "
            "и что на компьютере верное время.") from None
    h = {"Authorization": f"Bearer {creds.token}"}

    meta = requests.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sid}"
        "?fields=sheets.properties", headers=h, timeout=30)
    if meta.status_code != 200:
        raise RuntimeError(_google_error(meta))
    sheets = meta.json().get("sheets") or []
    if not sheets:
        raise RuntimeError("В таблице нет листов")
    title = next((s["properties"]["title"] for s in sheets
                  if str(s["properties"].get("sheetId")) == gid),
                 sheets[0]["properties"]["title"])

    r = requests.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/"
        + urllib.parse.quote(f"'{title}'!A1:T500", safe="!:'"),
        headers=h, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(_google_error(r))
    return r.json().get("values") or []


def fetch_csv(url, timeout=30):
    req = urllib.request.Request(export_url(url),
                                 headers={"User-Agent": "PintelCheck/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            raise RuntimeError(
                "Google не пустил к таблице (код %d): она закрыта. Открой доступ: "
                "в таблице «Настройки доступа» → «Все, у кого есть ссылка» → "
                "«Читатель» — и нажми кнопку снова." % e.code) from None
        raise
    text = body.decode("utf-8-sig", "replace")
    if text.lstrip()[:120].lower().startswith(("<!doctype", "<html")):
        raise RuntimeError(
            "Google вернул страницу входа вместо таблицы. Открой доступ: "
            "в таблице «Настройки доступа» → «Все, у кого есть ссылка» → «Читатель».")
    return text


# ---------- разбор ----------

def _norm(s):
    s = str(s or "").strip().lower().replace("ё", "е").replace("\xa0", " ")
    for a, b in _TRANSLIT:
        s = s.replace(a, b)
    return re.sub(r"\(.*?\)", " ", s)


def _squash(s):
    return re.sub(r"[^a-z0-9]+", "", s)


def _name_map(models):
    """нормализованное имя → все коды с этим именем (iPhone 8 — это два кода)."""
    m = {}
    for code, name in models.items():
        m.setdefault(_squash(_norm(name)), []).append(code)
    return m


def _cap_token(s):
    """Объём из текста: (гб | None, текст без него)."""
    m = _CAP_RE.search(s)
    if not m:
        return None, s
    n = int(m.group(1))
    gb = n * 1024 if m.group(2).lower() in ("tb", "тб") else n
    return gb, s[:m.start()] + " " + s[m.end():]


def _cap_of_cell(cell):
    """Ячейка шапки «128», «256 GB», «1 ТБ» → гб."""
    s = _norm(cell)
    m = re.fullmatch(r"\s*(\d+)\s*(tb|тб|gb|гб)?\s*", s)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    if unit:
        return n * 1024 if unit in ("tb", "тб") else n
    return n if n in _KNOWN_GB else None


def _price_of(cell):
    s = str(cell or "").replace("\xa0", " ").strip()
    s = re.sub(r"₸|тг\.?|kzt|тенге", "", s, flags=re.I)
    s = re.sub(r"[ .,]", "", s)
    if not re.fullmatch(r"\d{4,9}", s):
        return None
    v = int(s)
    # Отсекаем то, что похоже на объём, а не на цену
    return v if v >= 5000 else None


def parse(rows, models):
    """Строки таблицы → (база {код: {гб: цена}}, не_распознанные строки).
    Принимает и готовые строки (Sheets API), и CSV-текст (запасной путь)."""
    if isinstance(rows, str):
        rows = list(csv.reader(io.StringIO(rows)))
    name_map = _name_map(models)
    base, unknown = {}, []
    cap_cols = {}                         # столбец → гб (последняя шапка объёмов)

    for row in rows:
        # Строка-шапка с объёмами? Шапка — это объёмы БЕЗ цен и БЕЗ моделей:
        # так «Модель, 64» (один столбец) тоже распознаётся, а строка данных
        # с ценами шапкой не считается.
        cand = {i: g for i, cell in enumerate(row)
                if (g := _cap_of_cell(cell))}
        if cand and not any("iphone" in _norm(c) for c in row) and \
           not any(_price_of(c) for i, c in enumerate(row) if i not in cand):
            cap_cols = cand
            continue

        # строка с моделью?
        codes = gb = name_col = None
        looks_like_iphone = False
        for i, cell in enumerate(row):
            s = _norm(cell)
            if "iphone" not in s:
                continue
            looks_like_iphone = True
            g, rest = _cap_token(s)
            found = name_map.get(_squash(rest))
            if found:
                codes, gb, name_col = found, g, i
                break
        if not codes:
            if looks_like_iphone and any(str(c).strip() for c in row):
                unknown.append(" | ".join(str(c).strip() for c in row
                                          if str(c).strip())[:90])
            continue

        got = False
        if gb:                              # объём прямо в названии
            for j, cell in enumerate(row):
                if j == name_col:
                    continue
                p = _price_of(cell)
                if p:
                    for c in codes:
                        base.setdefault(c, {})[str(gb)] = p
                    got = True
                    break
        elif cap_cols:                      # объёмы по столбцам шапки
            for j, g in cap_cols.items():
                if j < len(row):
                    p = _price_of(row[j])
                    if p:
                        for c in codes:
                            base.setdefault(c, {})[str(g)] = p
                        got = True
        if not got:
            unknown.append(" | ".join(str(c).strip() for c in row
                                      if str(c).strip())[:90])
    return base, unknown


# ---------- синхронизация ----------

def sync(url=None):
    """Скачивает таблицу и обновляет базовые цены в prices.json.
    Возвращает сводку. Бросает исключение с человеческим текстом при беде."""
    cfg = price.load()
    url = (url or cfg.get("гугл_таблица") or DEFAULT_URL).strip()
    models = json.load(open(bundled("core", "models.json"), encoding="utf-8"))

    import os
    if os.path.isfile(sa_path()):
        rows, source = api_rows(url), "api"
    else:
        rows, source = fetch_csv(url), "csv"
    base, unknown = parse(rows, models)
    if not base:
        raise RuntimeError(
            "В таблице не нашлось ни одной знакомой модели с ценой. "
            "Ожидаю лист, где в строках модели (iPhone 13, Айфон 13 Про…), "
            "а объёмы — в шапке столбцов или прямо в названии.")

    cfg["база"] = base
    cfg["гугл_таблица"] = url
    cfg["источник_прайса"] = source
    cfg["прайс_обновлён"] = time.strftime("%Y-%m-%d %H:%M")
    cfg.pop("_комментарий", None)          # заглушек больше нет
    with open(price.cfg_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)

    names = sorted({models[c] for c in base})
    return {"моделей": len(names),
            "позиций": sum(len(v) for v in base.values()),
            "модели": names,
            "не_распознано": unknown[:12],
            "обновлено": cfg["прайс_обновлён"]}
