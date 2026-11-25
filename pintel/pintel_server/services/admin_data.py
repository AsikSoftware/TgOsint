# -*- coding: utf-8 -*-
"""Данные для административной программы: обзор, точки, компьютеры, тревоги.

Зачем отдельно от страниц. Веб-касса отдаёт HTML — она сделана для сотрудника за стойкой.
Административная программа живёт на маке у владельца и показывает другое: не сделку, а
сеть целиком. Поэтому здесь не страницы, а чистые данные, и живут они в сервисе, а не в
обработчике: так их проверяют тесты, не поднимая сеть.

Правило у всех чисел одно: **пусто там, где данных нет**. Ноль вместо «не знаем» на экране
владельца — это ложь, по которой принимают решения.

Что считается «сегодня»: местный день точки (Алматы), как и в остальной кассе —
`evaluations.local_day`. Сервер живёт по UTC, и без этого вечерние сделки попадали бы в
завтрашний день.
"""
from datetime import timedelta

from sqlalchemy import func, select

from ..db import now
from ..models import (Evaluation, Kiosk, Point, ReferenceBundle, ST_BOUGHT, ST_DECLINED, User)
from .evaluations import local_day

# Насколько касса на точке может молчать, прежде чем это станет бедой. Два часа: точка
# работает с 10 до 21, и два часа без единой проверки — это либо закрылись, либо интернет.
МОЛЧИТ_ЧАСОВ = 2
# Выкуп дороже автооценки больше чем на столько — повод посмотреть сделку поимённо.
ПЕРЕПЛАТА = 30_000


def _точка_имя(p):
    return p.name if p else "без точки"


def обзор(db) -> dict:
    """Главные числа дня и точки сегодня. Для первого экрана программы."""
    день = local_day()
    строки = db.execute(select(Evaluation.point_id, Evaluation.status, Evaluation.price_offer,
                               Evaluation.final_price, Evaluation.assigned_user_id)
                        .where(Evaluation.day == день)).all()
    точки = {p.id: p for p in db.scalars(select(Point)).all()}
    по_точкам = {}
    проверок = выкуплено = выдано = человеком = 0
    for point_id, статус, автоцена, цена, _кто in строки:
        проверок += 1
        куда = по_точкам.setdefault(point_id, {"точка": _точка_имя(точки.get(point_id)),
                                               "проверок": 0, "выкуп": 0, "выдано": 0})
        куда["проверок"] += 1
        if автоцена is None:
            человеком += 1
        if статус == ST_BOUGHT:
            выкуплено += 1
            куда["выкуп"] += 1
            if цена:
                выдано += int(цена)
                куда["выдано"] += int(цена)
    return {
        "день": день,
        "проверок": проверок,
        "выкуплено": выкуплено,
        "выдано": выдано or None,
        "средний_чек": round(выдано / выкуплено) if выкуплено and выдано else None,
        "оценил_человек": человеком,
        "точки": sorted(по_точкам.values(), key=lambda т: -т["проверок"]),
    }


def точки(db) -> list:
    """Точки с их кассами: кто на смене, что с кассой, сколько сделок сегодня."""
    день = local_day()
    сделок = dict(db.execute(select(Evaluation.point_id, func.count())
                             .where(Evaluation.day == день)
                             .group_by(Evaluation.point_id)).all())
    последняя = dict(db.execute(select(Evaluation.point_id, func.max(Evaluation.created_at))
                                .group_by(Evaluation.point_id)).all())
    кассы = {}
    for k in db.scalars(select(Kiosk)).all():
        кассы.setdefault(k.point_id, []).append(k)
    готово = []
    for p in db.scalars(select(Point).order_by(Point.name)).all():
        свои = кассы.get(p.id, [])
        видели = max((k.last_seen_at for k in свои if k.last_seen_at), default=None)
        готово.append({
            "id": p.id,
            "точка": p.name,
            "город": p.city or "",
            "работает": bool(p.is_active),
            "на_смене": p.staff_name or "",
            "касс": len(свои),
            "сборка": (свои[0].version if свои else None),
            "последняя_связь": видели,
            "молчит_часов": _часов(видели),
            "сделок_сегодня": int(сделок.get(p.id) or 0),
            "последняя_сделка": последняя.get(p.id),
        })
    return готово


