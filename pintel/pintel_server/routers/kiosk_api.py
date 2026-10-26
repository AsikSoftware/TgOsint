# -*- coding: utf-8 -*-
"""API киоска. Авторизация — заголовок X-Kiosk-Token (токен выдаёт администратор в Настройках)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .. import audit
from ..auth import current_kiosk
from ..config import settings
from ..db import get_db, now
from ..models import Evaluation, Kiosk
from ..services import evaluations as ev_service
from ..services import price as price_service
from ..services import sickw_service

router = APIRouter(prefix="/api/kiosk", tags=["kiosk"])


class SickwIn(BaseModel):
    imei: str
    fresh: bool = False


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
        r = sickw_service.lookup(db, body.imei.strip(), use_cache=not body.fresh)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(502, str(e))
    r.pop("сырые_ответы", None)
    return r


@router.post("/evaluations")
def create_evaluation(body: EvaluationIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    ev, created = ev_service.create_from_kiosk(db, kiosk, body.model_dump())
    return {"id": ev.id, "номер": ev.number, "день": ev.day, "создана": created,
            "статус": ev.status, "ссылка_отчёта": f"{settings.public_url}/r/{ev.public_token}",
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


@router.post("/heartbeat")
def heartbeat(body: HeartbeatIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    kiosk.version = (body.version or kiosk.version or "")[:32]
    kiosk.status = body.status or kiosk.status
    kiosk.last_seen_at = now()
    db.commit()
    return {"ok": True, "время_сервера": now().isoformat()}
