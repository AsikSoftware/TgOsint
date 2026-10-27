# -*- coding: utf-8 -*-
"""Касса сотрудника: вход, очередь, карточка оценки, настройки, сотрудники и журнал."""
import json
import os
import secrets
from datetime import timedelta
from urllib.parse import quote
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session as DbSession

from .. import audit
from ..auth import (authenticate, clear_cookie, create_session, current_user, hash_password, new_kiosk_token,
                    require_admin, require_senior, require_staff, revoke_session, set_cookie, COOKIE)
from ..config import settings
from ..db import get_db, now
from ..models import (MEDIA_PHOTO, MEDIA_VIDEO, ROLE_ADMIN, ROLE_CASHIER, ROLES, ST_AT_COUNTER, ST_BOUGHT,
                      ST_DECLINED, ST_IN_WORK, ST_NEW, STATUSES, AuditLog, Device, Evaluation, EvaluationMedia,
                      Kiosk, LoginEvent, Point, PriceGrid, User)
from ..services import evaluations as ev_service
from ..services import ocenka_import
from ..services import price as price_service
from ..services import references as ref_service
from ..services import sickw_service

TEMPLATES = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"))
router = APIRouter()


def _fmt_money(v):
    return f"{int(v):,}".replace(",", " ") if v not in (None, "") else "—"


def _dt(dt, fmt="%d.%m.%Y %H:%M"):
    from zoneinfo import ZoneInfo
    return dt.astimezone(ZoneInfo(settings.tz)).strftime(fmt) if dt else ""


TEMPLATES.env.filters["money"] = _fmt_money
TEMPLATES.env.filters["dt"] = _dt
TEMPLATES.env.filters["time"] = ev_service.local_time
TEMPLATES.env.globals.update(ROLES=ROLES, STATUSES=STATUSES, settings=settings,
                             PARTS_STAFF=ev_service.PARTS_STAFF, PART_STATES=ev_service.PART_STATES)


def render(request, name, user=None, **ctx):
    ctx.update({"request": request, "user": user, "flash": request.query_params.get("m")})
    return TEMPLATES.TemplateResponse(request, name, ctx)


# ---------- вход ----------

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user=Depends(current_user)):
    if user:
        return RedirectResponse("/queue", 303)
    return render(request, "login.html", error=request.query_params.get("e"))


@router.post("/login")
def login(request: Request, login: str = Form(...), password: str = Form(...), db: DbSession = Depends(get_db)):
    user = authenticate(db, login, password, request)
    if not user:
        return RedirectResponse("/login?e=1", 303)
    token = create_session(db, user, request)
    audit.log(db, user, "login", f"Вход в систему", details={"ip": request.client.host if request.client else None})
    db.commit()
    resp = RedirectResponse("/queue", 303)
    set_cookie(resp, token)
    return resp


@router.post("/logout")
def logout(request: Request, db: DbSession = Depends(get_db), user=Depends(current_user)):
    revoke_session(db, request.cookies.get(COOKIE))
    if user:
        audit.log(db, user, "logout", "Выход из системы")
        db.commit()
    resp = RedirectResponse("/login", 303)
    clear_cookie(resp)
    return resp


@router.get("/", response_class=HTMLResponse)
def root(user=Depends(current_user)):
    return RedirectResponse("/queue" if user else "/login", 303)


# ---------- очередь ----------