def компьютеры(db) -> list:
    """Каждая машина, на которой стоит наша программа.

    Токен принадлежит точке, а машин на точке бывает несколько — поэтому это отдельный
    список, а не колонка в точках."""
    точки_по_id = {p.id: p for p in db.scalars(select(Point)).all()}
    готово = []
    for k in db.scalars(select(Kiosk).order_by(Kiosk.name)).all():
        состояние = k.status if isinstance(k.status, dict) else {}
        готово.append({
            "id": k.id,
            "машина": k.name,
            "имя_в_системе": k.machine or "",
            "точка": _точка_имя(точки_по_id.get(k.point_id)) if k.point_id else "",
            "точка_id": k.point_id,
            "сборка": k.version or "",
            "работает": bool(k.is_active),
            "последняя_связь": k.last_seen_at,
            "молчит_часов": _часов(k.last_seen_at),
            "состояние": состояние,
        })
    return готово


def _часов(когда):
    """Сколько часов назад это было. → None, если не было вовсе."""
    if not когда:
        return None
    return round((now() - когда).total_seconds() / 3600, 1)


def тревоги(db, свежая_сборка: str = "") -> list:
    """Что требует внимания прямо сейчас. → [{вид, важность, что, почему, когда}]

    Важность: «беда» — работа стоит, «внимание» — деньги или качество, «к сведению» — рутина.
    Порядок не алфавитный и не по времени: сначала то, из-за чего точка не работает.
    """
    готово = []
    день = local_day()

    # 1. Точка молчит. Считаем только те, где сегодня уже были сделки: закрытая точка не беда.
    for т in точки(db):
        if not т["работает"]:
            continue
        часов = т["молчит_часов"]
        if т["сделок_сегодня"] and часов is not None and часов >= МОЛЧИТ_ЧАСОВ:
            готово.append({"вид": "точка_молчит", "важность": "беда",
                           "что": f"{т['точка']} не выходит на связь",
                           "почему": f"последний раз {часов:.0f} ч назад, сегодня было "
                                     f"{т['сделок_сегодня']} проверок",
                           "когда": т["последняя_связь"]})

    # 2. Касса на старой сборке. Не беда, но исправленная ошибка до точки не доехала.
    if свежая_сборка:
        for м in компьютеры(db):
            if м["работает"] and м["сборка"] and м["сборка"] != свежая_сборка:
                готово.append({"вид": "старая_сборка", "важность": "внимание",
                               "что": f"{м['машина']} на сборке {м['сборка']}",
                               "почему": f"вышла {свежая_сборка}; обновление ставится само, "
                                         "но машина должна быть на связи",
                               "когда": м["последняя_связь"]})

    # 3. Выкуп заметно дороже автооценки — смотрим поимённо.
    за_неделю = now() - timedelta(days=7)
    for ev in db.scalars(select(Evaluation).where(Evaluation.created_at >= за_неделю,
                                                  Evaluation.status == ST_BOUGHT)).all():
        if ev.price_offer and ev.final_price and ev.final_price - ev.price_offer >= ПЕРЕПЛАТА:
            готово.append({"вид": "переплата", "важность": "внимание",
                           "что": f"выкуп дороже автооценки на {ev.final_price - ev.price_offer:,} ₸"
                                  .replace(",", " "),
                           "почему": f"сделка №{ev.number or ev.id}, {ev.model_name or 'аппарат'}",
                           "когда": ev.decided_at or ev.created_at})

    # 4. Сверка деталей без фото: подтвердить ответы сотрудника нечем.
    без_фото = 0
    for ev in db.scalars(select(Evaluation).where(Evaluation.day == день)).all():
        if ev.staff_parts and not (ev.report or {}).get("медиа_готово"):
            без_фото += 1
    if без_фото:
        готово.append({"вид": "нет_фото", "важность": "внимание",
                       "что": f"{без_фото} телефонов без фото раздела Apple",
                       "почему": "сотрудник ответил по деталям, а снимок экрана не пришёл — "
                                 "проверить ответы нечем",
                       "когда": None})

    порядок = {"беда": 0, "внимание": 1, "к сведению": 2}
    return sorted(готово, key=lambda т: (порядок.get(т["важность"], 9), т["что"]))


