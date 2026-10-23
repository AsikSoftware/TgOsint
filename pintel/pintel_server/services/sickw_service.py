# -*- coding: utf-8 -*-
"""Sickw через сервер: ключ только здесь, кэш по IMEI общий на всю сеть точек."""
from sqlalchemy import select

from pintel_core.external import sickw

from ..config import settings
from ..db import now
from ..models import SickwCache


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
        if row is None:
            row = SickwCache(imei=imei, service=s)
            db.add(row)
        row.raw = r.get("сырой_ответ") if isinstance(r.get("сырой_ответ"), str) else str(r.get("сырой_ответ"))
        row.normalized = {k: v for k, v in r.items() if k not in ("сырой_ответ",)}
        row.fetched_at = now()
        db.commit()
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