@router.get("/queue", response_class=HTMLResponse)
def queue(request: Request, q: str = "", period: str = "today", user: User = Depends(require_staff),
          db: DbSession = Depends(get_db)):
    day = ev_service.local_day()
    stmt = select(Evaluation).order_by(desc(Evaluation.created_at))
    if q.strip():
        s = f"%{q.strip()}%"
        stmt = stmt.where(or_(Evaluation.serial.ilike(s), Evaluation.imei.ilike(s), Evaluation.model_name.ilike(s),
                              Evaluation.number == (int(q) if q.strip().isdigit() else -1)))
        stmt = stmt.limit(200)
    elif period == "today":
        stmt = stmt.where(Evaluation.day == day)
    elif period == "week":
        stmt = stmt.where(Evaluation.created_at >= now() - timedelta(days=7)).limit(500)
    else:
        stmt = stmt.limit(500)
    if user.role != ROLE_ADMIN and user.point_id:
        stmt = stmt.where(or_(Evaluation.point_id == user.point_id, Evaluation.point_id.is_(None)))
    rows = db.scalars(stmt).all()
    kiosks = db.scalars(select(Kiosk).where(Kiosk.is_active == True)).all()  # noqa: E712
    grid = price_service.current(db)
    return render(request, "queue.html", user, rows=rows, stats=ev_service.day_stats(db, day, None if user.role == ROLE_ADMIN else user.point_id),
                  q=q, period=period, kiosks=kiosks, grid=grid, day=day, now=now())


# ---------- карточка оценки ----------

def _get_eval(db, ev_id) -> Evaluation:
    ev = db.get(Evaluation, ev_id)
    if not ev:
        raise HTTPException(404, "оценка не найдена")
    return ev


@router.get("/deal/{ev_id}", response_class=HTMLResponse)
def deal(request: Request, ev_id: int, user: User = Depends(require_staff), db: DbSession = Depends(get_db)):
    ev = _get_eval(db, ev_id)
    history = db.scalars(select(Evaluation).where(Evaluation.serial == ev.serial, Evaluation.id != ev.id)
                         .order_by(desc(Evaluation.created_at))).all() if ev.serial else []
    log = db.scalars(select(AuditLog).where(AuditLog.entity == "evaluation", AuditLog.entity_id == ev.id)
                     .order_by(desc(AuditLog.at))).all()
    ev_service.ensure_media_token(db, ev)
    return render(request, "deal.html", user, ev=ev, rep=ev.report or {}, history=history, log=log,
                  ocenka_staff=ocenka_import.staff_list(), media_link=ev_service.media_url(ev),
                  parts=ev_service.parts_check(ev), error=request.query_params.get("e"))


@router.get("/deal/{ev_id}/state")
def deal_state(ev_id: int, user: User = Depends(require_staff), db: DbSession = Depends(get_db)):
    """Короткое состояние карточки: карточка опрашивает его, пока ждём, что на телефоне
    откроют «Детали и обслуживание». Как только журнал Apple пришёл с киоска — страница
    перезагружается сама, и сотруднику не нужно ничего переписывать руками."""
    ev = _get_eval(db, ev_id)
    pv = (ev.report or {}).get("детали_вердикт") or {}
    pc = ev_service.parts_check(ev)
    return {"ключ": f"{pv.get('итог')}|{(ev.report or {}).get('apple_история_статус')}|"
                    f"{len(ev.media)}|{bool(ev.staff_parts)}|{ev.ocenka_device_id}",
            "детали": pv.get("итог"), "apple": (ev.report or {}).get("apple_история_статус"),
            "нужна_сверка": pc["нужна_сверка"]}


@router.post("/deal/{ev_id}/parts")
def deal_parts(ev_id: int, Battery: str = Form(""), Display: str = Form(""), Camera: str = Form(""),
               FaceID: str = Form(""), BackGlass: str = Form(""), LogicBoard: str = Form(""),
               FrontCamera: str = Form(""), note: str = Form(""),
               user: User = Depends(require_staff), db: DbSession = Depends(get_db)):
    """Сверка с экраном телефона: что показывает «Детали и обслуживание». Обязательна,
    когда автоматика не получила подтверждения Apple."""
    ev = _get_eval(db, ev_id)
    if ev.ocenka_device_id:
        return RedirectResponse(f"/deal/{ev_id}?e=Сделка уже отправлена в Оценку — сверку не меняем", 303)
    ev_service.set_staff_parts(db, user, ev, {"Battery": Battery, "Display": Display, "Camera": Camera,
                                              "FaceID": FaceID, "BackGlass": BackGlass,
                                              "LogicBoard": LogicBoard, "FrontCamera": FrontCamera}, note)
    return RedirectResponse(f"/deal/{ev_id}?m=Сверка деталей сохранена", 303)


