# -*- coding: utf-8 -*-
"""Sickw через сервер: ключ только здесь, кэш по IMEI общий на всю сеть точек."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from pintel_core.external import sickw

from ..config import settings
from ..db import now
from ..models import SickwCache


def _в_кэш(db, imei, s, r, row=None) -> None:
    """Положить ответ Sickw в общий кэш. Не получилось — не беда: ответ уже есть.

    Две кассы спрашивают один IMEI одновременно — обе не находят строку в кэше и обе её
    создают. Вторая получала «нарушена уникальность», запрос падал с ошибкой 500, а касса
    писала «база недоступна»: чёрный список оставался непроверенным, автоцены не было
    (24.11.2026, 10:16 — живой случай на точке). Кэш — это ускорение, а не условие ответа,
    и ронять из-за него проверку телефона нельзя.
    """
    поля = {
        "raw": r.get("сырой_ответ") if isinstance(r.get("сырой_ответ"), str) else str(r.get("сырой_ответ")),
        "normalized": {k: v for k, v in r.items() if k not in ("сырой_ответ",)},
        "fetched_at": now(),
    }
    try:
        if row is None:
            row = SickwCache(imei=imei, service=s)
            db.add(row)
        for к, v in поля.items():
            setattr(row, к, v)
        db.commit()
        return
    except IntegrityError:
        db.rollback()
    except SQLAlchemyError:
        db.rollback()
        return
    # Строку завела соседняя касса — обновляем её же.
    try:
        чужая = db.scalar(select(SickwCache).where(SickwCache.imei == imei, SickwCache.service == s))
        if чужая is not None:
            for к, v in поля.items():
                setattr(чужая, к, v)
            db.commit()
    except SQLAlchemyError:
        db.rollback()


def lookup(db, imei: str, services=None, use_cache=True) -> dict:
    if not settings.sickw_key:
        raise RuntimeError("ключ Sickw не задан на сервере (PINTEL_SICKW_KEY)")
    if not sickw.luhn_ok(imei):
        raise ValueError(f"IMEI {imei} не проходит контрольную цифру")
    results, errors = [], {}
    for s in (services or settings.sickw_services):
        row = db.scalar(select(SickwCache).where(SickwCache.imei == imei, SickwCache.service == s))
        if use_cache and row and row.raw:
            r = sickw.normalize(sickw.parse_result(row.raw))
            r.update({"сырой_ответ": row.raw, "служба": s, "получено": row.fetched_at.strftime("%Y-%m-%d %H:%M:%S"),
                      "из_кэша": True})
            results.append(r)
            continue
        try:
            r = sickw.lookup(imei, settings.sickw_key, cache_dir=None, service=s, use_cache=False)
        except Exception as e:                                   # noqa: BLE001
            errors[str(s)] = str(e)
            continue
        _в_кэш(db, imei, s, r, row)
        results.append(r)
    if not results:
        raise RuntimeError("; ".join(errors.values()) or "Sickw: нет служб")
    out = sickw.merge(results)
    out["ошибки_служб"] = errors
    return out


def balance():
    if not settings.sickw_key:
        raise RuntimeError("ключ Sickw не задан на сервере")
    return sickw.balance(settings.sickw_key)
