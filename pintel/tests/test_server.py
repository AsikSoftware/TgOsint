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
from pintel_server.models import AuditLog, Device, Evaluation, Kiosk, LoginEvent, User, ROLE_ADMIN, ROLE_CASHIER, ROLE_SENIOR
from pintel_server.auth import hash_password
from pintel_server.services import price as price_service
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
    r = admin.post("/settings/kiosks", data={"name": "Киоск-1", "point_id": "1"})
    token = re.search(r"t=(pk_[A-Za-z0-9_\-]+)", loc(r)).group(1)
    assert admin.get(f"/settings?t={token}").status_code == 200

    k = TestClient(app, follow_redirects=False)
    assert k.get("/api/kiosk/config").status_code == 401
    H = {"X-Kiosk-Token": token}
    cfg = k.get("/api/kiosk/config", headers=H).json()
    assert cfg["киоск"] == "Киоск-1" and cfg["точка"] == "Алматы-1" and cfg["прайс_версия"] is None
    assert k.get("/api/kiosk/price", headers=H).status_code == 404

    # прайс: подменяем Google Таблицу
    fake_grid = {"база": {"iPhone13,2": {64: 80000}}, "сетка_износа": {}, "источник": "api", "моделей": 1, "позиций": 1, "не_распознано": []}
    monkeypatch.setattr(price_service.gsheet, "fetch_grid", lambda url=None, models=None: fake_grid)
    r = admin.post("/settings/price/refresh")
    assert r.status_code == 303 and "Прайс обновлён" in loc(r)
    p = k.get("/api/kiosk/price", headers=H).json()
    assert p["версия"] >= 1 and p["сетка"]["моделей"] == 1

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
    assert ev.model_name == "iPhone 12" and ev.battery_health == 78 and ev.price_offer == 75000 and ev.apple_summary == "менялось: Экран"
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
    db = SessionLocal(); token_hash = db.scalar(select(Kiosk)).token_hash; db.close()
    admin = client_for(app, "admin", "admin123")
    r = admin.post("/settings/kiosks", data={"name": "Киоск-2", "point_id": ""})
    token = re.search(r"t=(pk_[A-Za-z0-9_\-]+)", loc(r)).group(1)
    k = TestClient(app)
    H = {"X-Kiosk-Token": token}
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
    r = admin.post("/settings/kiosks", data={"name": "Интейк-киоск", "point_id": ""})
    token = re.search(r"t=(pk_[A-Za-z0-9_\-]+)", loc(r)).group(1)
    H = {"X-Kiosk-Token": token}
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
    r = admin.post("/settings/kiosks", data={"name": "Касса-киоск", "point_id": ""})
    token = re.search(r"t=(pk_[A-Za-z0-9_\-]+)", loc(r)).group(1)
    H = {"X-Kiosk-Token": token}
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
