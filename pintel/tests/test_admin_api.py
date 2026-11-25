# -*- coding: utf-8 -*-
"""Выдача данных административной программе: обзор, точки, компьютеры, тревоги, люди.

Программа живёт на маке у владельца и показывает сеть целиком. Проверяем две вещи: что без
входа и не администратору ничего не отдаётся, и что числа считаются по тем же правилам, что
и всё остальное в кассе (местный день, пусто вместо нуля).

Два правила про базу, оба оплачены:

1. Модули сервера грузятся ЛЕНИВО, внутри `_сервер()`. Этот файл первый по алфавиту, и при
   обычном импорте он создавал соединение с базой раньше всех — а серверные проверки задают
   адрес базы при своём импорте, то есть уже поздно. Они уезжали в рабочую базу разработчика
   и падали пачкой (23 проверки, 25.11.2026).
2. Счётные проверки работают НА СВОЕЙ базе и зовут сервис напрямую, а проверка доступа
   подменяет базу приложению (`dependency_overrides`). Иначе учётные записи этих проверок
   попадают в общую базу тестов и ломают чужие.
"""
import os
import tempfile
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

_КЭШ = {}


def _сервер() -> dict:
    """Модули сервера и своя база. Лениво — см. правило 1 в шапке файла."""
    if not _КЭШ:
        os.environ.setdefault("PINTEL_DATABASE_URL",
                              f"sqlite:///{tempfile.mkdtemp()}/admin_server.db")
        from pintel_server import models
        from pintel_server.auth import hash_password
        from pintel_server.db import get_db, now
        from pintel_server.main import create_app
        from pintel_server.services import admin_data
        from pintel_server.services.evaluations import local_day
        движок = create_engine(f"sqlite:///{tempfile.mkdtemp()}/admin.db")
        models.Base.metadata.create_all(движок)
        _КЭШ.update(м=models, хэш=hash_password, get_db=get_db, сейчас=now, приложение=create_app,
                    данные=admin_data, день=local_day, Сессия=sessionmaker(bind=движок))
    return _КЭШ


def _м(имя):
    """Модель или константа сервера по имени."""
    return getattr(_сервер()["м"], имя)


ДЕРЖИМ = ("vladelec", "kassir_admin_test")       # учётные записи проверки доступа


@pytest.fixture
def db():
    """Своя пустая база на каждую проверку: числа считаются без чужих сделок."""
    with _сервер()["Сессия"]() as сессия:
        for имя in ("Evaluation", "Kiosk", "Point"):
            for строка in сессия.scalars(select(_м(имя))).all():
                сессия.delete(строка)
        for человек in сессия.scalars(select(_м("User"))).all():
            if человек.login not in ДЕРЖИМ:
                сессия.delete(человек)
        сессия.commit()
        yield сессия


def точка(db, имя, город="Алматы", **поля):
    p = _м("Point")(name=имя, city=город, token="pk_" + имя.encode().hex()[:12], **поля)
    db.add(p)
    db.commit()
    return p


def сделка(db, точка_, **поля):
    ev = _м("Evaluation")(client_id=os.urandom(6).hex(), day=поля.pop("день", _сервер()["день"]()),
                          point_id=точка_.id, report=поля.pop("report", {}),
                          public_token=os.urandom(8).hex(), **поля)
    db.add(ev)
    db.commit()
    return ev


def касса(db, точка_, имя, сборка="doctor-114", видели="сейчас"):
    когда = {"сейчас": _сервер()["сейчас"](), "никогда": None}.get(видели, видели)
    k = _м("Kiosk")(name=имя, point_id=точка_.id, token_hash=имя, version=сборка,
                    last_seen_at=когда, machine=имя.lower())
    db.add(k)
    db.commit()
    return k


# ---------------------------------------------------------------- доступ


@pytest.fixture(scope="module")
def client():
    """Сервер целиком — ради проверки доступа. База подменена на свою (правило 2)."""
    from fastapi.testclient import TestClient
    с = _сервер()
    with с["Сессия"]() as сессия:
        if not сессия.scalar(select(_м("User")).where(_м("User").login == "vladelec")):
            сессия.add(_м("User")(login="vladelec", name="Владелец", role=_м("ROLE_ADMIN"),
                                  password_hash=с["хэш"]("admin123")))
            сессия.add(_м("User")(login="kassir_admin_test", name="Кассир",
                                  role=_м("ROLE_CASHIER"), password_hash=с["хэш"]("kassir123")))
            сессия.commit()

    приложение = с["приложение"](init_sqlite=False)

    def своя_база():
        сессия = с["Сессия"]()
        try:
            yield сессия
        finally:
            сессия.close()

    приложение.dependency_overrides[с["get_db"]] = своя_база
    return TestClient(приложение)


