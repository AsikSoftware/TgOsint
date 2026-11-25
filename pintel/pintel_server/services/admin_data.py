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

from sqlalchemy import func, or_, select

from ..db import now
from ..models import (AuditLog, Evaluation, Kiosk, Point, ReferenceBundle, ROLE_ADMIN,
                      ROLE_CASHIER, ROLE_SENIOR, ST_BOUGHT, ST_DECLINED, STATUSES, Setting, User)
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


# ---------------------------------------------------------------- деньги и товар


def деньги(db, дней: int = 30) -> dict:
    """Выкупы за период: сколько выдано, по каким моделям и каким точкам.

    Продаж мы на сервере НЕ видим — они живут в МойСкладе, и пока он сюда не заведён, слова
    «маржа» здесь не будет: придумывать её по памяти нельзя.
    """
    порог = now() - timedelta(days=дней)
    строки = db.execute(select(Evaluation.model_name, Evaluation.capacity_gb,
                               Evaluation.final_price, Evaluation.price_offer,
                               Evaluation.point_id, Evaluation.created_at)
                        .where(Evaluation.created_at >= порог,
                               Evaluation.status == ST_BOUGHT)).all()
    точки = {p.id: p.name for p in db.scalars(select(Point)).all()}
    по_моделям, по_точкам = {}, {}
    всего = выдано = 0
    for модель, память, цена, автоцена, point_id, _когда in строки:
        цена = int(цена or 0)
        всего += 1
        выдано += цена
        м = по_моделям.setdefault(модель or "без модели", {"модель": модель or "без модели",
                                                           "штук": 0, "сумма": 0, "переплат": 0})
        м["штук"] += 1
        м["сумма"] += цена
        if автоцена and цена - int(автоцена) >= ПЕРЕПЛАТА:
            м["переплат"] += 1
        т = по_точкам.setdefault(point_id, {"точка": точки.get(point_id) or "без точки",
                                            "штук": 0, "сумма": 0})
        т["штук"] += 1
        т["сумма"] += цена
    for м in по_моделям.values():
        м["средний_выкуп"] = round(м["сумма"] / м["штук"]) if м["штук"] else None
    return {
        "дней": дней,
        "выкуплено": всего,
        "выдано": выдано or None,
        "средний_чек": round(выдано / всего) if всего else None,
        "модели": sorted(по_моделям.values(), key=lambda м: -м["штук"]),
        "точки": sorted(по_точкам.values(), key=lambda т: -т["сумма"]),
        "оговорка": "продажи и маржа появятся, когда сюда заведут МойСклад: сейчас сервер "
                    "видит только выкупы",
    }


def товар_на_руках(db, дней: int = 120) -> dict:
    """Что выкуплено и сколько дней назад.

    Честно: признака «продан» у сервера нет — продажа происходит в МойСкладе. Поэтому это
    список выкупленного с возрастом, а не остаток склада. Старые строки почти наверняка уже
    проданы, и пока МойСклада нет, об этом сказано словами, а не спрятано."""
    порог = now() - timedelta(days=дней)
    строки = db.scalars(select(Evaluation).where(Evaluation.created_at >= порог,
                                                 Evaluation.status == ST_BOUGHT)
                        .order_by(Evaluation.created_at.desc())).all()
    точки = {p.id: p.name for p in db.scalars(select(Point)).all()}
    сейчас = now()
    готово = []
    for ev in строки:
        дней_лежит = (сейчас - ev.created_at).days
        готово.append({
            "аппарат": " · ".join(x for x in (ev.model_name, f"{ev.capacity_gb} ГБ"
                                              if ev.capacity_gb else "") if x),
            "батарея": ev.battery_health,
            "точка": точки.get(ev.point_id) or "",
            "выкуплен": ev.created_at,
            "дней": дней_лежит,
            "выкуп": ev.final_price,
            "номер": ev.number or ev.id,
        })
    старше_месяца = [т for т in готово if т["дней"] >= 30]
    return {
        "штук": len(готово),
        "сумма": sum(int(т["выкуп"] or 0) for т in готово) or None,
        "старше_месяца": len(старше_месяца),
        "сумма_старше": sum(int(т["выкуп"] or 0) for т in старше_месяца) or None,
        "список": готово[:300],
        "оговорка": "признака «продан» у сервера нет — продажи идут в МойСкладе; это список "
                    "выкупленного с возрастом",
    }


