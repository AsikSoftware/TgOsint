# -*- coding: utf-8 -*-
"""Импорт готовой оценки с киоска в Pintel Оценка (тестовую базу).

Наш сервер стоит на том же VPS и пишет в `pintel_ocenka_test` напрямую,
повторяя ровно ту вставку, что делает бот (`create_device_from_fsm_data`):
device → device_imeis, клиент в `users` (роль 3), статус «Ожидает оценку».
Код Оценки не трогаем.

Фото/видео, которые клиент загрузил по QR, прогоняем через Telegram Bot API
ТЕМ ЖЕ тестовым токеном, что крутит тест-бота, — получаем `file_id`, которые
бот затем показывает как у обычной сделки (photo_phone через «||», video_phone).

Всё включается только при заданном PINTEL_OCENKA_DB_URL; иначе импорт выключен.
"""
from __future__ import annotations

import logging
import os

import httpx
from sqlalchemy import create_engine, text

from ..config import settings
from ..db import now
from ..models import MEDIA_VIDEO, Evaluation

log = logging.getLogger("pintel.ocenka")

_engine = None


class ImportError_(RuntimeError):
    """Человеческий текст, почему импорт не удался."""


def _ocenka_engine():
    global _engine
    if _engine is None:
        if not settings.ocenka_db_url:
            raise ImportError_("импорт в Оценку выключен (PINTEL_OCENKA_DB_URL не задан)")
        _engine = create_engine(settings.ocenka_db_url, pool_pre_ping=True, future=True)
    return _engine


# ---------------------------------------------------------------- Telegram

def _tg_upload(path: str, kind: str) -> str | None:
    """Шлём файл тест-боту в чат-хранилище, возвращаем Telegram file_id."""
    token, chat = settings.ocenka_bot_token, settings.ocenka_media_chat
    if not token or not chat:
        log.warning("ocenka: токен/чат для фото не заданы — медиа без file_id")
        return None
    method, field, pick = (
        ("sendVideo", "video", lambda r: r["video"]["file_id"])
        if kind == MEDIA_VIDEO
        else ("sendPhoto", "photo", lambda r: r["photo"][-1]["file_id"])
    )
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        with open(path, "rb") as fh:
            resp = httpx.post(url, data={"chat_id": chat},
                              files={field: (os.path.basename(path), fh)}, timeout=120)
        js = resp.json()
        if not js.get("ok"):
            log.warning("ocenka: Telegram отклонил %s: %s", method, js.get("description"))
            return None
        return pick(js["result"])
    except Exception as exc:                                     # noqa: BLE001
        log.warning("ocenka: загрузка медиа не удалась (%s): %s", path, exc)
        return None


def _media_file_ids(db, ev: Evaluation) -> tuple[list[str], list[str]]:
    """Прогоняет медиа через Telegram, кэширует file_id в нашей БД.
    → (file_id фото, file_id видео)."""
    photos, videos = [], []
    for m in ev.media:
        if not m.tg_file_id:
            m.tg_file_id = _tg_upload(os.path.join(settings.media_dir, m.filename), m.kind)
        if not m.tg_file_id:
            continue
        (videos if m.kind == MEDIA_VIDEO else photos).append(m.tg_file_id)
    db.commit()
    return photos, videos


# ---------------------------------------------------------------- поля сделки

def _phone_status(ev: Evaluation) -> str | None:
    """Грубый статус состояния по вердикту киоска (админ уточнит)."""
    rep = ev.report or {}
    итог = ((rep.get("детали_вердикт") or {}).get("итог")) or ""
    if итог == "родные":
        return "Не был в ремонте"
    if итог in ("замена", "ремонт"):
        return "Ранее был в ремонте"
    return None


def _comment_ocenka(ev: Evaluation) -> str:
    rep = ev.report or {}
    parts = []
    dv = (rep.get("детали_вердикт") or {}).get("итог")
    if dv:
        parts.append(f"Детали: {dv}")
    if ev.apple_summary:
        parts.append(f"Apple: {ev.apple_summary}")
    if ev.locks_summary and ev.locks_summary != "чисто":
        parts.append(f"Замки: {ev.locks_summary}")
    parts.append(f"Киоск №{ev.number} от {ev.day}")
    return " · ".join(parts)[:4000]