def test_without_a_login_nothing_is_given_away(client):
    """Данные по всей сети не отдаются никому, кроме администратора.

    Это не формальность: здесь выручка по точкам, люди и состояние машин — то, чего не
    должно быть видно ни с кассы на точке, ни тем более снаружи."""
    assert client.get("/api/admin/overview").status_code == 401
    assert client.get("/api/admin/points").status_code == 401
    # токен в заголовке только латиницей: кириллица в заголовок HTTP не лезет вовсе
    assert client.get("/api/admin/machines", headers={"x-admin-token": "vydumannyj"}).status_code == 401

    # кассиру нельзя даже с верным паролем
    assert client.post("/api/admin/login",
                       json={"логин": "kassir_admin_test", "пароль": "kassir123"}).status_code == 403
    assert client.post("/api/admin/login",
                       json={"логин": "vladelec", "пароль": "не тот"}).status_code == 401

    r = client.post("/api/admin/login", json={"логин": "vladelec", "пароль": "admin123"})
    assert r.status_code == 200 and r.json()["имя"] == "Владелец"
    токен = {"x-admin-token": r.json()["токен"]}
    assert client.get("/api/admin/overview", headers=токен).status_code == 200

    # вышел — доступа больше нет
    assert client.post("/api/admin/logout", headers=токен).status_code == 200
    assert client.get("/api/admin/overview", headers=токен).status_code == 401


# ---------------------------------------------------------------- числа


def test_the_overview_counts_todays_work(db):
    """Обзор: проверки, выкупы, выданные деньги и точки за сегодняшний МЕСТНЫЙ день."""
    т1, т2 = точка(db, "16/38 Pintel"), точка(db, "Тарлан")
    сделка(db, т1, status=_м("ST_BOUGHT"), price_offer=180_000, final_price=180_000)
    сделка(db, т1, status=_м("ST_DECLINED"), price_offer=95_000, decision_note="не сошлись в цене")
    сделка(db, т2, status=_м("ST_BOUGHT"), price_offer=240_000, final_price=250_000)
    сделка(db, т2, status="new", price_offer=None)        # автоцены нет — оценивает человек
    сделка(db, т2, status=_м("ST_BOUGHT"), price_offer=90_000, final_price=90_000, день="2026-01-01")

    итог = _сервер()["данные"].обзор(db)
    assert итог["день"] == _сервер()["день"]()
    assert итог["проверок"] == 4, "вчерашняя сделка попала в сегодня"
    assert итог["выкуплено"] == 2
    assert итог["выдано"] == 430_000
    assert итог["средний_чек"] == 215_000
    assert итог["оценил_человек"] == 1
    точки = {т["точка"]: т for т in итог["точки"]}
    assert точки["16/38 Pintel"]["выдано"] == 180_000
    assert точки["Тарлан"]["выкуп"] == 1


def test_an_empty_day_shows_nothing_not_zero(db):
    """Пусто там, где данных нет. Ноль вместо «не знаем» на экране владельца — это ложь,
    по которой принимают решения."""
    точка(db, "Новая точка")
    итог = _сервер()["данные"].обзор(db)
    assert итог["проверок"] == 0
    assert итог["выдано"] is None and итог["средний_чек"] is None


def test_machines_are_listed_apart_from_points(db):
    """Компьютеры — отдельный список: токен принадлежит точке, а машин на точке бывает две."""
    т = точка(db, "Мега Алматы")
    касса(db, т, "KASSA-MEGA-1")
    касса(db, т, "KASSA-MEGA-2", сборка="doctor-109", видели="никогда")

    машины = {м["машина"]: м for м in _сервер()["данные"].компьютеры(db)}
    assert машины["KASSA-MEGA-1"]["точка"] == "Мега Алматы"
    assert машины["KASSA-MEGA-1"]["молчит_часов"] == 0.0
    assert машины["KASSA-MEGA-2"]["молчит_часов"] is None, "машина не выходила на связь ни разу"
    assert [т["касс"] for т in _сервер()["данные"].точки(db)] == [2]


