# -*- coding: utf-8 -*-
"""Оценки: приём с киоска, номера талонов, решения кассы."""
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from .. import audit
from ..config import settings
from ..db import now
from ..models import (ROLE_CASHIER, ST_AT_COUNTER, ST_BOUGHT, ST_DECLINED, ST_IN_WORK, ST_NEW, ST_VIEWED,
                      Device, Evaluation)


def local_day(dt=None) -> str:
    dt = dt or now()
    return dt.astimezone(ZoneInfo(settings.tz)).strftime("%Y-%m-%d")


def local_time(dt) -> str:
    return dt.astimezone(ZoneInfo(settings.tz)).strftime("%H:%M") if dt else ""


def next_number(db, point_id, day) -> int:
    q = select(func.max(Evaluation.number)).where(Evaluation.day == day)
    q = q.where(Evaluation.point_id == point_id) if point_id else q.where(Evaluation.point_id.is_(None))
    return (db.scalar(q) or 0) + 1


def apple_summary(rep) -> str:
    hist = rep.get("apple_история") or {}
    if not hist:
        return "история не получена"
    changed = [v["деталь"] for v in hist.values() if v.get("меняли")]
    return "всё родное" if not changed else ("менялось: " + ", ".join(changed[:3]))


def locks_summary(rep) -> str:
    leg = rep.get("правовой") or {}
    sk = rep.get("sickw") or {}
    parts = []
    if sk.get("в_чёрном_списке") is True:
        parts.append("ЧЁРНЫЙ СПИСОК")
    if leg.get("mdm") is True:
        parts.append("MDM")
    if leg.get("найти_iphone") == "включён" or sk.get("fmi_включён") is True:
        parts.append("Найти iPhone вкл.")
    if leg.get("пароль"):
        parts.append("пароль")
    return ", ".join(parts) if parts else "чисто"


def create_from_kiosk(db, kiosk, payload: dict) -> tuple[Evaluation, bool]:
    """→ (оценка, создана_сейчас). Повтор с тем же client_id возвращает старую запись."""
    cid = str(payload.get("client_id") or "")[:64]
    if cid:
        old = db.scalar(select(Evaluation).where(Evaluation.client_id == cid))
        if old:
            return old, False
    rep = payload.get("report") or {}
    pas = rep.get("паспорт") or {}
    bat = rep.get("батарея") or {}
    sto = rep.get("память") or {}
    price = rep.get("цена") or {}
    day = local_day()
    serial = (pas.get("серийник") or "")[:32] or None
    device = None
    if serial:
        device = db.scalar(select(Device).where(Device.serial == serial))
        if not device:
            device = Device(serial=serial, imei=pas.get("imei"), model_code=pas.get("код_модели"),
                            model_name=pas.get("модель"))
            db.add(device)
            db.flush()
        device.last_seen_at = now()
        device.evaluations_count = (device.evaluations_count or 0) + 1
        device.imei = device.imei or pas.get("imei")
    ev = Evaluation(
        client_id=cid or secrets.token_hex(8), number=next_number(db, kiosk.point_id, day), day=day,
        kiosk_id=kiosk.id, point_id=kiosk.point_id, device_id=device.id if device else None,
        serial=serial, imei=(pas.get("imei") or None), model_name=pas.get("модель"),
        model_code=pas.get("код_модели"), capacity_gb=sto.get("объём_гб"), colour=pas.get("цвет"),
        ios=pas.get("ios"), battery_health=bat.get("здоровье_%"), battery_cycles=bat.get("циклы"),
        verdict=(rep.get("итог") or {}).get("вердикт"), price_offer=price.get("цена"),
        price_column=price.get("основание"), apple_summary=apple_summary(rep)[:120],
        locks_summary=locks_summary(rep)[:120], status=ST_NEW, report=rep,
        snapshot=payload.get("snapshot"), public_token=secrets.token_urlsafe(12),
    )
    db.add(ev)
    db.flush()
    audit.log(db, None, "evaluation.create",
              f"Оценка №{ev.number}: {ev.model_name or '?'} {ev.capacity_gb or '?'} ГБ, "
              f"батарея {ev.battery_health or '?'} %, цена {ev.price_offer or '—'}",
              entity="evaluation", entity_id=ev.id, kiosk=kiosk,
              details={"серийник": serial, "вердикт": ev.verdict, "повторно": bool(device and device.evaluations_count > 1)})
    db.commit()
    return ev, True


