# -*- coding: utf-8 -*-
"""Сервер: учётные записи, роли, журнал, API киоска, оценки и решения кассы (SQLite во временной папке)."""
import json, os, re, tempfile
from urllib.parse import unquote

_TMP = tempfile.mkdtemp()
os.environ["PINTEL_DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["PINTEL_SECRET_KEY"] = "test"
os.environ["PINTEL_SICKW_KEY"] = "test-key"
os.environ["PINTEL_PUBLIC_URL"] = "http://testserver"
os.environ["PINTEL_MEDIA_DIR"] = f"{_TMP}/media"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from pintel_server.main import create_app
from pintel_server.db import SessionLocal, init_db
from pintel_server.models import (AuditLog, Device, Evaluation, Kiosk, LoginEvent, Point, User,
                                   ROLE_ADMIN, ROLE_CASHIER, ROLE_SENIOR)
from pintel_server.auth import hash_password
from pintel_server.services import references
from pintel_core.devicelink import snapshot
from pintel_core.analysis import report as report_mod
from pintel_core.external import sickw

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture(scope="module")
def app():
    init_db()
    db = SessionLocal()
    db.add(User(login="admin", name="Администратор", role=ROLE_ADMIN, password_hash=hash_password("admin123")))
    db.add(User(login="asel", name="Асель Бекова", role=ROLE_CASHIER, password_hash=hash_password("asel123")))
    db.add(User(login="daniyar", name="Данияр Сапаров", role=ROLE_SENIOR, password_hash=hash_password("dan123")))
    db.commit(); db.close()
    return create_app(init_sqlite=False)


def loc(r):
    return unquote(r.headers.get("location", ""))


def точка(имя, токен=None):
    """Завести точку с токеном прямо в базе — так же, как это делают в TablePlus.

    Киосков руками больше не заводят: токен принадлежит точке, а машина записывается сама
    при первом запросе. → заголовки для программы на этой точке."""
    from pintel_server.models import Point
    токен = токен or ("pk_" + имя.encode("utf-8").hex()[:16])
    db = SessionLocal()
    try:
        p = db.scalar(select(Point).where(Point.name == имя))
        if p is None:
            p = Point(name=имя, token=токен)
            db.add(p)
        else:
            p.token = токен
        db.commit()
        return {"X-Kiosk-Token": токен, "X-Kiosk-Machine": "TEST-PC"}
    finally:
        db.close()


def client_for(app, login=None, password=None):
    c = TestClient(app, follow_redirects=False)
    if login:
        r = c.post("/login", data={"login": login, "password": password})
        assert r.status_code == 303 and r.headers["location"] == "/queue", r.headers
    return c


def real_report():
    snap = snapshot.loads(open(os.path.join(HERE, "fixtures_real", "iphone12_ios26_anon.snapshot.json"), encoding="utf-8").read())
    rep = report_mod.build(snap)
    rep["цена"] = {"валюта": "₸", "цена": 75000, "основание": "батарея 78% → столбец «75-79»", "нехватка": []}
    # киоск шлёт JSON как его пишет snapshot.dumps (bytes → {"__b64__": …})
    return json.loads(snapshot.dumps(rep)), json.loads(snapshot.dumps({"root": snap["root"], "quality": snap["quality"]}))


def test_login_and_audit(app):
    c = client_for(app)
    r = c.post("/login", data={"login": "asel", "password": "wrong"})
    assert r.status_code == 303 and "e=1" in loc(r)
    r = c.post("/login", data={"login": "asel", "password": "asel123"})
    assert r.status_code == 303 and "pintel_session" in r.cookies
    assert c.get("/queue").status_code == 200
    db = SessionLocal()
    ev = db.scalars(select(LoginEvent).order_by(LoginEvent.id)).all()
    assert [e.ok for e in ev][-2:] == [False, True] and ev[-2].reason == "неверный пароль"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "login")).actor_name == "Асель Бекова"
    db.close()
    r = c.post("/logout")
    assert r.status_code == 303
    assert c.get("/queue").status_code == 303 and c.get("/queue").headers["location"] == "/login"


def test_roles(app):
    asel = client_for(app, "asel", "asel123")
    assert asel.get("/settings").status_code == 403 and asel.get("/employees").status_code == 403
    dan = client_for(app, "daniyar", "dan123")
    assert dan.get("/settings").status_code == 200 and dan.get("/employees").status_code == 403
    admin = client_for(app, "admin", "admin123")
    assert admin.get("/settings").status_code == 200 and admin.get("/employees").status_code == 200
    assert TestClient(app, follow_redirects=False).get("/settings").status_code == 303


def test_kiosk_flow_and_decisions(app, monkeypatch):
    admin = client_for(app, "admin", "admin123")
    assert admin.post("/settings/points", data={"name": "Алматы-1", "city": "Алматы"}).status_code == 303
    H = точка("Алматы-1")                      # токен точки вписывают в базе, а не в кассе

    k = TestClient(app, follow_redirects=False)
    assert k.get("/api/kiosk/config").status_code == 401
    cfg = k.get("/api/kiosk/config", headers=H).json()
    assert cfg["точка"] == "Алматы-1"
    # прайса на сервере кассы нет: цену сделки считает бот Оценки, второй копии не держим
    assert "прайс_версия" not in cfg and "прайс_обновлён" not in cfg
    assert "TEST-PC" in cfg["киоск"]           # машина записалась сама
    assert k.get("/api/kiosk/price", headers=H).status_code == 404

    assert admin.post("/settings/price/refresh").status_code in (404, 405)

    # оценка с киоска, идемпотентно
    rep, snap = real_report()
    body = {"client_id": "c-1", "report": rep, "snapshot": snap}
    r1 = k.post("/api/kiosk/evaluations", json=body, headers=H).json()
    assert r1["номер"] is None and r1["создана"] is True and r1["ссылка_отчёта"].startswith("http://testserver/r/")
    assert "ссылка_данных" not in r1                                 # клиент сам ничего не вводит
    # номер заявки выдаётся, когда сотрудник в кассе записал имя и телефон клиента
    assert admin.post(f"/deal/{r1['id']}/client", data={"client_name": "Айгерим", "client_phone": "+77001112233"}).status_code == 303
    st = k.get(f"/api/kiosk/evaluations/{r1['id']}/intake", headers=H).json()
    assert st["номер"] == 1 and st["ссылка_отчёта"].startswith("http://testserver/r/")
    r2 = k.post("/api/kiosk/evaluations", json=body, headers=H).json()
    assert r2["id"] == r1["id"] and r2["создана"] is False
    r3 = k.post("/api/kiosk/evaluations", json={**body, "client_id": "c-2"}, headers=H).json()
    assert r3["номер"] is None and r3["уже_приносили"] is True
    assert k.post(f"/api/kiosk/evaluations/{r1['id']}/decision", json={"decision": "sell"}, headers=H).json()["статус"] == "at_counter"
    assert k.post("/api/kiosk/heartbeat", json={"version": "1.0", "status": {"драйвер": True}}, headers=H).json()["ok"]
    # история Apple пришла позже — киоск досылает отчёт
    rep2 = dict(rep); rep2["apple_история"] = {"Display": {"деталь": "Экран", "код": 1025, "меняли": True, "бу": False, "дата": ""}}
    r = k.patch(f"/api/kiosk/evaluations/{r1['id']}", json={"report": rep2, "snapshot_patch": {"repair_history": rep2["apple_история"]}}, headers=H)
    assert r.status_code == 200 and r.json()["apple"] == "менялось: Экран"
    assert k.patch("/api/kiosk/evaluations/999", json={"report": rep2}, headers=H).status_code == 404

    db = SessionLocal()
    ev = db.get(Evaluation, r1["id"])
    # 77 — процент с экрана телефона (минимум за жизнь), не текущая ёмкость
    assert ev.model_name == "iPhone 12" and ev.battery_health == 77 and ev.price_offer == 75000 and ev.apple_summary == "менялось: Экран"
    assert ev.snapshot["repair_history"]["Display"]["меняли"] is True
    assert ev.locks_summary == "Найти iPhone вкл." and ev.point_id == 1 and ev.snapshot["root"]["ProductType"] == "iPhone13,2"
    dev = db.scalar(select(Device).where(Device.serial == ev.serial))
    assert dev.evaluations_count == 2
    assert db.scalar(select(Kiosk)).version == "1.0"
    public = ev.public_token
    db.close()

    # касса: очередь, карточка, решение
    asel = client_for(app, "asel", "asel123")
    page = asel.get("/queue").text
    assert "iPhone 12" in page and "Клиент идёт к кассе" in page and "уже приносили" in page
    assert asel.get(f"/deal/{r1['id']}").status_code == 200
    assert asel.post(f"/deal/{r1['id']}/take").status_code == 303
    r = asel.post(f"/deal/{r1['id']}/decide", data={"kind": "bought", "final_price": "80 000", "note": ""})
    assert "старший" in loc(r)
    r = asel.post(f"/deal/{r1['id']}/decide", data={"kind": "bought", "final_price": "74000", "note": "царапины", "scratches": "on"})
    assert "Решение записано" in loc(r)
    db = SessionLocal()
    ev = db.get(Evaluation, r1["id"])
    assert ev.status == "bought" and ev.final_price == 74000 and ev.inspection["царапины_экрана"] is True and ev.decided_by.login == "asel"
    logs = [l.text for l in db.scalars(select(AuditLog).where(AuditLog.entity_id == ev.id, AuditLog.entity == "evaluation")).all()]
    assert any("Оформил(а) выкуп №1" in t and "(прайс 75000)" in t for t in logs)
    db.close()
    dan = client_for(app, "daniyar", "dan123")
    r = dan.post(f"/deal/{r3['id']}/decide", data={"kind": "bought", "final_price": "80000"})
    assert "Решение записано" in loc(r)
    assert "ВЫКУПЛЕНО" in asel.get("/queue").text.upper()
    pub = TestClient(app).get(f"/r/{public}")
    assert pub.status_code == 200 and "iPhone 12" in pub.text
    assert "Цену назовёт сотрудник" in pub.text and "75 000" not in pub.text   # цену клиенту не показываем


