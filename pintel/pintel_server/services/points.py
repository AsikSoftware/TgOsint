# -*- coding: utf-8 -*-
"""Точки: берутся из магазинов Оценки, с теми же id.

Точка у нас — это магазин Оценки, и её `id` равен `shops.id` там. Из-за этого сделка,
уходящая в Оценку, несёт готовый `shop_id`, и спрашивать точку у сотрудника в боте не
нужно вовсе: раньше её выбирали кнопкой каждый раз, а администратор ещё и мог ошибиться.

Список не набирают руками: `pintel-server sync-shops` читает `shops` из базы Оценки и
заводит у нас такие же строки. Токен каждой точки лежит рядом, текстом: точками управляют
прямо в базе, веб-кассой не пользуются.
"""
from __future__ import annotations

import secrets

from sqlalchemy import select, text

from ..models import Point

# Буквы и цифры без пар, которые легко спутать: токен иногда диктуют голосом.
АЛФАВИТ = "ACDEFGHJKLMNPQRTUVWXY345679"


def новый_токен(длина: int = 12) -> str:
    return "pk_" + "".join(secrets.choice(АЛФАВИТ) for _ in range(длина))


def магазины_оценки() -> list:
    """→ [{id, litera, shop_name}] из базы Оценки. Связь не настроена — пустой список."""
    from . import ocenka_import
    движок = ocenka_import._ocenka_engine()
    with движок.connect() as conn:
        строки = conn.execute(text("SELECT id, litera, shop_name FROM shops ORDER BY id")).all()
    return [{"id": r[0], "litera": r[1], "shop_name": r[2]} for r in строки]


ПРОПАЛА = "нет_в_оценке"        # пометка в points.settings: такого магазина у Оценки больше нет


def синхронизировать(db, выдавать_токены: bool = True) -> dict:
    """Завести у нас точки по магазинам Оценки. → что изменилось, по пунктам.

    Идём по id: у нас и у них это одна и та же точка.

    * **новый магазин** — заводим точку с тем же id и сразу выдаём токен;
    * **переименовали или сменили литеру** — обновляем; токен не трогаем, иначе программа
      на точке перестала бы работать из-за чужого переименования;
    * **магазин пропал** — точку НЕ удаляем и не отключаем молча: на ней висят оценки, а
      сотрудник у стойки не должен узнать об этом по отказу. Помечаем и громко называем в
      ответе, решает человек.

    Возвращаем списки, а не только числа: «обновлено 3» ничего не говорит, а «16/38 Pintel
    стала Pintel Центральный» говорит всё.
    """
    было = {p.id: p for p in db.scalars(select(Point))}
    создано, переименовано, токенов = [], [], 0
    живые = set()
    for м in магазины_оценки():
        живые.add(м["id"])
        p = было.get(м["id"])
        имя = м["shop_name"] or f"Магазин {м['id']}"
        if p is None:
            p = Point(id=м["id"], name=имя, litera=м["litera"])
            db.add(p)
            создано.append(f"{м['id']} {имя}")
        else:
            if (p.name, p.litera) != (имя, м["litera"]):
                переименовано.append(f"{p.id} «{p.name}» → «{имя}»")
                p.name, p.litera = имя, м["litera"]
            настройки = dict(p.settings or {})
            if настройки.pop(ПРОПАЛА, None):        # магазин вернулся — снимаем пометку
                p.settings = настройки or None
        if выдавать_токены and not p.token:
            p.token = новый_токен()
            токенов += 1
    пропали = []
    for p in было.values():
        if p.id in живые:
            continue
        пропали.append(f"{p.id} {p.name}")
        p.settings = {**(p.settings or {}), ПРОПАЛА: True}
    db.flush()
    _поправить_счётчик(db)
    db.commit()
    return {"создано": создано, "переименовано": переименовано, "пропали": пропали,
            "токенов_выдано": токенов}


def _поправить_счётчик(db) -> None:
    """Строки заводятся с явными id, и автосчётчик остаётся позади — следующая точка,
    добавленная руками, упала бы на «ключ уже существует». В SQLite счётчика нет."""
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    db.execute(text("SELECT setval(pg_get_serial_sequence('points', 'id'), "
                    "GREATEST((SELECT COALESCE(MAX(id), 1) FROM points), 1))"))


def список(db) -> list:
    return list(db.scalars(select(Point).order_by(Point.id)))


def пропала(p: Point) -> bool:
    """Магазина с таким id в Оценке больше нет. Точка работает, но это надо видеть."""
    return bool((p.settings or {}).get(ПРОПАЛА))
