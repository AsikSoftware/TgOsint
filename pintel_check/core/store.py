"""Хранилище приёмок. SQLite из стандартной библиотеки — ничего ставить не надо,
и упаковка в exe от этого не усложняется.

В бэкенд пишем МАКСИМУМ: сырые данные целиком, чтобы потом можно было
пересчитать вердикты новыми правилами по уже принятым аппаратам, не трогая
телефоны. Во фронт отдаём только понятное.
"""
import json, os, sqlite3, time
from .paths import beside

# Рядом с программой, а НЕ внутри неё: внутри собранного exe лежит временная
# папка, которую система стирает при выходе — база пропадала бы каждый раз.
DB = beside("data", "checks.db")


def _conn():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS checks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        создан     TEXT,
        udid       TEXT,
        серийник   TEXT,
        imei       TEXT,
        модель     TEXT,
        этап       INTEGER DEFAULT 1,
        вердикт    TEXT,
        цена       INTEGER,
        кабель     TEXT,   -- сырьё с кабеля, JSON
        apple      TEXT,   -- вердикт Apple, JSON
        sickw      TEXT,   -- внешняя база, JSON
        этап2      TEXT,   -- результаты ручных проверок, JSON
        этап3      TEXT    -- финал: фото, документы, выплата
    )""")
    c.commit()
    return c


def create(udid, res, raw):
    c = _conn()
    p = res["паспорт"]
    cur = c.execute(
        "INSERT INTO checks(создан,udid,серийник,imei,модель,вердикт,кабель) VALUES(?,?,?,?,?,?,?)",
        (time.strftime("%Y-%m-%d %H:%M:%S"), udid, p["серийник"], p["imei"],
         p["модель"], res["итог"]["вердикт"],
         json.dumps({"вердикты": res, "сырьё": _clean(raw)}, ensure_ascii=False, default=str)))
    c.commit()
    i = cur.lastrowid
    c.close()
    return i


def update(check_id, **fields):
    if not fields:
        return
    c = _conn()
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = [json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else v
            for v in fields.values()]
    c.execute(f"UPDATE checks SET {cols} WHERE id=?", vals + [check_id])
    c.commit()
    c.close()


def get(check_id):
    c = _conn()
    c.row_factory = sqlite3.Row
    r = c.execute("SELECT * FROM checks WHERE id=?", (check_id,)).fetchone()
    c.close()
    return dict(r) if r else None


def recent(limit=50):
    c = _conn()
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT id,создан,модель,серийник,вердикт,цена,этап FROM checks "
        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def _clean(raw):
    """Байтовые поля в JSON не кладутся: короткие расшифровываем как текст,
    длинные заменяем пометкой с длиной — сырьё должно оставаться читаемым."""
    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        if isinstance(o, (bytes, bytearray)):
            b = bytes(o).rstrip(b"\x00")
            if b and len(b) <= 64 and all(32 <= ch < 127 for ch in b):
                return b.decode("ascii")
            return f"<{len(o)} байт>"
        return o
    return walk(raw)
