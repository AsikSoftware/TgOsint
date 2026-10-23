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

import os

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

SA_PATH = "gservice.json"          # задаётся вызывающим: set_service_account(path)


def set_service_account(path):
    global SA_PATH
    SA_PATH = path


def sa_path():
    return SA_PATH


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
    """Ячейка «128», «256 GB», «1 ТБ», «Цена 128» → гб."""
    s = _norm(cell).strip()
    if len(s) > 14:
        return None
    nums = re.findall(r"\d+", s)
    if len(nums) != 1:
        return None
    n = int(nums[0])
    if re.search(r"\d+\s*(tb|тб)\b", s):
        return n * 1024
    if re.search(r"\d+\s*(gb|гб)\b", s):
        return n
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


_RANGE_RE = re.compile(r"^(\d{1,3})\s*[-–]\s*(\d{1,3})$")


def _wear_key(cell):
    """Ячейка шапки сетки износа батареи → ключ диапазона.
    По сырой ячейке: «100 (0-30)» живёт в скобках, которые _norm вырезает."""
    s = str(cell or "").strip().lower().replace("ё", "е").replace("\xa0", " ")
    if not s:
        return None
    if "нет информации" in s or "неизвест" in s:
        return "неизвестно"
    m = _RANGE_RE.match(s)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if hi <= 100:
            return f"{lo}-{hi}"
        return None
    if re.fullmatch(r"100\s*\(\s*0\s*[-–]\s*30\s*\)", s):
        return "100новый"
    if s == "100":
        return "100"
    return None


def parse(rows, models):
    """Строки таблицы → (база {код: {гб: цена}}, сетка_износа, не_распознанное).

    Понимает два мира:
      • прайс магазина с СЕТКОЙ ПО ИЗНОСУ БАТАРЕИ: шапка «Память | нет
        информации | 0-74 | … | 100 | 100 (0-30)», строка на каждый объём;
        база = цена идеала, сетка сохраняется целиком;
      • простые форматы: объёмы в шапке, в названии или отдельным столбцом.
    Варианты «(Esim)» — отдельные позиции региона, в базу не пишутся.
    Принимает и готовые строки (Sheets API), и CSV-текст (запасной путь)."""
    if isinstance(rows, str):
        rows = list(csv.reader(io.StringIO(rows)))
    name_map = _name_map(models)
    base = {}
    wear_grid = {}                        # код → {гб → {диапазон → цена}}
    cap_cols = {}                         # столбец → гб (последняя шапка объёмов)
    wear_cols = {}                        # столбец → диапазон износа
    esim_skipped = 0
    unmatched = {}                        # незнакомое имя → сколько строк
    no_price = set()                      # знакомые модели, но без цен в листе

    for row in rows:
        # шапка сетки износа? («Память | нет информации | 0-74 | … | 100»)
        cand_w = {i: k for i, cell in enumerate(row) if (k := _wear_key(cell))}
        if len(cand_w) >= 3:
            wear_cols = cand_w
            cap_cols = {}
            continue

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
        iphone_cell = ""
        for i, cell in enumerate(row):
            s = _norm(cell)
            if "iphone" not in s:
                continue
            if not iphone_cell:
                iphone_cell = str(cell).strip()
            g, rest = _cap_token(s)
            found = name_map.get(_squash(rest))
            if not found and g is None:
                # объём без единицы: «iPhone 13 Pro Max 256» — пробуем выкинуть
                # одно известное число (но не номер модели: сперва прямое имя)
                for m in re.finditer(r"\b(16|32|64|128|256|512|1024|2048)\b", s):
                    rest2 = s[:m.start()] + " " + s[m.end():]
                    found2 = name_map.get(_squash(rest2))
                    if found2:
                        found, g = found2, int(m.group(1))
                        break
            if found:
                codes, gb, name_col = found, g, i
                break
        # по сырой ячейке: _norm вырезает скобки, а «(Esim)» живёт именно в них
        if codes and "esim" in str(row[name_col]).lower():
            esim_skipped += 1             # региональный вариант — не перетираем обычный
            continue
        if not codes:
            if iphone_cell:
                unmatched[iphone_cell] = unmatched.get(iphone_cell, 0) + 1
            continue

        if gb is None and not cap_cols:
            # формат «модель | объём | цена»: объём отдельной ячейкой без шапки
            caps = [(j, g2) for j, c in enumerate(row) if j != name_col
                    and j not in wear_cols and (g2 := _cap_of_cell(c))]
            if len(caps) == 1:
                gb = caps[0][1]

        # сетка износа: цены по диапазонам, база — идеал. Пустые ячейки
        # СОХРАНЯЮТСЯ как None: «магазин не задал цену для этого износа» —
        # это стоп-сигнал, а не повод посчитать по-своему.
        if wear_cols and gb:
            cells = {k: (_price_of(row[j]) if j < len(row) else None)
                     for j, k in wear_cols.items()}
            filled = [v for v in cells.values() if v]
            if filled:
                ideal = cells.get("100новый") or cells.get("100") or max(filled)
                for c in codes:
                    base.setdefault(c, {})[str(gb)] = ideal
                    wear_grid.setdefault(c, {})[str(gb)] = cells
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
            no_price.add(models.get(codes[0], iphone_cell))
    unknown = [k + (f" ×{v}" if v > 1 else "") for k, v in unmatched.items()]
    if no_price:
        unknown.append("без цены в прайсе (пропущено): "
                       + ", ".join(sorted(no_price)))
    if esim_skipped:
        unknown.append(f"(esim-вариантов пропущено: {esim_skipped} — "
                       "регион по кабелю не определяется)")
    return base, wear_grid, unknown


# ---------- синхронизация ----------

def fetch_grid(url=None, models=None):
    """Скачивает таблицу → {"база", "сетка_износа", "сводка"}.
    Бросает исключение с человеческим текстом при беде."""
    url = (url or DEFAULT_URL).strip()
    if models is None:
        from ..analysis.passport import MODELS as models

    if os.path.isfile(sa_path()):
        rows, source = api_rows(url), "api"
    else:
        rows, source = fetch_csv(url), "csv"
    base, wear_grid, unknown = parse(rows, models)
    if not base:
        # Показываем, что программа ВИДИТ в листе: гадать больше не нужно.
        if isinstance(rows, str):
            rows = list(csv.reader(io.StringIO(rows)))
        sample = []
        for row in rows:
            line = " | ".join(str(c).strip() for c in row if str(c).strip())
            if line:
                sample.append(line[:72])
            if len(sample) >= 8:
                break
        raise RuntimeError(
            "В таблице не нашлось ни одной знакомой модели с ценой. "
            "Ожидаю лист, где в строках модели (iPhone 13, Айфон 13 Про…), "
            "а объёмы — в шапке столбцов, в названии или отдельным столбцом.\n\n"
            "Начало листа, как я его вижу:\n" + "\n".join(sample))

    names = sorted({models[c] for c in base})
    return {"база": base, "сетка_износа": wear_grid, "гугл_таблица": url,
            "источник": source, "обновлено": time.strftime("%Y-%m-%d %H:%M"),
            "моделей": len(names),
            "позиций": sum(len(v) for v in base.values()),
            "по_износу": bool(wear_grid),
            "модели": names,
            "не_распознано": unknown[:12]}