def test_sickw_via_server_uses_db_cache(app, monkeypatch):
    calls = []
    def fake_get(params, timeout=60):
        calls.append(params)
        return {"status": "success", "result": 'Model: iPhone 12 64GB Black [A2403]<br>Blacklist Status: <font color="green">CLEAN</font><br>iCloud Lock: <font color="red">ON</font><br>'}
    monkeypatch.setattr(sickw, "_get", fake_get)
    admin = client_for(app, "admin", "admin123")
    H = точка("Точка-2")
    k = TestClient(app)
    r = k.post("/api/kiosk/sickw", json={"imei": "490154203237518"}, headers=H).json()
    assert r["в_чёрном_списке"] is False and r["fmi_включён"] is True and r["цвет"] == "чёрный"
    r = k.post("/api/kiosk/sickw", json={"imei": "490154203237518"}, headers=H).json()
    assert r["из_кэша"] is True and len(calls) == 1
    assert k.post("/api/kiosk/sickw", json={"imei": "123"}, headers=H).status_code == 502


def test_employees_create_update_and_revoke(app):
    admin = client_for(app, "admin", "admin123")
    r = admin.post("/employees", data={"name": "Мадина Ержанова", "login": "madina", "role": "cashier", "password": "madina1", "point_id": ""})
    assert "Сотрудник добавлен" in loc(r)
    madina = client_for(app, "madina", "madina1")
    assert madina.get("/queue").status_code == 200
    db = SessionLocal(); uid = db.scalar(select(User).where(User.login == "madina")).id; db.close()
    r = admin.post(f"/employees/{uid}", data={"name": "Мадина Ержанова", "role": "cashier", "point_id": ""})   # без is_active → отключить
    assert "Сохранено" in loc(r)
    assert madina.get("/queue").status_code == 303                     # сессия отозвана
    r = TestClient(app, follow_redirects=False).post("/login", data={"login": "madina", "password": "madina1"})
    assert "e=1" in loc(r)
    r = admin.post("/employees/1", data={"name": "Администратор", "role": "cashier", "point_id": "", "is_active": "on"})
    assert "самого себя" in loc(r)
    page = admin.get("/employees?show=logins").text
    assert "доступ отключён" in page and "Неудачная попытка" in page


def test_kiosk_intake_staff_entry_media_and_import(app, monkeypatch):
    """Данные клиента и фото/видео вносит сотрудник в кассе: номер заявки — только после имени
    и телефона; фото — с компьютера кассы или с телефона сотрудника по временной ссылке /m;
    затем импорт в Оценку."""
    admin = client_for(app, "admin", "admin123")
    admin.post("/settings/points", data={"name": "Интейк-город", "city": "Алматы"})
    H = точка("Интейк-точка")
    k = TestClient(app)
    rep, snap = real_report()

    resp = k.post("/api/kiosk/evaluations", json={"client_id": "intake-1", "report": rep, "snapshot": snap},
                  headers=H).json()
    ev_id = resp["id"]
    assert resp["номер"] is None and "ссылка_данных" not in resp and "ссылка_медиа" not in resp
    assert TestClient(app).get("/u/whatever").status_code == 404        # страницы клиента больше нет
    assert k.patch(f"/api/kiosk/evaluations/{ev_id}/details", json={"client_name": "x"}, headers=H).status_code in (404, 405)

    # карточка сделки: форма клиента, загрузка с компьютера и QR для телефона сотрудника
    page = admin.get(f"/deal/{ev_id}").text
    assert f'action="/deal/{ev_id}/client"' in page and f"/deal/{ev_id}/media_qr.svg" in page and "/m/" in page
    svg = admin.get(f"/deal/{ev_id}/media_qr.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml") and b"<path" in svg.content
    assert TestClient(app, follow_redirects=False).get(f"/deal/{ev_id}/media_qr.svg").status_code in (303, 401, 403)

    # без имени и телефона номер не выдаётся
    admin.post(f"/deal/{ev_id}/client", data={"client_name": "", "client_phone": "", "has_box": "yes"})
    assert k.get(f"/api/kiosk/evaluations/{ev_id}/intake", headers=H).json()["номер"] is None
    # с именем и телефоном — номер выдан, киоск его видит
    r = admin.post(f"/deal/{ev_id}/client", data={"client_name": "Иван", "client_phone": "+77001234567", "has_cord": "no"})
    assert r.status_code == 303 and "№1" in loc(r)
    st = k.get(f"/api/kiosk/evaluations/{ev_id}/intake", headers=H).json()
    assert st["номер"] == 1 and st["готово"] is True and "/r/" in st["ссылка_отчёта"]

    # фото: с компьютера кассы и с телефона сотрудника по временной ссылке /m
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    r = admin.post(f"/deal/{ev_id}/media", files={"files": ("phone.jpg", png, "image/jpeg")})
    assert r.status_code == 303 and "Загружено" in loc(r)
    db = SessionLocal(); ev = db.get(Evaluation, ev_id); m_token = ev.media_token
    assert ev.number == 1 and ev.client_name == "Иван" and ev.client_phone == "+77001234567"
    assert ev.has_box is True and ev.has_cord is False
    db.close()
    pub = TestClient(app)
    assert "Иван" in pub.get(f"/m/{m_token}").text
    r = pub.post(f"/m/{m_token}", files={"files": ("video.mp4", b"\x00" * 100, "video/mp4")})
    assert r.status_code in (200, 303)
    media = k.get(f"/api/kiosk/evaluations/{ev_id}/media", headers=H).json()["медиа"]
    assert [m["вид"] for m in media] == ["photo", "video"]
    logs = [l.text for l in SessionLocal().scalars(select(AuditLog).where(AuditLog.entity_id == ev_id, AuditLog.entity == "evaluation")).all()]
    assert any("Данные клиента по заявке №1" in t for t in logs) and any("С телефона сотрудника" in t for t in logs)

    # импорт выключен (нет PINTEL_OCENKA_DB_URL) → понятная 400
    assert k.post(f"/api/kiosk/evaluations/{ev_id}/import", headers=H).status_code == 400

    # импорт включён, но без имени/телефона — отказ (до обращения к БД Оценки)
    from pintel_server.config import settings as cfg
    monkeypatch.setattr(cfg, "ocenka_db_url", "postgresql+psycopg://u:p@localhost/pintel_ocenka_test")
    ev2 = k.post("/api/kiosk/evaluations", json={"client_id": "intake-2", "report": rep, "snapshot": snap},
                 headers=H).json()["id"]
    r = k.post(f"/api/kiosk/evaluations/{ev2}/import", headers=H)
    assert r.status_code == 400 and "имя и телефон" in r.json()["detail"]