def _imeis(ev: Evaluation) -> list[tuple[str, bool, bool]]:
    """→ [(imei, verifi, first)]. Первым — основной IMEI сделки."""
    from pintel_core.external import sickw
    out, seen = [], set()
    rep = ev.report or {}
    pas = rep.get("паспорт") or {}
    primary = (ev.imei or pas.get("imei") or "").strip()
    for imei in [primary, (pas.get("imei2") or "").strip()]:
        if imei and imei not in seen:
            seen.add(imei)
            out.append((imei, bool(sickw.luhn_ok(imei)), imei == primary))
    return out


# ---------------------------------------------------------------- импорт

def import_evaluation(db, ev: Evaluation) -> dict:
    """Создаёт сделку в Оценке и помечает нашу оценку импортированной.
    Идемпотентно: повторный вызов вернёт уже присвоенный номер."""
    if ev.ocenka_device_id:
        return {"ok": True, "device_id": ev.ocenka_device_id, "повтор": True}
    if not settings.ocenka_enabled:
        raise ImportError_("импорт в Оценку выключен (PINTEL_OCENKA_DB_URL не задан)")
    if not ev.model_name:
        raise ImportError_("не определена модель — импорт невозможен")
    if not ev.capacity_gb:
        raise ImportError_("не определён объём памяти — импорт невозможен")
    if not (ev.client_name and ev.client_phone):
        raise ImportError_("не заполнены имя и телефон клиента")

    photos, videos = _media_file_ids(db, ev)
    eng = _ocenka_engine()

    with eng.begin() as conn:
        shop_id = None
        if settings.ocenka_shop_litera:
            shop_id = conn.scalar(text("SELECT id FROM shops WHERE litera = :lit"),
                                  {"lit": settings.ocenka_shop_litera})
            if shop_id is None:
                raise ImportError_(f"в Оценке нет магазина с литерой «{settings.ocenka_shop_litera}»")

        phone = ev.client_phone.strip()[:13]
        client_id = conn.scalar(text("SELECT id FROM users WHERE phone = :ph"), {"ph": phone})
        if client_id is None:
            client_id = conn.scalar(text("""
                INSERT INTO users (first_name, last_name, phone, active, lang, staff_id)
                VALUES (:fn, :ln, :ph, true, 'ru', 3)
                RETURNING id
            """), {"fn": ev.client_name.strip()[:150], "ln": None, "ph": phone})

        device_id = conn.scalar(text("""
            INSERT INTO devices (
                producer, model, code_name, ddr, akb, akb_exact, color, sim,
                box, cord, panic_full, phone_status, online, status_id,
                price_grade_auto, user_client, shop_id_grade,
                photo_phone, video_phone, comment, comment_ocenka
            ) VALUES (
                :producer, :model, :code_name, :ddr, :akb, :akb_exact, :color, :sim,
                :box, :cord, :panic_full, :phone_status, false, :status_id,
                :price_auto, :user_client, :shop_id,
                :photo_phone, :video_phone, :comment, :comment_ocenka
            ) RETURNING id
        """), {
            "producer": "Apple",
            "model": ev.model_name[:50],
            "code_name": (ev.model_code or None),
            "ddr": int(ev.capacity_gb),
            "akb": (f"{ev.battery_health}%" if ev.battery_health is not None else None),
            "akb_exact": ev.battery_health,
            "color": (ev.colour or None),
            "sim": None,
            "box": ev.has_box,
            "cord": ev.has_cord,
            "panic_full": ev.panic_full,
            "phone_status": _phone_status(ev),
            "status_id": settings.ocenka_status_id,
            "price_auto": ev.price_offer,
            "user_client": client_id,
            "shop_id": shop_id,
            "photo_phone": ("||".join(photos) if photos else None),
            "video_phone": (videos[0][:200] if videos else None),
            "comment": (ev.verdict or None),
            "comment_ocenka": _comment_ocenka(ev),
        })

        for imei, verifi, first in _imeis(ev):
            conn.execute(text("""
                INSERT INTO device_imeis (device_id, imei, verifi, first)
                VALUES (:d, :imei, :verifi, :first)
            """), {"d": device_id, "imei": imei[:20], "verifi": verifi, "first": first})

    ev.ocenka_device_id = int(device_id)
    ev.ocenka_imported_at = now()
    db.commit()
    log.info("ocenka: оценка №%s импортирована как сделка №%s", ev.number, device_id)
    return {"ok": True, "device_id": int(device_id), "фото": len(photos), "видео": len(videos)}
