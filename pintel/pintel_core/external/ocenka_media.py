# -*- coding: utf-8 -*-
"""Фото и видео сделки — через бота Оценки, а не через наш сервер.

Как это работает на точке:

  1. Приложение заводит короткий код и показывает ссылку с ним:
     `https://t.me/<бот>?start=p7KQ2M` (и QR на неё).
  2. Сотрудник открывает ссылку своим телефоном, бот сразу знает, КТО пришёл —
     по chat_id находит его в `users`. Это и есть оценщик сделки: отдельно спрашивать
     «кто проводил оценку» больше не нужно.
  3. Сотрудник шлёт боту видео и фото, бот складывает `file_id` в строку с этим кодом.
  4. Приложение видит их и создаёт сделку.

Почему так: Оценка хранит медиа не файлами, а `file_id` Telegram — значит хранение
бесплатное и ничего своего поднимать не нужно. А главное, видео обязательно: без него
Оценка не открывает карточку сделки.

Таблица обмена — одна, маленькая, в базе Оценки (DDL в deploy/оценка_бот/). Её код
Оценки не трогает; обработчик бота лежит там же отдельным файлом.
"""
from __future__ import annotations

import logging
import secrets

log = logging.getLogger("pintel.ocenka.media")

# Код диктуют голосом и набирают руками, поэтому ни одной пары, которую легко спутать:
# нет O и 0, I и 1, B и 8, S и 5, Z и 2.
АЛФАВИТ = "ACDEFGHJKLMNPQRTUVWXY345679"
ТАБЛИЦА = "kiosk_media"


def новый_код(n: int = 6) -> str:
    return "".join(secrets.choice(АЛФАВИТ) for _ in range(n))


def ссылка(бот: str, код: str) -> str:
    """Готовая ссылка с командой: открывший её сразу попадает на нужную сделку."""
    бот = str(бот or "").strip().lstrip("@").removeprefix("https://t.me/").strip("/")
    return f"https://t.me/{бот}?start=p{код}"


def _engine(url):
    from sqlalchemy import create_engine
    return create_engine(url, pool_pre_ping=True, future=True)


def завести(url: str, точка: str = "") -> str:
    """Создать строку обмена и вернуть код. Строка живёт сама по себе: если сотрудник
    передумал, она просто останется незакрытой и никому не мешает."""
    from sqlalchemy import text
    код = новый_код()
    with _engine(url).begin() as conn:
        conn.execute(text(f"INSERT INTO {ТАБЛИЦА} (code, point) VALUES (:c, :p)"),
                     {"c": код, "p": (точка or "")[:50]})
    return код


def состояние(url: str, код: str) -> dict:
    """Что бот успел собрать: видео, фото, кто прислал. Пусто — ещё не приходил."""
    from sqlalchemy import text
    with _engine(url).connect() as conn:
        row = conn.execute(text(
            f"SELECT m.video, m.photos, m.user_id, m.done, u.first_name, u.last_name, u.phone "
            f"FROM {ТАБЛИЦА} m LEFT JOIN users u ON u.id = m.user_id WHERE m.code = :c"),
            {"c": код}).mappings().first()
    if not row:
        return {"есть": False}
    фото = [x for x in str(row["photos"] or "").split("||") if x]
    имя = " ".join(x for x in (row["first_name"], row["last_name"]) if x) or (row["phone"] or "")
    return {"есть": True, "видео": row["video"] or "", "фото": фото,
            "оценщик_id": row["user_id"], "оценщик": имя, "готово": bool(row["done"])}


def закрыть(url: str, код: str, device_id: int | None = None) -> None:
    """Пометить обмен завершённым и привязать к созданной сделке — чтобы по коду было
    видно, куда ушли эти фото."""
    from sqlalchemy import text
    with _engine(url).begin() as conn:
        conn.execute(text(f"UPDATE {ТАБЛИЦА} SET done = true, device_id = :d WHERE code = :c"),
                     {"d": device_id, "c": код})


def описание(с: dict) -> str:
    """Строка для экрана: что уже пришло."""
    if not с.get("есть"):
        return "код не найден — заведите новый"
    части = []
    if с.get("оценщик"):
        части.append("оценщик: " + с["оценщик"])
    части.append("видео: есть" if с.get("видео") else "видео: ждём")
    if с.get("фото"):
        части.append(f"фото: {len(с['фото'])}")
    return " · ".join(части)