def test_cashier_sees_client_data_media_and_import_button(app):
    admin = client_for(app, "admin", "admin123")
    H = точка("Касса-точка")
    k = TestClient(app)
    rep, snap = real_report()
    resp = k.post("/api/kiosk/evaluations", json={"client_id": "cash-1", "report": rep, "snapshot": snap}, headers=H).json()
    ev_id = resp["id"]
    admin.post(f"/deal/{ev_id}/client", data={"client_name": "Пётр", "client_phone": "+77009998877"})
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    admin.post(f"/deal/{ev_id}/media", files={"files": ("p.jpg", png, "image/jpeg")})

    page = admin.get(f"/deal/{ev_id}").text
    assert "Пётр" in page and "Отправить в Оценку" in page and 'src="/media/' in page
    media_id = k.get(f"/api/kiosk/evaluations/{ev_id}/media", headers=H).json()["медиа"][0]["id"]
    img = admin.get(f"/media/{media_id}")
    assert img.status_code == 200 and img.content.startswith(b"\x89PNG")
    # импорт выключен → редирект с понятной ошибкой
    r = admin.post(f"/deal/{ev_id}/import_ocenka")
    assert r.status_code == 303 and "выключен" in loc(r)


def test_staff_parts_check_gates_import(app, monkeypatch):
    """Без подтверждения Apple автоматика зелёного не даёт; сотрудник сверяет экран телефона
    («Об этом устройстве») и отмечает в карточке — только после этого сделка может уйти в Оценку."""
    admin = client_for(app, "admin", "admin123")
    H = точка("Сверка-точка")
    rep, snap = real_report()                        # iPhone 12, iOS 26: записи с нулями, сверки нет
    assert rep["детали_вердикт"]["итог"] == "кабель" and rep["итог"]["вердикт"] == "ПРОВЕРКА НЕПОЛНАЯ"
    ev_id = TestClient(app).post("/api/kiosk/evaluations", json={"client_id": "parts-1", "report": rep, "snapshot": snap},
                                 headers=H).json()["id"]
    admin.post(f"/deal/{ev_id}/client", data={"client_name": "Ержан", "client_phone": "+77005550000"})
    page = admin.get(f"/deal/{ev_id}").text
    assert "Apple не подтвердила подлинность деталей" in page
    assert "Откройте экран на телефоне" in page and "данные придут сами" in page   # сначала ждём телефон
    assert "может не быть" in page                  # честно: на чистом аппарате строки раздела нет
    assert "если телефон уже отключили" in page                                     # руками — только запасной путь
    st = admin.get(f"/deal/{ev_id}/state").json()
    assert st["нужна_сверка"] is True and st["детали"] == "кабель" and "|" in st["ключ"]
    from pintel_server.config import settings as cfg
    monkeypatch.setattr(cfg, "ocenka_db_url", "postgresql+psycopg://u:p@localhost/pintel_ocenka_test")
    r = admin.post(f"/deal/{ev_id}/import_ocenka")
    assert r.status_code == 303 and "сверьте" in loc(r)                 # без сверки — не уходит
    r = admin.post(f"/deal/{ev_id}/parts", data={"Battery": "serviced", "Display": "unknown",
                                                "Camera": "genuine", "note": "экран без даты"})
    assert r.status_code == 303
    page = admin.get(f"/deal/{ev_id}").text
    assert "Дисплей: Неизвестная запасная часть" in page and "экран без даты" in page
    db = SessionLocal(); ev = db.get(Evaluation, ev_id)
    from pintel_server.services import ocenka_import as oi
    assert oi._phone_status(ev) == "Ранее был в ремонте"
    assert "Дисплей — Неизвестная запасная часть" in oi._comment_ocenka(ev)
    logs = [l.text for l in db.scalars(select(AuditLog).where(AuditLog.entity_id == ev_id, AuditLog.entity == "evaluation")).all()]
    assert any("Сверка «Детали и обслуживание»" in t and "Дисплей — Неизвестная запасная часть" in t for t in logs)
    db.close()
    r = admin.post(f"/deal/{ev_id}/import_ocenka")
    assert "сверьте" not in loc(r)                      # дальше упирается в недоступную БД Оценки, не в сверку


def test_ocenka_import_field_mapping():
    """Маппинг полей оценки → поля сделки Оценки (без обращения к БД)."""
    from pintel_server.services import ocenka_import as oi
    ev = Evaluation(
        number=7, day="2026-10-26", imei="353915105357912", model_name="iPhone 12", model_code="iPhone13,2",
        capacity_gb=128, battery_health=83, colour="чёрный", verdict="ХОРОШИЙ",
        apple_summary="всё родное", locks_summary="чисто",
        report={"детали_вердикт": {"итог": "родные"}, "паспорт": {"imei2": "353915105357999"}})
    assert oi._phone_status(ev) == "Не был в ремонте"
    ev.report = {"детали_вердикт": {"итог": "замена"}}
    assert oi._phone_status(ev) == "Ранее был в ремонте"
    imeis = oi._imeis(ev)
    assert imeis[0][0] == "353915105357912" and imeis[0][2] is True   # основной IMEI первым
    assert "Киоск №7" in oi._comment_ocenka(ev)
    assert oi.staff_list() == []   # Оценка выключена в тестах → список сотрудников пуст


