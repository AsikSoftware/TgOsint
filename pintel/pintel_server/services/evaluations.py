# -*- coding: utf-8 -*-
"""Оценки: приём с киоска, номера талонов, решения кассы."""
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from .. import audit
from ..config import settings
from ..db import now
from ..models import (MEDIA_PHOTO, MEDIA_VIDEO, ROLE_CASHIER, ST_AT_COUNTER, ST_BOUGHT, ST_DECLINED,
                      ST_IN_WORK, ST_NEW, ST_VIEWED, Device, Evaluation, EvaluationMedia)


def local_day(dt=None) -> str:
    dt = dt or now()
    return dt.astimezone(ZoneInfo(settings.tz)).strftime("%Y-%m-%d")


def local_time(dt) -> str:
    return dt.astimezone(ZoneInfo(settings.tz)).strftime("%H:%M") if dt else ""


def label(ev) -> str:
    """«№12» или «без номера»: номер заявки выдаётся только после имени и телефона клиента."""
    return f"№{ev.number}" if ev.number else "без номера"


def next_number(db, point_id, day) -> int:
    q = select(func.max(Evaluation.number)).where(Evaluation.day == day)
    q = q.where(Evaluation.point_id == point_id) if point_id else q.where(Evaluation.point_id.is_(None))
    return (db.scalar(q) or 0) + 1