# ---------------------------------------------------------------- работа точек


def проверки_без_сделки(db, дней: int = 30) -> dict:
    """Телефон прочитали, а выкупа не было: сколько времени ушло и кому можно перезвонить."""
    порог = now() - timedelta(days=дней)
    строки = db.scalars(select(Evaluation).where(Evaluation.created_at >= порог,
                                                 Evaluation.status != ST_BOUGHT)
                        .order_by(Evaluation.created_at.desc())).all()
    точки = {p.id: p.name for p in db.scalars(select(Point)).all()}
    причины = {}
    с_телефоном = 0
    список = []
    for ev in строки:
        причина = (ev.decision_note or "").strip() or ("ещё в работе" if ev.status != ST_DECLINED
                                                       else "причина не записана")
        причины[причина] = причины.get(причина, 0) + 1
        if ev.client_phone:
            с_телефоном += 1
        список.append({
            "аппарат": " · ".join(x for x in (ev.model_name, f"{ev.capacity_gb} ГБ"
                                              if ev.capacity_gb else "") if x),
            "точка": точки.get(ev.point_id) or "",
            "когда": ev.created_at,
            "автоцена": ev.price_offer,
            "чем_кончилось": причина,
            "можно_позвонить": bool(ev.client_phone),
        })
    return {
        "дней": дней,
        "проверок": len(строки),
        "с_телефоном": с_телефоном,
        "причины": sorted(({"причина": к, "случаев": н} for к, н in причины.items()),
                          key=lambda п: -п["случаев"]),
        "список": список[:300],
    }


def сертификаты(db, дней: int = 30) -> dict:
    """Сертификаты, выданные клиентам: номер, аппарат, точка, ссылка.

    Сколько раз ссылку открывали, сервер пока не считает — и вместо выдуманного числа здесь
    так и сказано."""
    порог = now() - timedelta(days=дней)
    строки = db.scalars(select(Evaluation).where(Evaluation.created_at >= порог)
                        .order_by(Evaluation.created_at.desc())).all()
    точки = {p.id: p.name for p in db.scalars(select(Point)).all()}
    список = []
    for ev in строки:
        чек = (ev.report or {}).get("чек")
        if not чек:
            continue
        список.append({
            "номер": ev.number or ev.id,
            "аппарат": ev.model_name or "",
            "точка": точки.get(ev.point_id) or "",
            "когда": ev.created_at,
            "ссылка": f"/r/{ev.public_token}",
        })
    return {"дней": дней, "выдано": len(список), "список": список[:300],
            "оговорка": "сколько раз сертификат открывали, сервер пока не считает"}


# ---------------------------------------------------------------- данные


def эталоны(db, сколько: int = 300) -> dict:
    """Список эталонов: что собрано с точек и на чём проверяется каждая новая сборка."""
    точки = {p.id: p.name for p in db.scalars(select(Point)).all()}
    строки = db.scalars(select(ReferenceBundle)
                        .order_by(ReferenceBundle.created_at.desc()).limit(сколько)).all()
    итог = эталоны_коротко(db)
    итог["список"] = [{
        "аппарат": б.model_name or "",
        "ios": б.ios or "",
        "точка": точки.get(б.point_id) or "",
        "когда": б.created_at,
        "вердикт": б.verdict or "",
        "размер_мб": round((б.size or 0) / 1048576, 1) or None,
    } for б in строки]
    return итог