def test_references_collect_themselves_from_every_phone(app):
    """Эталон собирается сам с каждого телефона: киоск уже прислал слепок с сырым журналом
    Apple, а сверка сотрудника — та же правда с экрана. Выгрузка обезличена, ценное идёт
    первым, одно и то же второй раз не едет."""
    import io
    import zipfile

    admin = client_for(app, "admin", "admin123")
    H = точка("Эталон-точка")

    snap = snapshot.loads(open(os.path.join(HERE, "fixtures_real", "iphone12_ios26_anon.snapshot.json"),
                               encoding="utf-8").read())
    snap["root"]["SerialNumber"] = "ZZTESTSERIAL9"            # его не должно быть в выгрузке
    snap["repair_history"], snap["repair_history_meta"] = {}, {"раздел_открыт": True, "формат": None}
    snap["repair_history_raw"] = ("Oct 27 19:35:24 iPhone mobilerepaird(CoreRepairCore)[212] <Notice>: "
                                  "совершенно новая строка этой iOS\n")
    rep = report_mod.build(snap)
    rep["цена"] = {"валюта": "₸", "цена": 70000, "основание": "тест", "нехватка": []}
    ev_id = TestClient(app).post("/api/kiosk/evaluations",
                                 json={"client_id": "ref-auto-1", "report": json.loads(snapshot.dumps(rep)),
                                       "snapshot": json.loads(snapshot.dumps(snap))}, headers=H).json()["id"]

    page = admin.get("/эталоны").text
    assert "журнал пришёл" in page and "не распознан" in page   # самый ценный материал виден сразу

    r = admin.post("/эталоны/выгрузка")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "сводка.md" in names and any(n.startswith("эталоны/эталон_") for n in names)
    assert "не распознан" in z.read("сводка.md").decode("utf-8")
    assert b"ZZTESTSERIAL9" not in r.content                       # обезличено: серийника нет нигде
    наш = None                                                     # в выгрузке и другие аппараты — ищем свой
    for n in [x for x in names if x.endswith(".zip")]:
        b = zipfile.ZipFile(io.BytesIO(z.read(n)))
        if "совершенно новая строка" in b.read("apple_raw.txt").decode("utf-8"):
            наш = b
    assert наш is not None, names                                  # сырые строки новой iOS доехали
    assert json.loads(наш.read("правда.json"))["раздел_открывали"] is True

    assert loc(admin.post("/эталоны/выгрузка")).startswith("/эталоны?m=")   # второй раз то же не едет

    # сотрудник сверил экран: телефон показывает «Неизвестно» — появилась правда, и аппарат
    # снова становится материалом для разбора, уже с эталонным ответом
    admin.post(f"/deal/{ev_id}/parts", data={"Display": "unknown", "note": "экран неоригинал"})
    page = admin.get("/эталоны").text
    assert "есть" in page                              # сверка сотрудника видна в таблице
    db = SessionLocal()
    try:
        row = {x["id"]: x for x in references.rows(db)}[ev_id]
        _, data, _ = references.bundle(db.get(Evaluation, ev_id))
    finally:
        db.close()
    # телефон показал «Неизвестно», а мы такого не сказали — это главный материал для разбора
    assert row["правда"] is True and row["важность"] == 3 and "расхождение" in row["почему"]
    внутри = zipfile.ZipFile(io.BytesIO(data))
    правда = json.loads(внутри.read("правда.json"))
    assert правда["детали"] == {"Display": "unknown"} and правда["кто"] == "Администратор"
    assert "Неизвестная запасная часть" in внутри.read("расхождения.txt").decode("utf-8")

    # и главное: аппарат уже выгружали, но сверка появилась ПОСЛЕ — значит он обязан уехать
    # снова, иначе расхождение, найденное задним числом, не дойдёт до разбора никогда
    r3 = admin.post("/эталоны/выгрузка")
    assert r3.status_code == 200, loc(r3)
    z3 = zipfile.ZipFile(io.BytesIO(r3.content))
    снова = [n for n in z3.namelist() if n.endswith(".zip")
             and "Неизвестная запасная часть" in zipfile.ZipFile(
                 io.BytesIO(z3.read(n))).read("расхождения.txt").decode("utf-8")]
    assert снова, z3.namelist()


def test_queue_never_says_all_genuine_without_apple():
    """«Всё родное» в очереди — только с подтверждением Apple. Записи о ремонтах с нулями
    выглядят так же, и на демо именно они дали зелёное при «Неизвестно» на экране."""
    from pintel_server.services.evaluations import apple_summary
    журнал = {"Display": {"деталь": "Экран", "меняли": False}}
    assert apple_summary({"apple_история": журнал,
                          "детали_вердикт": {"apple_подтверждено": True}}) == "всё родное"
    assert apple_summary({"apple_история": журнал,
                          "детали_вердикт": {"apple_подтверждено": False}}) == "Apple не подтвердила"
    assert apple_summary({"apple_история": {}}) == "ждёт раздел на телефоне"
    assert apple_summary({"apple_история": {"Display": {"деталь": "Экран", "меняли": True}},
                          "детали_вердикт": {"apple_подтверждено": True}}) == "менялось: Экран"


def test_the_phone_test_lives_on_our_domain(app):
    """Тест на телефоне клиента по HTTPS: касса заводит сессию, телефон открывает страницу и
    присылает ответы, касса их забирает. На домене браузер пускает страницу к микрофону, а по
    локальной сети — нет, поэтому точка с интернетом ходит сюда.

    Строку заводит ТОЛЬКО касса: на выдуманный токен с улицы ничего не положить."""
    from pintel_core import phonetest
    admin = client_for(app, "admin", "admin123")
    H = точка("Тест-точка")
    k = TestClient(app)
    телефон = TestClient(app)                                  # чужой телефон: без токена киоска

    # чужого токена нет — ни страницы, ни приёма
    assert телефон.get("/t/NETAKOGO").status_code == 410
    assert телефон.post("/api/phone/NETAKOGO", json={"sensor": "ok"}).status_code == 410

    открыт = k.post("/api/kiosk/phone", json={"token": "QR123TEST"}, headers=H).json()
    assert открыт["ссылка"].endswith("/t/QR123TEST")
    стр = телефон.get("/t/QR123TEST")
    assert стр.status_code == 200 and "Тест телефона" in стр.text
    for ключ in phonetest.КЛЮЧИ:                               # страница спрашивает ровно наши тесты
        assert ключ in стр.text

    assert k.get("/api/kiosk/phone/QR123TEST", headers=H).json()["готов"] is False
    ответ = {k2: phonetest.ОК for k2 in phonetest.КЛЮЧИ}
    ответ.update({"speaker": phonetest.ПЛОХО, "устройство": "iPhone", "чужое": "выкинуть"})
    assert телефон.post("/api/phone/QR123TEST", json=ответ).status_code == 200
    готово = k.get("/api/kiosk/phone/QR123TEST", headers=H).json()
    assert готово["готов"] is True and готово["результат"]["speaker"] == "fail"
    assert "чужое" not in готово["результат"]                  # в базу ложатся только наши ключи
    assert телефон.post("/api/phone/QR123TEST", json={"мусор": 1}).status_code == 400
    assert k.get("/api/kiosk/phone/NETAKOGO", headers=H).status_code == 404