@router.post("/deal/{ev_id}/take")
def deal_take(ev_id: int, user: User = Depends(require_staff), db: DbSession = Depends(get_db)):
    ev_service.take(db, user, _get_eval(db, ev_id))
    return RedirectResponse(f"/deal/{ev_id}", 303)


@router.get("/media/{media_id}")
def media_file(media_id: int, user: User = Depends(require_staff), db: DbSession = Depends(get_db)):
    """Отдать загруженное фото/видео сотруднику в кассе."""
    m = db.get(EvaluationMedia, media_id)
    if not m:
        raise HTTPException(404, "файл не найден")
    path = os.path.join(settings.media_dir, m.filename)
    if not os.path.isfile(path):
        raise HTTPException(404, "файл отсутствует на диске")
    return FileResponse(path, media_type=m.content_type or "application/octet-stream")


@router.post("/deal/{ev_id}/import_ocenka")
def deal_import_ocenka(ev_id: int, panic_full: Optional[str] = Form(None),
                       ocenka_user_id: Optional[str] = Form(None),
                       user: User = Depends(require_staff), db: DbSession = Depends(get_db)):
    """Сотрудник отправляет готовую сделку в Pintel Оценку. panic full и «кто провёл»
    (оценщик из списка сотрудников Оценки) задаёт он же здесь."""
    ev = _get_eval(db, ev_id)
    ev.panic_full = bool(panic_full)
    db.commit()
    gid = int(ocenka_user_id) if (ocenka_user_id or "").strip().isdigit() else None
    try:
        res = ocenka_import.import_evaluation(db, ev, user_grade_id=gid)
    except ocenka_import.ImportError_ as e:
        return RedirectResponse(f"/deal/{ev_id}?e={e}", 303)
    except Exception as e:                                       # noqa: BLE001
        return RedirectResponse(f"/deal/{ev_id}?e=Оценка: {e}", 303)
    audit.log(db, user, "evaluation.ocenka_import",
              f"Оценка {ev_service.label(ev)} → сделка Оценки №{res.get('device_id')}",
              entity="evaluation", entity_id=ev.id, details=res)
    db.commit()                                              # audit.log только добавляет запись
    return RedirectResponse(f"/deal/{ev_id}?m=Отправлено в Оценку №{res.get('device_id')}", 303)


@router.post("/deal/{ev_id}/decide")
def deal_decide(ev_id: int, kind: str = Form(...), final_price: str = Form(""), note: str = Form(""),
                deal_kind: str = Form("buyout"), scratches: Optional[str] = Form(None), dents: Optional[str] = Form(None),
                back_glass: Optional[str] = Form(None), fmi_off: Optional[str] = Form(None),
                user: User = Depends(require_staff), db: DbSession = Depends(get_db)):
    ev = _get_eval(db, ev_id)
    price = int(final_price.replace(" ", "").replace(" ", "")) if final_price.strip() else None
    inspection = {"царапины_экрана": bool(scratches), "сколы_корпуса": bool(dents),
                  "трещина_заднего_стекла": bool(back_glass), "найти_iphone_выключен": bool(fmi_off)}
    try:
        ev_service.decide(db, user, ev, kind, price, note, inspection, deal_kind)
    except ev_service.DecisionError as e:
        return RedirectResponse(f"/deal/{ev_id}?e={e}", 303)
    return RedirectResponse(f"/deal/{ev_id}?m=Решение записано", 303)


# ---------- публичный отчёт клиента (QR с талона) ----------

@router.get("/r/{token}", response_class=HTMLResponse)
def public_report(request: Request, token: str, db: DbSession = Depends(get_db)):
    ev = db.scalar(select(Evaluation).where(Evaluation.public_token == token))
    if not ev:
        raise HTTPException(404, "отчёт не найден")
    return render(request, "public_report.html", None, ev=ev, rep=ev.report or {})