def телефон(db, запрос: str) -> dict:
    """Всё, что мы знаем про один аппарат: по IMEI или серийному номеру.

    Сводить это руками из трёх мест — то, на что уходит время при споре с клиентом."""
    запрос = (запрос or "").strip()
    if len(запрос) < 5:
        return {"найдено": False, "почему": "нужно хотя бы пять знаков IMEI или серийника"}
    цифры = "".join(c for c in запрос if c.isdigit())
    условия = [Evaluation.serial.ilike(f"%{запрос}%")]
    if цифры:
        условия.append(Evaluation.imei.ilike(f"%{цифры}%"))
    строки = db.scalars(select(Evaluation).where(or_(*условия))
                        .order_by(Evaluation.created_at.desc()).limit(50)).all()
    if not строки:
        return {"найдено": False, "почему": "такого аппарата у нас не было"}
    точки = {p.id: p.name for p in db.scalars(select(Point)).all()}
    первый = строки[0]
    return {
        "найдено": True,
        "аппарат": " · ".join(x for x in (первый.model_name, f"{первый.capacity_gb} ГБ"
                                          if первый.capacity_gb else "") if x),
        "ios": первый.ios or "",
        "батарея": первый.battery_health,
        "циклы": первый.battery_cycles,
        "детали": первый.apple_summary or "",
        "блокировки": первый.locks_summary or "",
        "проверок": len(строки),
        "история": [{
            "номер": ev.number or ev.id,
            "когда": ev.created_at,
            "точка": точки.get(ev.point_id) or "",
            "автоцена": ev.price_offer,
            "выкуп": ev.final_price,
            "чем_кончилось": STATUSES.get(ev.status, ev.status),
            "заметка": (ev.decision_note or "").strip(),
        } for ev in строки],
    }


def журнал(db, сколько: int = 200) -> list:
    """Кто что делал: сотрудники, кассы и сам сервер."""
    точки = {p.id: p.name for p in db.scalars(select(Point)).all()}
    строки = db.scalars(select(AuditLog).order_by(AuditLog.at.desc()).limit(сколько)).all()
    return [{
        "когда": з.at,
        "кто": з.actor_name or з.actor_type,
        "что": з.text or з.action,
        "где": точки.get(з.point_id) or "",
    } for з in строки]


def роли(db) -> dict:
    """Какие роли есть и что каждая видит. Матрица описана здесь же: это правило, а не данные."""
    есть = dict(db.execute(select(User.role, func.count()).group_by(User.role)).all())
    права = [
        {"роль": "Администратор", "ключ": ROLE_ADMIN, "сделки": "по всей сети",
         "деньги": "да", "люди": "да", "машины": "да", "админка": "да"},
        {"роль": "Старший", "ключ": ROLE_SENIOR, "сделки": "своей точки",
         "деньги": "нет", "люди": "свою смену", "машины": "свою кассу", "админка": "нет"},
        {"роль": "Кассир", "ключ": ROLE_CASHIER, "сделки": "свои",
         "деньги": "нет", "люди": "нет", "машины": "нет", "админка": "нет"},
    ]
    for п in права:
        п["людей"] = int(есть.get(п["ключ"]) or 0)
    return {"роли": права,
            "оговорка": "владелец и бухгалтер появятся отдельными ролями, когда понадобится "
                        "развести деньги и работу точек"}


# ---------------------------------------------------------------- чёрный список


КЛЮЧ_ЧЁРНОГО = "чёрный_список"


def чёрный_список(db) -> list:
    """Наши собственные отметки: этот аппарат не берём и вот почему.

    Лежит в настройках, а не отдельной таблицей: записей десятки, а не тысячи, и лишняя
    таблица на боевом сервере — это миграция ради списка из двадцати строк."""
    строка = db.get(Setting, КЛЮЧ_ЧЁРНОГО)
    значения = (строка.value or {}).get("записи") if строка else None
    return list(значения or [])