def apple_summary(rep) -> str:
    hist = rep.get("apple_история") or {}
    if not hist:
        return "ждёт раздел на телефоне"
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
        client_id=cid or secrets.token_hex(8), number=None, day=day,
        kiosk_id=kiosk.id, point_id=kiosk.point_id, device_id=device.id if device else None,
        serial=serial, imei=(pas.get("imei") or None), model_name=pas.get("модель"),
        model_code=pas.get("код_модели"), capacity_gb=sto.get("объём_гб"), colour=pas.get("цвет"),
        ios=pas.get("ios"), battery_health=bat.get("здоровье_%"), battery_cycles=bat.get("циклы"),
        verdict=(rep.get("итог") or {}).get("вердикт"), price_offer=price.get("цена"),
        price_column=price.get("основание"), apple_summary=apple_summary(rep)[:120],
        locks_summary=locks_summary(rep)[:120], status=ST_NEW, report=rep,
        snapshot=payload.get("snapshot"), public_token=secrets.token_urlsafe(12),
        media_token=secrets.token_urlsafe(12)[:32],
    )
    db.add(ev)
    db.flush()
    audit.log(db, None, "evaluation.create",
              f"Оценка {label(ev)}: {ev.model_name or '?'} {ev.capacity_gb or '?'} ГБ, "
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
    audit.log(db, None, "evaluation.update", f"Оценка {label(ev)}: данные обновлены с киоска ({ev.apple_summary})",
              entity="evaluation", entity_id=ev.id, kiosk=kiosk)
    db.commit()
    return ev


def client_decision(db, kiosk, ev: Evaluation, decision: str):
    ev.status = ST_AT_COUNTER if decision == "sell" else ST_VIEWED
    audit.log(db, None, "evaluation.client",
              f"Оценка {label(ev)}: клиент {'идёт к кассе' if decision == 'sell' else 'просто смотрел'}",
              entity="evaluation", entity_id=ev.id, kiosk=kiosk)
    db.commit()


def take(db, user, ev: Evaluation):
    ev.assigned_user_id = user.id
    if ev.status in (ST_NEW, ST_AT_COUNTER, ST_VIEWED):
        ev.status = ST_IN_WORK
    audit.log(db, user, "evaluation.take", f"Взял(а) в работу оценку {label(ev)}", entity="evaluation", entity_id=ev.id)
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
    what = (f"Оформил(а) выкуп {label(ev)} {ev.model_name or ''} за {final_price} {settings.currency}"
            if kind == ST_BOUGHT else f"Отказ по {label(ev)}: {note or 'без причины'}")
    if kind == ST_BOUGHT and ev.price_offer and final_price != ev.price_offer:
        what += f" (прайс {ev.price_offer})"
    audit.log(db, user, "evaluation." + kind, what, entity="evaluation", entity_id=ev.id,
              details={"до": before, "после": {"статус": kind, "цена": ev.final_price}, "осмотр": inspection})
    db.commit()


def _yn(v):
    return "да" if v else ("нет" if v is False else "—")


def set_client_details(db, user, ev: Evaluation, *, name=None, phone=None,
                       box=None, cord=None, panic=None) -> Evaluation:
    """Сотрудник в кассе записывает имя/телефон клиента, коробку/шнур/panic.
    Номер заявки выдаётся только когда есть имя и телефон; клиент сам ничего не вводит."""
    if name is not None:
        ev.client_name = (name.strip()[:120] or None)
    if phone is not None:
        ev.client_phone = (phone.strip()[:20] or None)
    if box is not None:
        ev.has_box = box
    if cord is not None:
        ev.has_cord = cord
    if panic is not None:
        ev.panic_full = panic
    db.commit()
    assign_number(db, ev)                      # сначала номер (если есть имя и телефон), потом запись в журнал
    audit.log(db, user, "evaluation.client_data",
              f"Данные клиента по заявке {label(ev)}: {ev.client_name or '—'}, {ev.client_phone or '—'}; "
              f"коробка: {_yn(ev.has_box)}, шнур: {_yn(ev.has_cord)}",
              entity="evaluation", entity_id=ev.id)
    db.commit()
    return ev


from pintel_core.analysis.capabilities import apple_tracked_parts
from pintel_core.analysis.parts import APPLE_PART_ORDER as PARTS_STAFF, APPLE_STATES

PART_STATES = {k: v[0] for k, v in APPLE_STATES.items()}
_SEVERITY = {k: v[2] for k, v in APPLE_STATES.items()}


def parts_check(ev: Evaluation) -> dict:
    """Нужна ли сверка раздела «Детали и обслуживание» с экрана телефона и что отметил сотрудник.
    Автоматика даёт зелёный только с подтверждением Apple; иначе без сверки сделка в Оценку не уйдёт.
    Показываем только те детали, по которым Apple вообще ведёт историю для этой модели."""
    pv = (ev.report or {}).get("детали_вердикт") or {}
    names = dict(PARTS_STAFF)
    staff = ev.staff_parts or {}
    marks = {k: v for k, v in staff.items() if k in names and v in PART_STATES}
    tracked = set(apple_tracked_parts(ev.model_code))
    строки = [(k, n) for k, n in PARTS_STAFF if not tracked or k in tracked or k in marks]
    return {"авто": pv.get("итог"), "почему": pv.get("почему") or "", "строки": строки,
            "нужна_сверка": pv.get("итог") not in ("родные", "ремонт", "замена"),
            "отмечено": bool(marks), "метки": marks,
            "замены": [f"{names[k]}: {PART_STATES[v]}" for k, v in marks.items() if _SEVERITY.get(v) == "bad"],
            "сервис": [names[k] for k, v in marks.items() if _SEVERITY.get(v) in ("repaired", "used")],
            "кто": staff.get("кто"), "когда": staff.get("когда"), "примечание": staff.get("примечание") or ""}


def set_staff_parts(db, user, ev: Evaluation, marks: dict, note: str = "") -> Evaluation:
    """Сотрудник отметил, что показывает телефон в «Детали и обслуживание»."""
    names = dict(PARTS_STAFF)
    clean = {k: v for k, v in (marks or {}).items() if k in names and v in PART_STATES}
    ev.staff_parts = {**clean, "примечание": (note or "").strip()[:300], "кто": user.name, "когда": now().isoformat()}
    db.commit()
    audit.log(db, user, "evaluation.parts",
              f"Сверка «Детали и обслуживание» по заявке {label(ev)}: "
              + (", ".join(f"{names[k]} — {PART_STATES[v]}" for k, v in clean.items()) or "без отметок"),
              entity="evaluation", entity_id=ev.id, details=ev.staff_parts)
    db.commit()
    return ev


def ensure_media_token(db, ev: Evaluation) -> str:
    """Токен временной ссылки /m/ (фото/видео с телефона сотрудника). Создаём лениво."""
    if not ev.media_token:
        ev.media_token = secrets.token_urlsafe(12)[:32]
        db.commit()
    return ev.media_token


def report_url(ev: Evaluation) -> str:
    return f"{settings.public_url}/r/{ev.public_token}"


def media_url(ev: Evaluation) -> str | None:
    return f"{settings.public_url}/m/{ev.media_token}" if ev.media_token else None


def assign_number(db, ev: Evaluation):
    """Номер заявки выдаётся только когда есть имя и телефон клиента. Идемпотентно."""
    if ev.number or not (ev.client_name and ev.client_phone):
        return ev.number
    ev.number = next_number(db, ev.point_id, ev.day)
    audit.log(db, None, "evaluation.number",
              f"Заявке присвоен №{ev.number} ({ev.client_name}, {ev.client_phone})",
              entity="evaluation", entity_id=ev.id)
    db.commit()
    return ev.number


def intake_state(ev: Evaluation) -> dict:
    """Что киоск спрашивает у сервера, пока показан результат: номер заявки (его выдаёт
    сотрудник в кассе, записав имя и телефон клиента), ссылка на отчёт для QR, медиа."""
    return {"id": ev.id, "номер": ev.number, "ссылка_отчёта": report_url(ev),
            "клиент": {"имя": ev.client_name, "телефон": ev.client_phone,
                       "коробка": ev.has_box, "шнур": ev.has_cord},
            "медиа": media_list(ev), "готово": bool(ev.client_name and ev.client_phone),
            "импортирована": bool(ev.ocenka_device_id), "номер_сделки": ev.ocenka_device_id}


def media_list(ev: Evaluation) -> list[dict]:
    return [{"id": m.id, "вид": m.kind, "имя": m.filename, "тип": m.content_type,
             "размер": m.size, "загружено": local_time(m.uploaded_at)} for m in ev.media]


def add_media(db, ev: Evaluation, kind: str, filename: str, content_type=None, size=None) -> EvaluationMedia:
    m = EvaluationMedia(eval_id=ev.id, kind=kind, filename=filename,
                        content_type=(content_type or "")[:80], size=size)
    db.add(m)
    db.commit()
    return m


def day_stats(db, day, point_id=None):
    q = select(Evaluation).where(Evaluation.day == day)
    if point_id:
        q = q.where(Evaluation.point_id == point_id)
    rows = db.scalars(q).all()
    bought = [r for r in rows if r.status == ST_BOUGHT]
    return {"оценок": len(rows), "выкуплено": len(bought),
            "сумма": sum(r.final_price or 0 for r in bought),
            "конверсия": round(100 * len(bought) / len(rows)) if rows else 0}