def test_the_receipt_is_on_our_domain(app):
    """Чек на домене — тот же документ, что печатают на точке: бумага теряется, ссылка
    остаётся. Собирает его тот же pintel_core.receipt, поэтому они не разойдутся."""
    admin = client_for(app, "admin", "admin123")
    H = точка("Чек-точка")
    k = TestClient(app)
    rep, snap = real_report()
    resp = k.post("/api/kiosk/evaluations", json={"client_id": "check-1", "report": rep, "snapshot": snap},
                  headers=H).json()
    assert resp["ссылка_чека"].endswith("/check/" + resp["ссылка_отчёта"].rsplit("/", 1)[-1])
    # киоск дослал чек и результат теста — то, что появилось уже после создания оценки
    rep2 = {**rep, "чек": {"номер": "A-7", "клиент": "Зама", "телефон": "+77058837953",
                           "сотрудник": "Асылбек", "точка": "16/38", "коробка": True,
                           "ссылка": resp["ссылка_чека"]},
            "тест_телефона": {"sensor": "ok", "speaker": "fail"}}
    assert k.patch(f"/api/kiosk/evaluations/{resp['id']}", json={"report": rep2}, headers=H).status_code == 200

    страница = TestClient(app).get(resp["ссылка_чека"].replace("http://testserver", ""))
    assert страница.status_code == 200
    for кусок in ("Зама", "Асылбек", "iPhone 12", "A-7"):
        assert кусок in страница.text, кусок
    assert "<svg" in страница.text                                 # QR на сам себя
    assert TestClient(app).get("/check/нет-такого").status_code == 404

    # оценка целиком лежит в базе: отчёт, слепок, чек и тест — всё вместе
    db = SessionLocal()
    ev = db.scalar(select(Evaluation).where(Evaluation.client_id == "check-1"))
    assert ev.report["чек"]["клиент"] == "Зама" and ev.report["тест_телефона"]["speaker"] == "fail"
    assert ev.snapshot and ev.verdict
    db.close()


def test_old_snapshots_are_pruned_but_the_evaluation_stays(app):
    """«Все оценки сохраняются» — это про оценку, а не про сырой слепок. Паспорт, батарея,
    вердикт, чек и тест лежат вечно; слепок весит около мегабайта на аппарат, и при двух
    сотнях оценок в день база росла бы на 6 ГБ в месяц. Разбор по нему нужен первые недели,
    дальше остаётся обезличенный эталон."""
    from datetime import timedelta
    from pintel_server.db import now
    from pintel_server.services import evaluations as ev_service
    admin = client_for(app, "admin", "admin123")
    H = точка("Уборка-точка")
    rep, snap = real_report()
    k = TestClient(app)
    ev_id = k.post("/api/kiosk/evaluations", json={"client_id": "prune-1", "report": rep, "snapshot": snap},
                   headers=H).json()["id"]
    db = SessionLocal()
    ev = db.get(Evaluation, ev_id)
    assert ev.snapshot
    ev.created_at = now() - timedelta(days=400)
    db.commit()
    assert ev_service.prune_snapshots(db, 0) == 0            # 0 — не чистить вовсе
    assert ev_service.prune_snapshots(db, 60) == 1
    db.expire_all()
    ev = db.get(Evaluation, ev_id)
    assert ev.snapshot is None                               # слепок ушёл
    assert ev.report and ev.verdict and ev.model_name        # сама оценка на месте
    assert ev_service.prune_snapshots(db, 60) == 0           # повторно чистить нечего
    # эталон аппарата при этом не теряется: его файл точка прислала сразу после проверки
    # и он чистится своим сроком, не завися от слепка
    assert ev_service.prune_references(db, 60) == 0
    db.close()


def test_the_receipt_is_on_our_domain(app):
    """Чек на домене — тот же документ, что печатают на точке: бумага теряется, ссылка
    остаётся. Собирает его тот же pintel_core.receipt, поэтому они не разойдутся."""
    admin = client_for(app, "admin", "admin123")
    H = точка("Чек-точка")
    k = TestClient(app)
    rep, snap = real_report()
    resp = k.post("/api/kiosk/evaluations", json={"client_id": "check-1", "report": rep, "snapshot": snap},
                  headers=H).json()
    assert resp["ссылка_чека"].endswith("/check/" + resp["ссылка_отчёта"].rsplit("/", 1)[-1])
    # киоск дослал чек и результат теста — то, что появилось уже после создания оценки
    rep2 = {**rep, "чек": {"номер": "A-7", "клиент": "Зама", "телефон": "+77058837953",
                           "сотрудник": "Асылбек", "точка": "16/38", "коробка": True,
                           "ссылка": resp["ссылка_чека"]},
            "тест_телефона": {"sensor": "ok", "speaker": "fail"}}
    assert k.patch(f"/api/kiosk/evaluations/{resp['id']}", json={"report": rep2}, headers=H).status_code == 200

    страница = TestClient(app).get(resp["ссылка_чека"].replace("http://testserver", ""))
    assert страница.status_code == 200
    for кусок in ("Зама", "Асылбек", "iPhone 12", "A-7"):
        assert кусок in страница.text, кусок
    assert "<svg" in страница.text                                 # QR на сам себя
    assert TestClient(app).get("/check/нет-такого").status_code == 404

    # оценка целиком лежит в базе: отчёт, слепок, чек и тест — всё вместе
    db = SessionLocal()
    ev = db.scalar(select(Evaluation).where(Evaluation.client_id == "check-1"))
    assert ev.report["чек"]["клиент"] == "Зама" and ev.report["тест_телефона"]["speaker"] == "fail"
    assert ev.snapshot and ev.verdict
    db.close()


def test_old_snapshots_are_pruned_but_the_evaluation_stays(app):
    """«Все оценки сохраняются» — это про оценку, а не про сырой слепок. Паспорт, батарея,
    вердикт, чек и тест лежат вечно; слепок весит около мегабайта на аппарат, и при двух
    сотнях оценок в день база росла бы на 6 ГБ в месяц. Разбор по нему нужен первые недели,
    дальше остаётся обезличенный эталон."""
    from datetime import timedelta
    from pintel_server.db import now
    from pintel_server.services import evaluations as ev_service
    admin = client_for(app, "admin", "admin123")
    H = точка("Уборка-точка")
    rep, snap = real_report()
    k = TestClient(app)
    ev_id = k.post("/api/kiosk/evaluations", json={"client_id": "prune-1", "report": rep, "snapshot": snap},
                   headers=H).json()["id"]
    db = SessionLocal()
    ev = db.get(Evaluation, ev_id)
    assert ev.snapshot
    ev.created_at = now() - timedelta(days=400)
    db.commit()
    assert ev_service.prune_snapshots(db, 0) == 0            # 0 — не чистить вовсе
    assert ev_service.prune_snapshots(db, 60) == 1
    db.expire_all()
    ev = db.get(Evaluation, ev_id)
    assert ev.snapshot is None                               # слепок ушёл
    assert ev.report and ev.verdict and ev.model_name        # сама оценка на месте
    assert ev_service.prune_snapshots(db, 60) == 0           # повторно чистить нечего
    # эталон аппарата при этом не теряется: его файл точка прислала сразу после проверки
    # и он чистится своим сроком, не завися от слепка
    assert ev_service.prune_references(db, 60) == 0
    db.close()