# ---------- данные клиента и фото/видео: вносит сотрудник в кассе ----------

_PHOTO_EXT = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif")
_VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".avi", ".3gp")


def _media_kind(content_type: str | None, filename: str) -> str | None:
    ct = (content_type or "").lower()
    name = (filename or "").lower()
    if ct.startswith("video") or name.endswith(_VIDEO_EXT):
        return MEDIA_VIDEO
    if ct.startswith("image") or name.endswith(_PHOTO_EXT):
        return MEDIA_PHOTO
    return None


def _tri(v):
    return True if v == "yes" else (False if v == "no" else None)


async def _store_media(db, ev: Evaluation, files: list[UploadFile]) -> int:
    """Сохранить присланные фото/видео в media_dir с учётом лимитов. → сколько принято."""
    os.makedirs(settings.media_dir, exist_ok=True)
    limit = settings.media_max_mb * 1024 * 1024
    have, taken = len(ev.media), 0
    for up in files:
        if have >= settings.media_max_files:
            break
        kind = _media_kind(up.content_type, up.filename or "")
        if not kind:
            continue
        data = await up.read()
        if not data or len(data) > limit:
            continue
        ext = os.path.splitext(up.filename or "")[1].lower()[:8] or (".mp4" if kind == MEDIA_VIDEO else ".jpg")
        fname = f"{ev.id}_{secrets.token_hex(8)}{ext}"
        with open(os.path.join(settings.media_dir, fname), "wb") as fh:
            fh.write(data)
        ev_service.add_media(db, ev, kind, fname, up.content_type, len(data))
        have += 1
        taken += 1
    return taken


def _qr_svg(text: str, module: int = 6) -> str:
    """QR-код как SVG: сотрудник сканирует его своим телефоном прямо с экрана кассы."""
    import qrcode
    q = qrcode.QRCode(border=2, box_size=1)
    q.add_data(text)
    q.make(fit=True)
    m = q.get_matrix()
    size = len(m) * module
    d = "".join(f"M{x * module} {y * module}h{module}v{module}h-{module}z"
                for y, row in enumerate(m) for x, v in enumerate(row) if v)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
            f'shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/><path d="{d}" fill="#0C1A2E"/></svg>')


@router.post("/deal/{ev_id}/client")
def deal_client(ev_id: int, client_name: str = Form(""), client_phone: str = Form(""),
                has_box: Optional[str] = Form(None), has_cord: Optional[str] = Form(None),
                user: User = Depends(require_staff), db: DbSession = Depends(get_db)):
    """Сотрудник записывает имя и телефон клиента, коробку/шнур. Номер заявки выдаётся здесь —
    только когда есть имя и телефон; киоск показывает его клиенту сам."""
    ev = _get_eval(db, ev_id)
    if ev.ocenka_device_id:
        return RedirectResponse(f"/deal/{ev_id}?e=Сделка уже отправлена в Оценку — данные не меняем", 303)
    ev_service.set_client_details(db, user, ev, name=client_name, phone=client_phone,
                                  box=_tri(has_box), cord=_tri(has_cord))
    msg = (f"Данные клиента сохранены, заявке присвоен №{ev.number}" if ev.number
           else "Данные сохранены. Номер заявки будет выдан, когда указаны имя и телефон клиента")
    return RedirectResponse(f"/deal/{ev_id}?m={msg}", 303)


@router.post("/deal/{ev_id}/media")
async def deal_media(ev_id: int, files: list[UploadFile] = File(default=[]),
                     user: User = Depends(require_staff), db: DbSession = Depends(get_db)):
    """Фото/видео телефона с компьютера кассы."""
    ev = _get_eval(db, ev_id)
    if ev.ocenka_device_id:
        return RedirectResponse(f"/deal/{ev_id}?e=Сделка уже отправлена в Оценку — файлы не принимаем", 303)
    n = await _store_media(db, ev, files)
    audit.log(db, user, "evaluation.media", f"Загружено файлов к заявке {ev_service.label(ev)}: {n}",
              entity="evaluation", entity_id=ev.id)
    db.commit()
    return RedirectResponse(f"/deal/{ev_id}?m=Загружено файлов: {n}", 303)