def чёрный_добавить(db, imei: str, почему: str, кто: str) -> list:
    цифры = "".join(c for c in str(imei or "") if c.isdigit())
    if len(цифры) < 8:
        raise ValueError("IMEI слишком короткий")
    записи = [з for з in чёрный_список(db) if з.get("imei") != цифры]
    записи.insert(0, {"imei": цифры, "почему": (почему or "").strip() or "без причины",
                      "кто": кто, "когда": now().isoformat(timespec="seconds")})
    _чёрный_сохранить(db, записи)
    return записи


def чёрный_убрать(db, imei: str) -> list:
    цифры = "".join(c for c in str(imei or "") if c.isdigit())
    записи = [з for з in чёрный_список(db) if з.get("imei") != цифры]
    _чёрный_сохранить(db, записи)
    return записи


def _чёрный_сохранить(db, записи: list):
    строка = db.get(Setting, КЛЮЧ_ЧЁРНОГО)
    if строка is None:
        строка = Setting(key=КЛЮЧ_ЧЁРНОГО, value={})
        db.add(строка)
    строка.value = {"записи": записи}
    db.commit()


# ---------------------------------------------------------------- действия над точками


# Команда машине кладётся отдельной настройкой, а не в `Kiosk.status`: статус касса
# перезаписывает каждым пульсом, и команда исчезла бы, не дойдя.
КЛЮЧ_КОМАНДЫ = "команда_кассе_%s"


def команда_машине(db, kiosk_id: int, команда: str):
    """Положить команду для машины. Она заберёт её ближайшим пульсом — раз в минуту."""
    ключ = КЛЮЧ_КОМАНДЫ % int(kiosk_id)
    строка = db.get(Setting, ключ)
    if строка is None:
        строка = Setting(key=ключ, value={})
        db.add(строка)
    строка.value = {"команда": команда, "когда": now().isoformat(timespec="seconds")}
    db.commit()


def забрать_команду(db, kiosk_id: int) -> str:
    """→ команда для этой машины, один раз. Выполненная команда не должна повториться:
    «обновись», застрявшая в базе, перезапускала бы кассу каждую минуту."""
    строка = db.get(Setting, КЛЮЧ_КОМАНДЫ % int(kiosk_id))
    если = ((строка.value or {}).get("команда") if строка else "") or ""
    if строка is not None and если:
        строка.value = {}
        db.commit()
    return если


def машина_работает(db, kiosk_id: int, работает: bool) -> dict:
    """Закрыть или открыть машину. Закрытая не пускается на сервер вовсе: касса на ней
    скажет «этот компьютер отключён администратором» и сделку начать не даст."""
    k = db.get(Kiosk, int(kiosk_id))
    if k is None:
        raise ValueError("нет такой машины")
    k.is_active = bool(работает)
    db.commit()
    return {"машина": k.name, "работает": k.is_active}


def машину_забыть(db, kiosk_id: int) -> dict:
    """Убрать машину из списка. Если она снова выйдет на связь с токеном своей точки, она
    появится заново — токен принадлежит точке, и это правильно: иначе замена компьютера
    требовала бы выдачи нового токена всей точке."""
    k = db.get(Kiosk, int(kiosk_id))
    if k is None:
        raise ValueError("нет такой машины")
    имя = k.name
    db.delete(k)
    db.commit()
    return {"машина": имя, "забыта": True}


def точка_работает(db, point_id: int, работает: bool) -> dict:
    """Закрыть или открыть точку целиком: закрытая не пускает на сервер ни одну свою кассу."""
    p = db.get(Point, int(point_id))
    if p is None:
        raise ValueError("нет такой точки")
    p.is_active = bool(работает)
    db.commit()
    return {"точка": p.name, "работает": p.is_active}


def доступ_человеку(db, user_id: int, доступ: bool) -> dict:
    """Открыть или закрыть доступ сотруднику. Закрытый не войдёт ни в кассу, ни сюда."""
    u = db.get(User, int(user_id))
    if u is None:
        raise ValueError("нет такого сотрудника")
    u.is_active = bool(доступ)
    db.commit()
    return {"сотрудник": u.name, "доступ": u.is_active}