def люди(db) -> list:
    """Сотрудники: где работают, сколько сделали, есть ли доступ."""
    за_месяц = now() - timedelta(days=30)
    сделок = dict(db.execute(select(Evaluation.assigned_user_id, func.count())
                             .where(Evaluation.created_at >= за_месяц)
                             .group_by(Evaluation.assigned_user_id)).all())
    выкупов = dict(db.execute(select(Evaluation.assigned_user_id, func.count())
                              .where(Evaluation.created_at >= за_месяц,
                                     Evaluation.status == ST_BOUGHT)
                              .group_by(Evaluation.assigned_user_id)).all())
    выдано = dict(db.execute(select(Evaluation.assigned_user_id, func.sum(Evaluation.final_price))
                             .where(Evaluation.created_at >= за_месяц,
                                    Evaluation.status == ST_BOUGHT)
                             .group_by(Evaluation.assigned_user_id)).all())
    готово = []
    for u in db.scalars(select(User).order_by(User.name)).all():
        готово.append({
            "id": u.id,
            "имя": u.name,
            "логин": u.login,
            "роль": u.role,
            "роль_словами": u.role_label,
            "точка": _точка_имя(u.point) if u.point_id else "",
            "доступ": bool(u.is_active),
            "последний_вход": u.last_login_at,
            "проверок_за_месяц": int(сделок.get(u.id) or 0),
            "выкупов_за_месяц": int(выкупов.get(u.id) or 0),
            "выдано_за_месяц": int(выдано.get(u.id) or 0) or None,
        })
    return готово


def эталоны_коротко(db) -> dict:
    """Сколько эталонов и сколько из них с отметками сотрудника (правдой с экрана)."""
    всего = db.scalar(select(func.count()).select_from(ReferenceBundle)) or 0
    с_правдой = db.scalar(select(func.count()).select_from(ReferenceBundle)
                          .where(ReferenceBundle.verdict.is_not(None))) or 0
    return {"всего": всего, "с_отметками": с_правдой, "без_отметок": всего - с_правдой}


def воронка(db, дней: int = 30) -> dict:
    """Путь клиента: сколько проверили, сколько выкупили, сколько отказов и почему.

    Заявки с сайта считаются отдельно (их заводит бот Оценки), поэтому здесь то, что видно
    на нашей стороне: пришёл → прочитали → выкупили."""
    порог = now() - timedelta(days=дней)
    строки = db.execute(select(Evaluation.status, Evaluation.decision_note)
                        .where(Evaluation.created_at >= порог)).all()
    всего = len(строки)
    выкуплено = sum(1 for с, _ in строки if с == ST_BOUGHT)
    отказов = sum(1 for с, _ in строки if с == ST_DECLINED)
    причины = {}
    for статус, заметка in строки:
        if статус != ST_DECLINED:
            continue
        ключ = (заметка or "").strip() or "причина не записана"
        причины[ключ] = причины.get(ключ, 0) + 1
    return {
        "дней": дней,
        "прочитали": всего,
        "выкупили": выкуплено,
        "отказов": отказов,
        "доля_выкупа": round(выкуплено * 100 / всего) if всего else None,
        "причины": sorted(({"причина": к, "случаев": н} for к, н in причины.items()),
                          key=lambda п: -п["случаев"]),
    }