@router.get("/deal/{ev_id}/media_qr.svg")
def deal_media_qr(ev_id: int, user: User = Depends(require_staff), db: DbSession = Depends(get_db)):
    """QR на временную ссылку /m/<код>: сотрудник сканирует своим телефоном и снимает фото/видео."""
    ev = _get_eval(db, ev_id)
    ev_service.ensure_media_token(db, ev)
    return Response(_qr_svg(ev_service.media_url(ev)), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


# ---------- временная ссылка для телефона сотрудника: снять фото/видео ----------

@router.get("/m/{token}", response_class=HTMLResponse)
def media_page(request: Request, token: str, db: DbSession = Depends(get_db)):
    ev = db.scalar(select(Evaluation).where(Evaluation.media_token == token))
    if not ev:
        raise HTTPException(404, "ссылка недействительна")
    return render(request, "media.html", None, ev=ev, media=ev_service.media_list(ev),
                  imported=bool(ev.ocenka_device_id), max_files=settings.media_max_files,
                  max_mb=settings.media_max_mb)


@router.post("/m/{token}")
async def media_receive(request: Request, token: str, db: DbSession = Depends(get_db),
                        files: list[UploadFile] = File(default=[])):
    ev = db.scalar(select(Evaluation).where(Evaluation.media_token == token))
    if not ev:
        raise HTTPException(404, "ссылка недействительна")
    if ev.ocenka_device_id:
        return RedirectResponse(f"/m/{token}?m=imported", 303)
    n = await _store_media(db, ev, files)
    audit.log(db, None, "evaluation.media",
              f"С телефона сотрудника загружено файлов к заявке {ev_service.label(ev)}: {n}",
              entity="evaluation", entity_id=ev.id)
    db.commit()
    return RedirectResponse(f"/m/{token}?m=ok", 303)


# ---------- настройки ----------

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: User = Depends(require_senior), db: DbSession = Depends(get_db)):
    grid = price_service.current(db)
    kiosks = db.scalars(select(Kiosk).order_by(Kiosk.name)).all()
    points = db.scalars(select(Point).order_by(Point.name)).all()
    return render(request, "settings.html", user, grid=grid, kiosks=kiosks, points=points,
                  sickw_key_set=bool(settings.sickw_key), gservice_set=os.path.isfile(settings.gservice_json),
                  error=request.query_params.get("e"), new_token=request.query_params.get("t"),
                  balance=request.query_params.get("b"), now=now())


# ---------- эталоны: учим проверку на живых аппаратах ----------

@router.get("/эталоны", response_class=HTMLResponse)
def references_page(request: Request, user: User = Depends(require_senior), db: DbSession = Depends(get_db)):
    """Каждый проверенный телефон — готовый эталон: слепок с сырым журналом Apple уже
    на сервере, сверка сотрудника — правда с экрана. Здесь видно, что из этого ценно."""
    rows = ref_service.rows(db)
    новых = len([r for r in rows if not r["выгружен"]])
    # по каким iOS и каким форматам журнала у нас уже есть аппараты — так видно, где дыра
    срез = {}
    for r in rows:
        ключ = (r["ios"], r["формат"])
        срез[ключ] = срез.get(ключ, 0) + 1
    срез = sorted(((f"iOS {i}", f, n) for (i, f), n in срез.items()), key=lambda t: (-t[2], t[0]))
    return render(request, "references.html", user, rows=rows, новых=новых, срез=срез,
                  готово=len(ref_service.pick(db)), важность=ref_service.ВАЖНОСТЬ,
                  flash_=request.query_params.get("m"))