def update_from_kiosk(db, kiosk, ev: Evaluation, report: dict, snapshot_patch: dict | None = None) -> Evaluation:
    """Киоск дослал уточнённый отчёт (обычно — историю Apple, открытую позже).
    Решение кассы не трогаем: обновляются только данные телефона."""
    if ev.kiosk_id != kiosk.id:
        raise PermissionError("оценка другого киоска")
    rep = report or {}
    ev.report = rep
    if snapshot_patch and isinstance(ev.snapshot, dict):
        ev.snapshot = {**ev.snapshot, **snapshot_patch}
    elif snapshot_patch:
        ev.snapshot = snapshot_patch
    ev.apple_summary = apple_summary(rep)[:120]
    ev.locks_summary = locks_summary(rep)[:120]
    ev.verdict = (rep.get("итог") or {}).get("вердикт") or ev.verdict
    price = rep.get("цена") or {}
    if price.get("цена") and ev.status not in (ST_BOUGHT, ST_DECLINED):
        ev.price_offer = price.get("цена")
        ev.price_column = price.get("основание")
    audit.log(db, None, "evaluation.update", f"Оценка №{ev.number}: данные обновлены с киоска ({ev.apple_summary})",
              entity="evaluation", entity_id=ev.id, kiosk=kiosk)
    db.commit()
    return ev


def client_decision(db, kiosk, ev: Evaluation, decision: str):
    ev.status = ST_AT_COUNTER if decision == "sell" else ST_VIEWED
    audit.log(db, None, "evaluation.client",
              f"Оценка №{ev.number}: клиент {'идёт к кассе' if decision == 'sell' else 'просто смотрел'}",
              entity="evaluation", entity_id=ev.id, kiosk=kiosk)
    db.commit()


def take(db, user, ev: Evaluation):
    ev.assigned_user_id = user.id
    if ev.status in (ST_NEW, ST_AT_COUNTER, ST_VIEWED):
        ev.status = ST_IN_WORK
    audit.log(db, user, "evaluation.take", f"Взял(а) в работу оценку №{ev.number}", entity="evaluation", entity_id=ev.id)
    db.commit()


class DecisionError(ValueError):
    pass


def decide(db, user, ev: Evaluation, kind: str, final_price, note: str = "", inspection=None, deal_kind="buyout"):
    """kind: bought | declined. Кассир не может дать больше цены прайса — это право старшего."""
    if kind not in (ST_BOUGHT, ST_DECLINED):
        raise DecisionError("неизвестное решение")
    if kind == ST_BOUGHT:
        if final_price is None:
            raise DecisionError("укажите итоговую цену")
        if user.role == ROLE_CASHIER and ev.price_offer and final_price > ev.price_offer:
            raise DecisionError("цена выше прайса — нужен старший сотрудник")
    before = {"статус": ev.status, "цена": ev.final_price}
    ev.status = kind
    ev.final_price = final_price if kind == ST_BOUGHT else None
    ev.deal_kind = deal_kind
    ev.inspection = inspection or {}
    ev.decision_note = (note or "")[:2000]
    ev.decided_at = now()
    ev.decided_by_id = user.id
    ev.assigned_user_id = ev.assigned_user_id or user.id
    what = (f"Оформил(а) выкуп №{ev.number} {ev.model_name or ''} за {final_price} {settings.currency}"
            if kind == ST_BOUGHT else f"Отказ по №{ev.number}: {note or 'без причины'}")
    if kind == ST_BOUGHT and ev.price_offer and final_price != ev.price_offer:
        what += f" (прайс {ev.price_offer})"
    audit.log(db, user, "evaluation." + kind, what, entity="evaluation", entity_id=ev.id,
              details={"до": before, "после": {"статус": kind, "цена": ev.final_price}, "осмотр": inspection})
    db.commit()


def day_stats(db, day, point_id=None):
    q = select(Evaluation).where(Evaluation.day == day)
    if point_id:
        q = q.where(Evaluation.point_id == point_id)
    rows = db.scalars(q).all()
    bought = [r for r in rows if r.status == ST_BOUGHT]
    return {"оценок": len(rows), "выкуплено": len(bought),
            "сумма": sum(r.final_price or 0 for r in bought),
            "конверсия": round(100 * len(bought) / len(rows)) if rows else 0}