def test_alerts_name_the_point_that_went_quiet(db):
    """Тревога про молчащую точку поднимается только там, где сегодня уже работали:
    закрытая с утра точка — не беда, а обычное утро."""
    шумная = точка(db, "Шымкент · Мега", "Шымкент")
    тихая = точка(db, "Караганда · Сити", "Караганда")
    сделка(db, шумная, status=_м("ST_BOUGHT"), price_offer=100_000, final_price=100_000)
    касса(db, шумная, "KASSA-SHYM", видели=_сервер()["сейчас"]() - timedelta(hours=4))
    касса(db, тихая, "KASSA-KRG", видели=_сервер()["сейчас"]() - timedelta(hours=14))

    тревоги = _сервер()["данные"].тревоги(db, "doctor-114")
    молчат = [т["что"] for т in тревоги if т["вид"] == "точка_молчит"]
    assert any("Шымкент" in ч for ч in молчат), тревоги
    assert not any("Караганда" in ч for ч in молчат), "позвали из-за точки, которая не работала"
    assert тревоги[0]["важность"] == "беда", "беда должна стоять первой"


def test_alerts_see_an_old_build_and_an_overpaid_deal(db):
    """Старая сборка на точке и выкуп заметно дороже автооценки — обе строки именные."""
    т = точка(db, "Абая 150")
    сделка(db, т, status=_м("ST_BOUGHT"), price_offer=180_000, final_price=230_000, number=12891,
           model_name="iPhone 14 Pro")
    касса(db, т, "KASSA-ABAYA", сборка="doctor-109")

    тревоги = _сервер()["данные"].тревоги(db, "doctor-114")
    переплаты = [т for т in тревоги if т["вид"] == "переплата"]
    старые = [т for т in тревоги if т["вид"] == "старая_сборка"]
    assert переплаты and "50 000" in переплаты[0]["что"], тревоги
    assert "12891" in переплаты[0]["почему"]
    assert старые and "doctor-109" in старые[0]["что"]
    # на свежей сборке тревоги быть не должно
    assert not [т for т in _сервер()["данные"].тревоги(db, "doctor-109") if т["вид"] == "старая_сборка"]


def test_the_funnel_collects_the_reasons_people_walked_away(db):
    """Причины отказов: по ним решают, менять ли прайс. Без причины — так и написано."""
    т = точка(db, "Достык Плаза")
    сделка(db, т, status=_м("ST_DECLINED"), decision_note="не сошлись в цене")
    сделка(db, т, status=_м("ST_DECLINED"), decision_note="не сошлись в цене")
    сделка(db, т, status=_м("ST_DECLINED"), decision_note="")
    сделка(db, т, status=_м("ST_BOUGHT"), price_offer=100_000, final_price=100_000)

    воронка = _сервер()["данные"].воронка(db, 30)
    причины = {п["причина"]: п["случаев"] for п in воронка["причины"]}
    assert причины["не сошлись в цене"] == 2
    assert причины["причина не записана"] == 1
    assert воронка["прочитали"] == 4 and воронка["выкупили"] == 1
    assert воронка["доля_выкупа"] == 25


def test_people_show_who_works_and_who_is_shut_out(db):
    """Люди: выработка за месяц и доступ. Закрытый доступ виден сразу — это и есть
    управление людьми, ради которого программу и делают."""
    т = точка(db, "16/38 Pintel")
    работает = _м("User")(login="daniyar", name="Данияр К.", role=_м("ROLE_CASHIER"),
                          point_id=т.id, password_hash="x", is_active=True)
    уволен = _м("User")(login="bauyrzhan", name="Бауыржан Т.", role=_м("ROLE_CASHIER"),
                        point_id=т.id, password_hash="x", is_active=False)
    db.add_all([работает, уволен])
    db.commit()
    сделка(db, т, status=_м("ST_BOUGHT"), price_offer=150_000, final_price=150_000,
           assigned_user_id=работает.id)
    сделка(db, т, status=_м("ST_DECLINED"), assigned_user_id=работает.id)

    люди = {ч["логин"]: ч for ч in _сервер()["данные"].люди(db)}
    assert люди["daniyar"]["проверок_за_месяц"] == 2
    assert люди["daniyar"]["выкупов_за_месяц"] == 1
    assert люди["daniyar"]["выдано_за_месяц"] == 150_000
    assert люди["daniyar"]["точка"] == "16/38 Pintel"
    assert люди["bauyrzhan"]["доступ"] is False
    assert люди["bauyrzhan"]["выдано_за_месяц"] is None, "ноль вместо «ничего не было» — ложь"