@router.post("/эталоны/выгрузка")
def references_export(user: User = Depends(require_senior), db: DbSession = Depends(get_db),
                      all_: str = Form("", alias="all")):
    """Один файл со всеми отобранными эталонами и сводкой — его и отправляют разработчику."""
    name, data, взято = ref_service.export(db, user, only_new=not all_)
    if not взято:
        return RedirectResponse("/эталоны?m=Новых аппаратов для выгрузки нет", 303)
    # имя файла русское: в заголовке только ASCII, настоящее имя — по RFC 5987
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=\"pintel-references.zip\"; "
                                                    "filename*=UTF-8''" + quote(name),
                             "Cache-Control": "no-store"})


@router.post("/settings/price/refresh")
def settings_price_refresh(user: User = Depends(require_senior), db: DbSession = Depends(get_db)):
    try:
        row = price_service.refresh(db, user)
    except Exception as e:                                       # noqa: BLE001
        return RedirectResponse(f"/settings?e={str(e)[:300]}", 303)
    return RedirectResponse(f"/settings?m=Прайс обновлён: {row.models_count} моделей, {row.positions_count} позиций", 303)


@router.post("/settings/sickw/balance")
def settings_sickw_balance(user: User = Depends(require_senior)):
    try:
        b = sickw_service.balance()
    except Exception as e:                                       # noqa: BLE001
        return RedirectResponse(f"/settings?e={str(e)[:300]}", 303)
    return RedirectResponse(f"/settings?b={b.get('balance', b)}", 303)


@router.post("/settings/points")
def settings_point_create(name: str = Form(...), city: str = Form(""), user: User = Depends(require_admin),
                          db: DbSession = Depends(get_db)):
    if db.scalar(select(Point).where(Point.name == name.strip())):
        return RedirectResponse("/settings?e=Точка с таким названием уже есть", 303)
    p = Point(name=name.strip()[:80], city=city.strip()[:80] or None)
    db.add(p)
    audit.log(db, user, "point.create", f"Добавлена точка «{p.name}»", entity="point")
    db.commit()
    return RedirectResponse("/settings?m=Точка добавлена", 303)


@router.post("/settings/kiosks")
def settings_kiosk_create(name: str = Form(...), point_id: str = Form(""), user: User = Depends(require_admin),
                          db: DbSession = Depends(get_db)):
    if db.scalar(select(Kiosk).where(Kiosk.name == name.strip())):
        return RedirectResponse("/settings?e=Киоск с таким именем уже есть", 303)
    token, h = new_kiosk_token()
    k = Kiosk(name=name.strip()[:80], point_id=int(point_id) if point_id else None, token_hash=h)
    db.add(k)
    db.flush()
    audit.log(db, user, "kiosk.create", f"Создан киоск «{k.name}», выдан токен", entity="kiosk", entity_id=k.id)
    db.commit()
    return RedirectResponse(f"/settings?t={token}&m=Киоск создан. Токен показывается один раз", 303)


@router.post("/settings/kiosks/{kiosk_id}/toggle")
def settings_kiosk_toggle(kiosk_id: int, user: User = Depends(require_admin), db: DbSession = Depends(get_db)):
    k = db.get(Kiosk, kiosk_id)
    if not k:
        raise HTTPException(404)
    k.is_active = not k.is_active
    audit.log(db, user, "kiosk.toggle", f"Киоск «{k.name}» {'включён' if k.is_active else 'отключён'}", entity="kiosk", entity_id=k.id)
    db.commit()
    return RedirectResponse("/settings", 303)


# ---------- сотрудники и журнал ----------