def test_the_point_is_a_shop_of_ocenka_and_the_token_lives_in_the_base(app, monkeypatch):
    """Правильная структура: точка — это магазин Оценки, с тем же id. Список точек не
    набирают руками, его заводит `sync-shops` из `shops`. Токен лежит в базе текстом:
    управляют точками там же, веб-кассой не пользуются.

    Раз id совпадает, сделка несёт готовый shop_id, и спрашивать точку в боте не нужно."""
    from pintel_server.services import points as points_service
    магазины = [{"id": 14, "litera": "U", "shop_name": "16/38 Pintel"},
                {"id": 19, "litera": "Z", "shop_name": "Апорт"}]
    monkeypatch.setattr(points_service, "магазины_оценки", lambda: магазины)
    db = SessionLocal()
    итог = points_service.синхронизировать(db)
    assert len(итог["создано"]) >= 2 and итог["токенов_выдано"] >= 2
    апорт = db.get(Point, 19)
    assert апорт.name == "Апорт" and апорт.litera == "Z" and апорт.token.startswith("pk_")
    токен = апорт.token
    db.close()

    # программа при первой настройке берёт список точек без всякого токена
    k = TestClient(app)
    точки = k.get("/api/kiosk/points").json()["точки"]
    assert {"id": 19, "название": "Апорт", "литера": "Z", "город": None} in точки

    H = {"X-Kiosk-Token": токен, "X-Kiosk-Machine": "KASSA-19"}
    assert k.get("/api/kiosk/config", headers={"X-Kiosk-Token": "pk_wrong"}).status_code == 401
    cfg = k.get("/api/kiosk/config", headers=H).json()
    assert cfg["точка"] == "Апорт" and cfg["точка_id"] == 19 and cfg["литера"] == "Z"
    assert "KASSA-19" in cfg["киоск"]                    # машина записалась сама
    assert cfg["настройки"]["apple_history_seconds"] == 90

    # настройки на всю сеть и имя сотрудника точки доезжают до программы
    admin = client_for(app, "admin", "admin123")
    admin.post("/settings/kiosk", data={"ocenka_bot": "PintelOlxBot", "apple_history_seconds": "120",
                                        "return_seconds": "60", "keep_days": "90",
                                        "reference_keep": "500", "phone_test_port": "8765",
                                        "sickw": "on", "rfs": "on", "sickw_services_sealed": "147",
                                        "update_repo": "AsikSoftware/TgOsint",
                                        "company_name": "Pintel.kz"})
    admin.post("/settings/points/19", data={"staff_name": "Асылбек", "city": "Алматы"})
    н = k.get("/api/kiosk/config", headers=H).json()["настройки"]
    assert н["ocenka_bot"] == "PintelOlxBot" and н["apple_history_seconds"] == 120
    assert н["staff_name"] == "Асылбек"
    assert "ocenka_chat_id" not in н, "незаполненное не шлём: это не «сотри то, что есть»"

    # журнал и эталоны с точки
    assert k.post("/api/kiosk/logs", json={"lines": ["связь есть", "оценка отправлена"]},
                  headers=H).json()["принято"] == 2
    имя = "эталон_iPhone-14-Pro_iOS26.5_20261102_084500.zip"
    ответ = k.post("/api/kiosk/reference", headers=H, data={"name": имя},
                   files={"file": ("bundle.zip", b"PK\x03\x04" + b"x" * 100, "application/zip")})
    assert ответ.status_code == 200 and ответ.json()["принят"] is True
    assert k.post("/api/kiosk/reference", headers=H, data={"name": имя},
                  files={"file": ("bundle.zip", b"PK\x03\x04", "application/zip")}
                  ).json()["принят"] is False
    assert k.post("/api/kiosk/reference", headers=H, data={"name": "не-эталон.txt"},
                  files={"file": ("bundle.zip", b"x", "application/zip")}).status_code == 400

    # повторная синхронизация ничего не ломает и токен не трогает
    итог2 = points_service.синхронизировать(SessionLocal())
    assert итог2["создано"] == [] and итог2["токенов_выдано"] == 0
    # в базе живут и точки других тестов — их в списке магазинов нет, поэтому сверяем
    # вхождением, а не равенством
    db = SessionLocal()
    assert db.get(Point, 19).token == токен
    db.close()

    # магазин переименовали в Оценке: имя у нас догоняет, токен остаётся прежним
    магазины[1]["shop_name"] = "Апорт Южный"
    итог3 = points_service.синхронизировать(SessionLocal())
    assert итог3["переименовано"] == ['19 «Апорт» → «Апорт Южный»']
    db = SessionLocal()
    assert db.get(Point, 19).name == "Апорт Южный" and db.get(Point, 19).token == токен
    db.close()
    assert k.get("/api/kiosk/config", headers=H).json()["точка"] == "Апорт Южный"

    # магазин пропал: точку не удаляем и не гасим молча — на ней висят оценки, а сотрудник
    # у стойки не должен узнать об этом по отказу. Называем громко, решает человек.
    магазины.pop()
    итог4 = points_service.синхронизировать(SessionLocal())
    assert "19 Апорт Южный" in итог4["пропали"]
    db = SessionLocal()
    assert points_service.пропала(db.get(Point, 19)) is True
    db.close()
    assert k.get("/api/kiosk/config", headers=H).status_code == 200, "точка продолжает работать"
    # а вот настроить на неё новый компьютер уже нельзя: сделка уехала бы с shop_id, которого
    # у Оценки нет, и бот не смог бы её создать. В списке первой настройки её не видно.
    assert 19 not in [т["id"] for т in k.get("/api/kiosk/points").json()["точки"]]
    # вернули обратно — пометка снимается сама
    магазины.append({"id": 19, "litera": "Z", "shop_name": "Апорт Южный"})
    points_service.синхронизировать(SessionLocal())
    db = SessionLocal()
    assert points_service.пропала(db.get(Point, 19)) is False
    db.close()
    assert 19 in [т["id"] for т in k.get("/api/kiosk/points").json()["точки"]]

    # отключённая точка в список не попадает и внутрь не пускает
    admin.post("/settings/points/19/toggle")
    assert 19 not in [т["id"] for т in k.get("/api/kiosk/points").json()["точки"]]
    assert k.get("/api/kiosk/config", headers=H).status_code == 401
    admin.post("/settings/points/19/toggle")


def db_точка(app, имя):
    from pintel_server.models import Point
    db = SessionLocal()
    try:
        return db.scalar(select(Point).where(Point.name == имя))
    finally:
        db.close()


