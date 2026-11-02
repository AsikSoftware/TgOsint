# -*- coding: utf-8 -*-
"""API киоска. Авторизация — заголовок X-Kiosk-Token (токен выдаёт администратор в Настройках)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

import secrets

from .. import audit
from ..auth import current_kiosk, new_kiosk_token
from ..config import settings
from ..db import get_db, now
from ..models import Evaluation, Kiosk, PhoneTest, Point
from ..services import evaluations as ev_service
from ..services import ocenka_import
from ..services import price as price_service
from ..services import sickw_service

router = APIRouter(prefix="/api/kiosk", tags=["kiosk"])


class SickwIn(BaseModel):
    imei: str
    fresh: bool = False
    services: list[int] | None = None     # не по умолчанию: запечатанному нужна другая служба


class EvaluationIn(BaseModel):
    client_id: str
    report: dict
    snapshot: dict | None = None


class DecisionIn(BaseModel):
    decision: str          # sell | viewed


class UpdateIn(BaseModel):
    report: dict
    snapshot_patch: dict | None = None


class HeartbeatIn(BaseModel):
    version: str | None = None
    status: dict | None = None


def _own(db, kiosk, ev_id):
    ev = db.get(Evaluation, ev_id)
    if not ev or ev.kiosk_id != kiosk.id:
        raise HTTPException(404, "оценка не найдена")
    return ev


class RegisterIn(BaseModel):
    key: str
    machine: str
    point: str | None = None
    version: str | None = None


@router.post("/register")
def register(body: RegisterIn, db: DbSession = Depends(get_db)):
    """Киоск заводит себя сам. → токен, которым он дальше ходит в API.

    Токены по точкам руками больше не раздают: это осталось от версии, где каждый киоск
    заводили отдельно, и ровно из-за этого ни одна точка не была подключена, а общей базы не
    получалось. Теперь у всех один адрес сервера и один ключ привязки (он в сборке киоска),
    а сервер выдаёт каждому свой токен и показывает новый киоск в «Настройки → Киоски» —
    незнакомый отключается одной кнопкой.

    Узнаёт себя киоск по имени машины: после переустановки он найдёт свою прежнюю строку, а
    не заведёт вторую. Токен при этом перевыпускается — прежний перестаёт работать.
    """
    if not settings.kiosk_key or body.key != settings.kiosk_key:
        raise HTTPException(403, "неверный ключ привязки киоска")
    машина = (body.machine or "").strip()[:80]
    if not машина:
        raise HTTPException(400, "киоск не назвал себя (machine)")
    k = db.scalar(select(Kiosk).where(Kiosk.machine == машина))
    if k and not k.is_active:
        raise HTTPException(403, "этот киоск отключён администратором")
    токен, хэш = new_kiosk_token()
    if k is None:
        точка = (body.point or "").strip()[:40]
        имя = (f"{точка} · {машина}" if точка else машина)[:80]
        if db.scalar(select(Kiosk).where(Kiosk.name == имя)):
            имя = f"{имя[:72]} {secrets.token_hex(3)}"
        k = Kiosk(name=имя, machine=машина, token_hash=хэш,
                  point_id=db.scalar(select(Point.id).where(Point.name == точка)) if точка else None)
        db.add(k)
        db.flush()
        audit.log(db, None, "kiosk.register", f"Киоск «{k.name}» привязался сам", entity="kiosk",
                  entity_id=k.id, kiosk=k)
    else:
        k.token_hash = хэш
    k.version = (body.version or k.version or "")[:32]
    k.last_seen_at = now()
    db.commit()
    return {"токен": токен, "киоск": k.name, "точка": k.point.name if k.point else None}


@router.get("/config")
def config(kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    grid = price_service.current(db)
    return {
        "киоск": kiosk.name, "точка": kiosk.point.name if kiosk.point else None,
        "валюта": settings.currency, "возврат_с": settings.kiosk_return_seconds,
        "история_apple_с": settings.apple_history_seconds,
        "прайс_обновлён": grid.fetched_at.isoformat() if grid else None,
        "прайс_версия": grid.id if grid else None,
        "sickw": bool(settings.sickw_key), "время_сервера": now().isoformat(),
        "публичный_адрес": settings.public_url,
    }


@router.get("/price")
def price(kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    grid = price_service.current(db)
    if not grid:
        raise HTTPException(404, "прайс ещё не загружен на сервере — Настройки → Обновить прайс")
    return {"версия": grid.id, "обновлён": grid.fetched_at.isoformat(), "сетка": grid.grid}


@router.post("/sickw")
def sickw(body: SickwIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    try:
        r = sickw_service.lookup(db, body.imei.strip(), services=body.services or None,
                                 use_cache=not body.fresh)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(502, str(e))
    r.pop("сырые_ответы", None)
    return r


@router.post("/evaluations")
def create_evaluation(body: EvaluationIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    ev, created = ev_service.create_from_kiosk(db, kiosk, body.model_dump())
    return {"id": ev.id, "номер": ev.number, "день": ev.day, "создана": created,
            "статус": ev.status, "ссылка_отчёта": ev_service.report_url(ev),
            "ссылка_чека": ev_service.check_url(ev),
            "уже_приносили": bool(ev.device and ev.device.evaluations_count > 1)}


@router.patch("/evaluations/{ev_id}")
def update_evaluation(ev_id: int, body: UpdateIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    ev = db.get(Evaluation, ev_id)
    if not ev or ev.kiosk_id != kiosk.id:
        raise HTTPException(404, "оценка не найдена")
    ev_service.update_from_kiosk(db, kiosk, ev, body.report, body.snapshot_patch)
    return {"id": ev.id, "статус": ev.status, "apple": ev.apple_summary}


@router.post("/evaluations/{ev_id}/decision")
def client_decision(ev_id: int, body: DecisionIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    ev = db.get(Evaluation, ev_id)
    if not ev or ev.kiosk_id != kiosk.id:
        raise HTTPException(404, "оценка не найдена")
    if body.decision not in ("sell", "viewed"):
        raise HTTPException(400, "decision: sell | viewed")
    ev_service.client_decision(db, kiosk, ev, body.decision)
    return {"статус": ev.status}


@router.get("/evaluations/{ev_id}/media")
def list_media(ev_id: int, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    """Список фото/видео, загруженных сотрудником в кассе (данные клиента и медиа вносятся там)."""
    ev = _own(db, kiosk, ev_id)
    return ev_service.intake_state(ev)


@router.get("/evaluations/{ev_id}/intake")
def intake(ev_id: int, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    """Состояние заявки для киоска: номер (выдаёт сотрудник в кассе), ссылка на отчёт, медиа."""
    ev = _own(db, kiosk, ev_id)
    return ev_service.intake_state(ev)


@router.post("/evaluations/{ev_id}/import")
def import_to_ocenka(ev_id: int, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    """Отправить готовую сделку в Pintel Оценку (создаётся номер, уходит админам «Новая оценка»)."""
    ev = _own(db, kiosk, ev_id)
    try:
        res = ocenka_import.import_evaluation(db, ev)
    except ocenka_import.ImportError_ as e:
        raise HTTPException(400, str(e))
    except Exception as e:                                       # noqa: BLE001
        raise HTTPException(502, f"импорт в Оценку не удался: {e}")
    audit.log(db, None, "evaluation.ocenka_import",
              f"Оценка {ev_service.label(ev)} → сделка Оценки №{res.get('device_id')}",
              entity="evaluation", entity_id=ev.id, kiosk=kiosk, details=res)
    return {"id": ev.id, "номер_сделки": res.get("device_id"), **res}


# ---------- тест на телефоне клиента ----------

class PhoneTestIn(BaseModel):
    token: str
    eval_id: int | None = None


@router.post("/phone")
def open_phone_test(body: PhoneTestIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    """Открыть сессию теста: касса придумывает токен, сервер заводит под него строку.

    Строку создаёт только касса — поэтому на выдуманный токен с улицы результат не положить:
    такого токена в базе просто нет. В ответ — адрес страницы для QR на домене.
    """
    токен = (body.token or "").strip()[:32]
    if not токен.isalnum():
        raise HTTPException(400, "токен: только буквы и цифры")
    pt = db.scalar(select(PhoneTest).where(PhoneTest.token == токен))
    if pt is None:
        pt = PhoneTest(token=токен, kiosk_id=kiosk.id, eval_id=body.eval_id)
        db.add(pt)
    else:
        pt.kiosk_id, pt.eval_id = kiosk.id, body.eval_id or pt.eval_id
    db.commit()
    return {"токен": токен, "ссылка": f"{settings.public_url}/t/{токен}"}


@router.get("/phone/{token}")
def phone_test_result(token: str, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    """Результат теста: касса спрашивает его, пока клиент проходит тест на своём телефоне."""
    pt = db.scalar(select(PhoneTest).where(PhoneTest.token == token))
    if not pt:
        raise HTTPException(404, "проверка не найдена")
    return {"готов": pt.answered_at is not None, "результат": pt.result or {},
            "когда": pt.answered_at.isoformat() if pt.answered_at else None}


@router.post("/heartbeat")
def heartbeat(body: HeartbeatIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    kiosk.version = (body.version or kiosk.version or "")[:32]
    kiosk.status = body.status or kiosk.status
    kiosk.last_seen_at = now()
    db.commit()
    return {"ok": True, "время_сервера": now().isoformat()}
