# -*- coding: utf-8 -*-
"""Прайс: сервер сам забирает Google Таблицу, киоски получают готовую сетку."""
import os

from sqlalchemy import select, update

from pintel_core.external import gsheet

from .. import audit
from ..config import settings
from ..models import PriceGrid


def current(db) -> PriceGrid | None:
    return db.scalar(select(PriceGrid).where(PriceGrid.is_current == True).order_by(PriceGrid.id.desc()))  # noqa: E712


def refresh(db, actor=None) -> PriceGrid:
    """Забрать таблицу и сделать её текущей. Ошибки Google — человеческим текстом (gsheet)."""
    if settings.gservice_json and os.path.isfile(settings.gservice_json):
        gsheet.set_service_account(settings.gservice_json)
    grid = gsheet.fetch_grid(settings.price_sheet_url)
    db.execute(update(PriceGrid).where(PriceGrid.is_current == True).values(is_current=False))  # noqa: E712
    row = PriceGrid(source=grid.get("источник"), models_count=grid.get("моделей") or 0,
                    positions_count=grid.get("позиций") or 0, grid=grid, is_current=True,
                    fetched_by=(actor.name if actor else "сервер"))
    db.add(row)
    audit.log(db, actor, "price.refresh",
              f"Прайс обновлён из Google Таблицы: {row.models_count} моделей, {row.positions_count} позиций",
              entity="price_grid", details={"источник": row.source, "не_распознано": grid.get("не_распознано")})
    db.commit()
    return row