def test_the_kiosk_can_see_what_reached_the_bot(app, monkeypatch, tmp_path):
    """Касса спрашивает сервер, дошли ли фото и видео: в базу Оценки с точки хода нет, а
    сервер стоит рядом с ней. Без этого «Отправить в Оценку» нажималась бы вслепую.

    Ответ «не знаю» обязан отличаться от «ничего не прислали»: по первому касса работает
    дальше и говорит об этом вслух, по второму — ждёт медиа."""
    from sqlalchemy import create_engine, text as sqltext
    from pintel_server.services import ocenka_import, points as points_service

    monkeypatch.setattr(points_service, "магазины_оценки",
                        lambda: [{"id": 14, "litera": "U", "shop_name": "16/38 Pintel"}])
    db = SessionLocal()
    points_service.синхронизировать(db)
    токен = db.get(Point, 14).token
    db.close()
    k = TestClient(app)
    H = {"X-Kiosk-Token": токен, "X-Kiosk-Machine": "KASSA-14"}

    # базы Оценки нет вовсе — это «не знаю», и так и сказано
    monkeypatch.setattr(ocenka_import, "_ocenka_engine",
                        lambda: (_ for _ in ()).throw(RuntimeError("не настроено")))
    ответ = k.get("/api/kiosk/media/ABCD12", headers=H).json()
    assert ответ["известно"] is False and ответ["почему"]

    # а теперь база есть: заводим такую же таблицу обмена
    движок = create_engine(f"sqlite:///{tmp_path}/ocenka.db", future=True)
    with движок.begin() as conn:
        conn.execute(sqltext("CREATE TABLE kiosk_media (code TEXT, photos TEXT, video TEXT, "
                             "checks TEXT, done INTEGER, device_id INTEGER)"))
    monkeypatch.setattr(ocenka_import, "_ocenka_engine", lambda: движок)

    # ссылку ещё не открывали: строки нет — и это не ошибка, а начало сделки
    пусто = k.get("/api/kiosk/media/ABCD12", headers=H).json()
    assert пусто["известно"] is True and пусто["начали"] is False
    assert пусто["фото"] == 0 and пусто["видео"] is False and пусто["готово"] is False

    with движок.begin() as conn:
        conn.execute(sqltext("INSERT INTO kiosk_media (code, photos, video) "
                             "VALUES ('ABCD12', 'f1||f2', NULL)"))
    серёдка = k.get("/api/kiosk/media/ABCD12", headers=H).json()
    assert серёдка["фото"] == 2 and серёдка["видео"] is False and серёдка["готово"] is False

    with движок.begin() as conn:
        conn.execute(sqltext("UPDATE kiosk_media SET photos = 'f1||f2||f3', video = 'v1' "
                             "WHERE code = 'ABCD12'"))
    готово = k.get("/api/kiosk/media/ABCD12", headers=H).json()
    assert готово["готово"] is True and готово["фото"] == 3 and готово["видео"] is True
    # Про проверки руками сервер не рассказывает вовсе: их отмечают на экране программы.
    # Полям в ответе остаётся сказать сборкам до doctor-64 «не держи сделку из-за них».
    assert готово["диагностика_видна"] is False and готово["не_отмечено"] == []

    # чужой токен внутрь не пускают: по коду обмена видно, что происходит на точке
    assert k.get("/api/kiosk/media/ABCD12", headers={"X-Kiosk-Token": "pk_wrong"}).status_code == 401

    # В таблице обмена может не быть колонки отметок вовсе (она нужна только точкам со
    # старой сборкой). Запрос не должен падать целиком: фото и видео видно по-прежнему.
    старый = create_engine(f"sqlite:///{tmp_path}/старый.db", future=True)
    with старый.begin() as conn:
        conn.execute(sqltext("CREATE TABLE kiosk_media (code TEXT, photos TEXT, video TEXT, "
                             "done INTEGER, device_id INTEGER)"))
        conn.execute(sqltext("INSERT INTO kiosk_media (code, photos, video) "
                             "VALUES ('ABCD12', 'f1||f2||f3', 'v1')"))
    monkeypatch.setattr(ocenka_import, "_ocenka_engine", lambda: старый)
    без_колонки = k.get("/api/kiosk/media/ABCD12", headers=H).json()
    assert без_колонки["известно"] is True and без_колонки["готово"] is True


def test_the_deal_from_the_point_goes_to_the_bot_through_us(app, monkeypatch, tmp_path):
    """Сделку с точки сервер кладёт в таблицу обмена — бот заберёт её оттуда сам.

    Зачем так. Раньше касса слала посылку файлом в чат Telegram, и бот получал её ТОЛЬКО
    когда кто-то нажимал кнопку под карточкой: свои исходящие сообщения бот не видит.
    Значит, сделка зависела от того, доступен ли чат, — а он отказывал («chat not found»,
    «bot was blocked by the user»), и тогда создать её было нельзя вовсе.

    Каждый отказ отдаём словами: по ним касса решает, уходить ли в запасной путь, и
    «не принято» без причины там хуже, чем ничего.
    """
    from sqlalchemy import create_engine, text as sqltext
    from pintel_server.services import ocenka_import, points as points_service

    monkeypatch.setattr(points_service, "магазины_оценки",
                        lambda: [{"id": 14, "litera": "U", "shop_name": "16/38 Pintel"}])
    db = SessionLocal()
    points_service.синхронизировать(db)
    токен = db.get(Point, 14).token
    db.close()
    k = TestClient(app)
    H = {"X-Kiosk-Token": токен, "X-Kiosk-Machine": "KASSA-14"}
    посылка = {"версия": 1, "код": "ABCD12", "сделка": {"model": "iPhone 14 Pro"}}

    движок = create_engine(f"sqlite:///{tmp_path}/ocenka_parcel.db", future=True)
    with движок.begin() as conn:
        conn.execute(sqltext("CREATE TABLE kiosk_media (code TEXT, photos TEXT, video TEXT, "
                             "done INTEGER, device_id INTEGER, parcel TEXT, parcel_at TEXT, "
                             "parcel_error TEXT)"))
    monkeypatch.setattr(ocenka_import, "_ocenka_engine", lambda: движок)

    # QR никто не сканировал — сделка ни к кому не привязана, и это сказано словами
    нет = k.post("/api/kiosk/media/ABCD12/parcel", headers=H, json={"посылка": посылка}).json()
    assert нет["принято"] is False and "не привязана" in нет["почему"]

    with движок.begin() as conn:
        conn.execute(sqltext("INSERT INTO kiosk_media (code, photos, video) "
                             "VALUES ('ABCD12', 'f1||f2||f3', 'v1')"))
    ответ = k.post("/api/kiosk/media/ABCD12/parcel", headers=H, json={"посылка": посылка}).json()
    assert ответ["принято"] is True
    with движок.connect() as conn:
        лежит = conn.execute(sqltext("SELECT parcel FROM kiosk_media WHERE code = 'ABCD12'")).scalar()
    assert json.loads(лежит)["сделка"]["model"] == "iPhone 14 Pro"
    # касса видит по тому же адресу, что посылка у бота и ждёт своей очереди
    assert k.get("/api/kiosk/media/ABCD12", headers=H).json()["посылка_ждёт"] is True

    # чужой код в посылке не принимаем: иначе сделка уедет на другой телефон
    чужая = k.post("/api/kiosk/media/ABCD12/parcel", headers=H,
                   json={"посылка": {**посылка, "код": "ZZZZ99"}}).json()
    assert чужая["принято"] is False and "код" in чужая["почему"]

    # сделка уже создана — второй раз не кладём, но и не пугаем: отвечаем её номером
    with движок.begin() as conn:
        conn.execute(sqltext("UPDATE kiosk_media SET device_id = 7311 WHERE code = 'ABCD12'"))
    снова = k.post("/api/kiosk/media/ABCD12/parcel", headers=H, json={"посылка": посылка}).json()
    assert снова["принято"] is True and снова["сделка"] == 7311

    # база без новых колонок (её ещё не обновили) — отказ словами, а не падение: касса
    # по нему уходит в запасной путь и шлёт карточку в чат, как раньше
    старая = create_engine(f"sqlite:///{tmp_path}/ocenka_old.db", future=True)
    with старая.begin() as conn:
        conn.execute(sqltext("CREATE TABLE kiosk_media (code TEXT, photos TEXT, video TEXT, "
                             "done INTEGER, device_id INTEGER)"))
        conn.execute(sqltext("INSERT INTO kiosk_media (code, photos, video) "
                             "VALUES ('ABCD12', 'f1||f2||f3', 'v1')"))
    monkeypatch.setattr(ocenka_import, "_ocenka_engine", lambda: старая)
    отказ = k.post("/api/kiosk/media/ABCD12/parcel", headers=H, json={"посылка": посылка}).json()
    assert отказ["принято"] is False and отказ["почему"]

    # чужой токен внутрь не пускают: посылка — это имя, телефон и аппарат клиента
    assert k.post("/api/kiosk/media/ABCD12/parcel", headers={"X-Kiosk-Token": "pk_wrong"},
                  json={"посылка": посылка}).status_code == 401