@router.get("/employees", response_class=HTMLResponse)
def employees(request: Request, show: str = "today", user: User = Depends(require_admin), db: DbSession = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.is_active.desc(), User.name)).all()
    points = db.scalars(select(Point).order_by(Point.name)).all()
    since = now() - timedelta(days=1 if show == "today" else 7)
    if show == "logins":
        events = db.scalars(select(LoginEvent).order_by(desc(LoginEvent.at)).limit(300)).all()
        log = []
    else:
        log = db.scalars(select(AuditLog).where(AuditLog.at >= since).order_by(desc(AuditLog.at)).limit(400)).all()
        events = []
    day = ev_service.local_day()
    month = day[:7]
    stats = {}
    for u in users:
        rows = db.scalars(select(Evaluation).where(Evaluation.decided_by_id == u.id, Evaluation.status == ST_BOUGHT,
                                                   Evaluation.day >= month + "-01")).all()
        stats[u.id] = {"n": len(rows), "sum": sum(r.final_price or 0 for r in rows)}
    online = {s.user_id: s for s in db.scalars(select(__import__("pintel_server.models", fromlist=["Session"]).Session)
                                                .where(__import__("pintel_server.models", fromlist=["Session"]).Session.revoked == False,  # noqa: E712
                                                       __import__("pintel_server.models", fromlist=["Session"]).Session.last_seen_at >= now() - timedelta(minutes=15))).all()}
    return render(request, "employees.html", user, users=users, points=points, log=log, events=events, show=show,
                  stats=stats, online=online, error=request.query_params.get("e"))


@router.post("/employees")
def employee_create(login: str = Form(...), name: str = Form(...), role: str = Form(ROLE_CASHIER),
                    password: str = Form(...), point_id: str = Form(""), user: User = Depends(require_admin),
                    db: DbSession = Depends(get_db)):
    login = login.strip().lower()
    if not login or not name.strip() or len(password) < 6:
        return RedirectResponse("/employees?e=Логин, имя и пароль не короче 6 знаков обязательны", 303)
    if role not in ROLES:
        return RedirectResponse("/employees?e=Неизвестная роль", 303)
    if db.scalar(select(User).where(User.login == login)):
        return RedirectResponse("/employees?e=Такой логин уже есть", 303)
    u = User(login=login[:64], name=name.strip()[:120], role=role, password_hash=hash_password(password),
             point_id=int(point_id) if point_id else None)
    db.add(u)
    db.flush()
    audit.log(db, user, "user.create", f"Добавлен сотрудник {u.name} ({ROLES[role]})", entity="user", entity_id=u.id)
    db.commit()
    return RedirectResponse("/employees?m=Сотрудник добавлен", 303)


@router.post("/employees/{uid}")
def employee_update(uid: int, name: str = Form(...), role: str = Form(...), point_id: str = Form(""),
                    is_active: Optional[str] = Form(None), password: str = Form(""),
                    user: User = Depends(require_admin), db: DbSession = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    if role not in ROLES:
        return RedirectResponse("/employees?e=Неизвестная роль", 303)
    if u.id == user.id and (role != ROLE_ADMIN or not is_active):
        return RedirectResponse("/employees?e=Нельзя снять права или отключить самого себя", 303)
    changes = []
    if u.name != name.strip():
        changes.append(f"имя {u.name} → {name.strip()}")
    if u.role != role:
        changes.append(f"роль {ROLES[u.role]} → {ROLES[role]}")
    new_active = bool(is_active)
    if u.is_active != new_active:
        changes.append("доступ " + ("включён" if new_active else "отключён"))
    if password:
        if len(password) < 6:
            return RedirectResponse("/employees?e=Пароль не короче 6 знаков", 303)
        u.password_hash = hash_password(password)
        changes.append("пароль сменён")
    u.name, u.role, u.is_active = name.strip()[:120], role, new_active
    u.point_id = int(point_id) if point_id else None
    if not new_active:
        from ..models import Session as S
        for s in db.scalars(select(S).where(S.user_id == u.id, S.revoked == False)).all():  # noqa: E712
            s.revoked = True
    audit.log(db, user, "user.update", f"Изменён сотрудник {u.name}: " + ("; ".join(changes) or "без изменений"),
              entity="user", entity_id=u.id)
    db.commit()
    return RedirectResponse("/employees?m=Сохранено", 303)
