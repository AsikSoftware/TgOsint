# -*- coding: utf-8 -*-
"""Что происходит на точках — одной страницей.

Данные уже есть: каждая оценка приходит с отчётом, вердиктом, тестом телефона и отметкой о
том, дошла ли она до Оценки. Раньше всё это лежало россыпью и никто не видел картины: сколько
аппаратов посмотрели, сколько оказались чистыми, сколько сделок доехало до бота, где точка
стоит без связи. Здесь это считается, ничего не придумывая сверх того, что записано.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from ..db import now
from ..models import Evaluation, Kiosk, KioskLog, PhoneTest, Point, ReferenceBundle

ПЕРИОДЫ = (("today", "сегодня", 1), ("week", "неделя", 7), ("month", "месяц", 30),
           ("all", "всё время", 0))

# Вердикты отчёта в том порядке, в каком их читает человек: от хорошего к плохому.
ВЕРДИКТЫ = ("ИДЕАЛ", "ХОРОШИЙ", "ПРОВЕРКА НЕПОЛНАЯ", "ПРОБЛЕМНЫЙ")


def _порог(дней: int):
    return None if not дней else now() - timedelta(days=дней)


def свод(db, дней: int = 7) -> dict:
    """Главные числа за период. Пусто там, где данных нет, а не ноль ради красоты."""
    порог = _порог(дней)
    усл = [Evaluation.created_at >= порог] if порог else []
    всего = db.scalar(select(func.count()).select_from(Evaluation).where(*усл)) or 0
    по_вердикту = dict(db.execute(
        select(Evaluation.verdict, func.count()).where(*усл).group_by(Evaluation.verdict)).all())
    дошло = db.scalar(select(func.count()).select_from(Evaluation).where(
        Evaluation.ocenka_device_id.is_not(None), *усл)) or 0
    с_чеком = 0
    с_тестом = тест_прошёл = тест_не_прошёл = 0
    батареи = []
    for (rep, здоровье) in db.execute(select(Evaluation.report, Evaluation.battery_health).where(*усл)).all():
        rep = rep or {}
        if rep.get("чек"):
            с_чеком += 1
        тест = rep.get("тест_телефона") or {}
        if тест:
            с_тестом += 1
            if any(v == "fail" for v in тест.values()):
                тест_не_прошёл += 1
            elif all(v == "ok" for v in тест.values() if isinstance(v, str)):
                тест_прошёл += 1
        if здоровье:
            батареи.append(int(здоровье))
    усл_т = [PhoneTest.created_at >= порог] if порог else []
    тестов_открыто = db.scalar(select(func.count()).select_from(PhoneTest).where(*усл_т)) or 0
    тестов_отвечено = db.scalar(select(func.count()).select_from(PhoneTest).where(
        PhoneTest.answered_at.is_not(None), *усл_т)) or 0
    эталонов = db.scalar(select(func.count()).select_from(ReferenceBundle).where(
        *([ReferenceBundle.created_at >= порог] if порог else []))) or 0
    строк_журнала = db.scalar(select(func.count()).select_from(KioskLog).where(
        *([KioskLog.at >= порог] if порог else []))) or 0
    return {
        "оценок": всего,
        "по_вердикту": [(в, по_вердикту.get(в, 0)) for в in ВЕРДИКТЫ]
                       + [(k, v) for k, v in по_вердикту.items() if k not in ВЕРДИКТЫ and k],
        "идеальных": по_вердикту.get("ИДЕАЛ", 0) + по_вердикту.get("ХОРОШИЙ", 0),
        "с_вопросами": по_вердикту.get("ПРОБЛЕМНЫЙ", 0) + по_вердикту.get("ПРОВЕРКА НЕПОЛНАЯ", 0),
        "дошло_до_бота": дошло,
        "с_чеком": с_чеком,
        "тест_был": с_тестом, "тест_прошёл": тест_прошёл, "тест_не_прошёл": тест_не_прошёл,
        "тестов_открыто": тестов_открыто, "тестов_отвечено": тестов_отвечено,
        "эталонов": эталонов, "строк_журнала": строк_журнала,
        "батарея_средняя": round(sum(батареи) / len(батареи)) if батареи else None,
    }


def по_точкам(db, дней: int = 7) -> list:
    """Та же картина в разрезе точек: где работают, а где тишина."""
    порог = _порог(дней)
    усл = [Evaluation.created_at >= порог] if порог else []
    counts = dict(db.execute(select(Evaluation.point_id, func.count()).where(*усл)
                             .group_by(Evaluation.point_id)).all())
    дошло = dict(db.execute(select(Evaluation.point_id, func.count())
                            .where(Evaluation.ocenka_device_id.is_not(None), *усл)
                            .group_by(Evaluation.point_id)).all())
    последняя = dict(db.execute(select(Evaluation.point_id, func.max(Evaluation.created_at))
                                .group_by(Evaluation.point_id)).all())
    машины = {}
    for k in db.scalars(select(Kiosk).order_by(Kiosk.name)):
        машины.setdefault(k.point_id, []).append(k)
    строки = []
    for p in db.scalars(select(Point).order_by(Point.name)):
        свои = машины.get(p.id, [])
        на_связи = [k for k in свои if k.last_seen_at and (now() - k.last_seen_at).total_seconds() < 900]
        строки.append({"точка": p, "оценок": counts.get(p.id, 0), "дошло": дошло.get(p.id, 0),
                       "последняя": последняя.get(p.id), "машин": len(свои), "на_связи": len(на_связи),
                       "токен": bool(p.token_hash)})
    без_точки = counts.get(None, 0)
    if без_точки:
        строки.append({"точка": None, "оценок": без_точки, "дошло": дошло.get(None, 0),
                       "последняя": последняя.get(None), "машин": len(машины.get(None, [])),
                       "на_связи": 0, "токен": False})
    return строки


def последние_логи(db, сколько: int = 200, point_id: int | None = None) -> list:
    q = select(KioskLog).order_by(KioskLog.id.desc()).limit(сколько)
    if point_id:
        q = q.where(KioskLog.point_id == point_id)
    return list(db.scalars(q))