def test_the_point_learns_who_is_linked_and_asks_the_bot_for_a_price(app, monkeypatch, tmp_path):
    """Порядок с 12.11.2026: QR сканируют в начале сделки, и касса видит, кто привязан;
    автоцену касса спрашивает до медиа. Считает её бот — сервер только кладёт запрос в
    таблицу обмена и отдаёт ответ, сам он прайс не читает.

    Новый запрос обязан стирать прежний ответ: иначе на экране осталась бы цена от старых
    данных (сняли галочку «SIM-лоток» — строка прайса уже другая)."""
    from sqlalchemy import create_engine, text as sqltext
    from pintel_server.services import ocenka_import, points as points_service

    monkeypatch.setattr(points_service, "магазины_оценки",
                        lambda: [{"id": 14, "litera": "U", "shop_name": "16/38 Pintel"}])
    db = SessionLocal()
    points_service.синхронизировать(db)
    токен = db.get(Point, 14).token
    db.close()
    k = TestClient(app)
    H = {"X-Kiosk-Token": токен, "X-Kiosk-Machine": "KASSA-14"}
    посылка = {"версия": 1, "код": "ABCD12", "запрос_цены": "q1",
               "сделка": {"model": "iPhone 13", "ddr": 128}}

    движок = create_engine(f"sqlite:///{tmp_path}/ocenka_quote.db", future=True)
    with движок.begin() as conn:
        conn.execute(sqltext(
            "CREATE TABLE kiosk_media (code TEXT, user_id INTEGER, photos TEXT, video TEXT, "
            "done INTEGER, device_id INTEGER, parcel TEXT, parcel_at TEXT, parcel_error TEXT, "
            "quote_request TEXT, quote_at TEXT, quote TEXT, media_asked TEXT)"))
        conn.execute(sqltext("CREATE TABLE users (id INTEGER, first_name TEXT, last_name TEXT)"))
        conn.execute(sqltext("INSERT INTO users VALUES (5, 'Асылбек', 'Нурланов')"))
    monkeypatch.setattr(ocenka_import, "_ocenka_engine", lambda: движок)

    # QR ещё не сканировали: спросить цену не у кого, и это сказано словами
    нет = k.post("/api/kiosk/media/ABCD12/quote", headers=H, json={"посылка": посылка}).json()
    assert нет["принято"] is False and "не привязана" in нет["почему"]
    assert k.get("/api/kiosk/media/ABCD12", headers=H).json()["сотрудник"] == ""

    # отсканировали — строку завёл бот; касса видит имя, без фамилии целиком
    with движок.begin() as conn:
        conn.execute(sqltext("INSERT INTO kiosk_media (code, user_id) VALUES ('ABCD12', 5)"))
    привязан = k.get("/api/kiosk/media/ABCD12", headers=H).json()
    assert привязан["начали"] is True and привязан["сотрудник"] == "Асылбек Н."
    assert привязан["оценка"] is None and привязан["цену_считают"] is False

    да = k.post("/api/kiosk/media/ABCD12/quote", headers=H, json={"посылка": посылка}).json()
    assert да == {"принято": True}
    ждём = k.get("/api/kiosk/media/ABCD12", headers=H).json()
    assert ждём["цену_считают"] is True and ждём["оценка"] is None

    # бот ответил: забрал запрос и положил цену
    with движок.begin() as conn:
        conn.execute(sqltext(
            "UPDATE kiosk_media SET quote_request = NULL, "
            "quote = '{\"цена\": 185000, \"почему\": \"\", \"запрос\": \"q1\"}'"))
    ответ = k.get("/api/kiosk/media/ABCD12", headers=H).json()
    assert ответ["оценка"] == {"цена": 185000, "почему": "", "запрос": "q1"}
    assert ответ["цену_считают"] is False

    # данные на кассе поменяли — новый запрос стирает прежнюю цену
    k.post("/api/kiosk/media/ABCD12/quote", headers=H,
           json={"посылка": {**посылка, "запрос_цены": "q2"}})
    assert k.get("/api/kiosk/media/ABCD12", headers=H).json()["оценка"] is None

    # автоцены нет — причина доезжает словами, а не нулём
    with движок.begin() as conn:
        conn.execute(sqltext(
            "UPDATE kiosk_media SET quote_request = NULL, media_asked = '2026-11-12', "
            "quote = '{\"цена\": null, \"почему\": \"аппарат был в ремонте\", \"запрос\": \"q2\"}'"))
    без = k.get("/api/kiosk/media/ABCD12", headers=H).json()
    assert без["оценка"] == {"цена": None, "почему": "аппарат был в ремонте", "запрос": "q2"}
    assert без["медиа_просили"] is True

    # чужой код в запросе не принимаем
    чужой = k.post("/api/kiosk/media/ABCD12/quote", headers=H,
                   json={"посылка": {**посылка, "код": "ZZZZ99"}}).json()
    assert чужой["принято"] is False and "код" in чужой["почему"]

    # бот на сервере ещё прежний (колонок нет) — отказ словами, касса обойдётся без цены
    старая = create_engine(f"sqlite:///{tmp_path}/ocenka_quote_old.db", future=True)
    with старая.begin() as conn:
        conn.execute(sqltext("CREATE TABLE kiosk_media (code TEXT, photos TEXT, video TEXT, "
                             "done INTEGER, device_id INTEGER)"))
        conn.execute(sqltext("INSERT INTO kiosk_media (code) VALUES ('ABCD12')"))
    monkeypatch.setattr(ocenka_import, "_ocenka_engine", lambda: старая)
    отказ = k.post("/api/kiosk/media/ABCD12/quote", headers=H, json={"посылка": посылка}).json()
    assert отказ["принято"] is False and "не умеет" in отказ["почему"]
    # и состояние по старой базе читается как прежде: новых полей нет, но ничего не падает
    по_старой = k.get("/api/kiosk/media/ABCD12", headers=H).json()
    assert по_старой["известно"] is True and по_старой["оценка"] is None

    assert k.post("/api/kiosk/media/ABCD12/quote", headers={"X-Kiosk-Token": "pk_wrong"},
                  json={"посылка": посылка}).status_code == 401


def test_istoriya_telefona_po_imei(app, monkeypatch):
    """Киоск спрашивает историю по IMEI и получает три списка плюс «почему».

    Молчащий источник обязан быть назван: пустая история и неотвеченный запрос — для
    сотрудника разные вещи, и во втором случае он идёт смотреть руками."""
    from pintel_server.services import history as history_service
    # токен задаём явно: помощник выводит его из имени, а у всех «Точка-…» начало одно
    H = точка("Точка-История", токен="pk_istoria")
    k = TestClient(app)

    # оба источника выключены: ответ пустой, но причины названы
    monkeypatch.setattr(history_service.settings, "ocenka_db_url", "")
    monkeypatch.setattr(history_service.settings, "requests_sheet_url", "")
    history_service._кэш.update({"когда": None, "по_имеи": {}, "строк": 0, "беда": ""})
    r = k.get("/api/kiosk/history", params={"imei": "351234560000019"}, headers=H)
    assert r.status_code == 200
    тело = r.json()
    assert тело["есть"] is False and len(тело["почему"]) == 2
    assert тело["оценки"] == [] and тело["заявки"] == [] and тело["наши"] == []

    # IMEI не прочитался — так и говорим, а не «ничего не нашли»
    тело = k.get("/api/kiosk/history", headers=H).json()
    assert "IMEI" in тело["почему"][0]

    # без токена точки история не отдаётся: это данные о клиентах и ценах
    assert k.get("/api/kiosk/history", params={"imei": "351234560000019"}).status_code in (401, 403)
