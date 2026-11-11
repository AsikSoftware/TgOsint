# -*- coding: utf-8 -*-
"""API киоска. Авторизация — заголовок X-Kiosk-Token (токен выдаёт администратор в Настройках)."""
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .. import audit
from ..auth import current_kiosk
from ..config import settings
from ..db import get_db, now
from ..models import Evaluation, Kiosk, KioskLog, PhoneTest, Point, ReferenceBundle
from ..services import evaluations as ev_service
from ..services import history as history_service
from ..services import kiosk_settings
from ..services import references as ref_service
from ..services import ocenka_import
from ..services import points as points_service
from ..services import sickw_service

router = APIRouter(prefix="/api/kiosk", tags=["kiosk"])


class SickwIn(BaseModel):
    imei: str
    fresh: bool = False
    services: list[int] | None = None     # не по умолчанию: запечатанному нужна другая служба


class EvaluationIn(BaseModel):
    client_id: str
    report: dict
    snapshot: dict | None = None


class DecisionIn(BaseModel):
    decision: str          # sell | viewed


class UpdateIn(BaseModel):
    report: dict
    snapshot_patch: dict | None = None


class HeartbeatIn(BaseModel):
    version: str | None = None
    status: dict | None = None


def _own(db, kiosk, ev_id):
    ev = db.get(Evaluation, ev_id)
    if not ev or ev.kiosk_id != kiosk.id:
        raise HTTPException(404, "оценка не найдена")
    return ev


@router.get("/points")
def points(db: DbSession = Depends(get_db)):
    """Список точек для первой настройки программы: из него сотрудник выбирает свою.

    Без токена: выбрать точку надо ДО того, как он введён. Отдаём только то, что и так
    написано на вывеске — id (он же id магазина в Оценке), название и литеру.

    Магазины, которых в Оценке уже нет, в этот список не попадают: настраивать на них новый
    компьютер нельзя — сделка уехала бы с `shop_id`, которого у Оценки нет. Уже настроенные
    точки при этом работают: их опознаёт токен, а не этот список."""
    строки = db.scalars(select(Point).where(Point.is_active == True).order_by(Point.name))  # noqa: E712
    return {"точки": [{"id": p.id, "название": p.name, "литера": p.litera, "город": p.city}
                      for p in строки if not points_service.пропала(p)]}


@router.get("/config")
def config(kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    """Все настройки программы на точке. В её файле ничего этого больше нет.

    Имя бота Оценки и его токен тоже здесь: программа отдаёт сделку через него, а держать
    этот токен на девятнадцати компьютерах и менять его объездом — то же самое, от чего мы
    и уходим. Канал закрыт HTTPS и токеном точки.
    """
    из_базы = kiosk_settings.для_точки(db, kiosk.point)
    return {
        "киоск": kiosk.name, "точка": из_базы["point"],
        # id точки = id магазина в Оценке: программа кладёт его в посылку, и бот больше
        # не спрашивает точку у сотрудника
        "точка_id": kiosk.point_id,
        "литера": kiosk.point.litera if kiosk.point else None,
        "валюта": settings.currency,
        "sickw_ключ_есть": bool(settings.sickw_key), "время_сервера": now().isoformat(),
        "публичный_адрес": settings.public_url,
        "настройки": из_базы,
        # прежние имена: их читают сборки до 56-й, пусть не ломаются об обновление сервера
        "возврат_с": из_базы["return_seconds"], "история_apple_с": из_базы["apple_history_seconds"],
        "sickw": bool(settings.sickw_key),
    }


@router.get("/media/{code}")                   # имя в адресе латиницей: Starlette не видит
def media(code: str, kiosk: Kiosk = Depends(current_kiosk)):
    """Дошли ли до бота фото, видео и отметки диагностики по этому коду обмена.

    Касса спрашивает это, пока открыт экран сделки, и не даёт отправить оценку, пока медиа
    не собраны: раньше карточка уходила в рабочую группу без них, а отказ прилетал от бота
    минутой позже — с телефоном клиента в руках это значит начинать заново.
    """
    from ..services import ocenka_media as media_service
    return media_service.состояние(code)


class ПосылкаIn(BaseModel):
    посылка: dict


@router.post("/media/{code}/parcel")
def media_parcel(code: str, body: ПосылкаIn, kiosk: Kiosk = Depends(current_kiosk)):
    """Сделка с точки — боту, минуя чат Telegram.

    Раньше касса слала посылку файлом в чат, и бот получал её только когда кто-то нажимал
    кнопку под карточкой. Значит, сделка зависела от того, доступен ли чат, — а он
    отказывал («chat not found», «bot was blocked by the user»), и тогда сделку нельзя
    было создать вовсе. Теперь посылка ложится в таблицу обмена, бот забирает её сам.

    Отказ отдаём словами: по нему касса уходит в запасной путь — ту самую карточку
    с кнопкой, — и сотрудник не остаётся ни с чем.
    """
    from ..services import ocenka_media as media_service
    return media_service.принять(code, body.посылка)


class LogsIn(BaseModel):
    lines: list[str]


@router.post("/logs")
def logs(body: LogsIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    """Журнал программы с точки. Раньше он лежал только там, и прочитать его можно было,
    лишь приехав: теперь видно, что происходило у аппарата, когда сделка не сложилась."""
    взято = 0
    for строка in (body.lines or [])[:500]:
        текст = str(строка or "").strip()[:1000]
        if текст:
            db.add(KioskLog(point_id=kiosk.point_id, kiosk_id=kiosk.id, line=текст))
            взято += 1
    db.commit()
    return {"принято": взято}


@router.post("/reference")
async def reference_upload(file: UploadFile = File(...), name: str = Form(""),
                           kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    """Эталон с точки: обезличенный слепок, сырой журнал Apple и наш вердикт.

    Складываем файлом рядом с медиа, в базе — карточка. Повторная присылка того же имени
    не плодит копий: точка досылает всё, что у неё накопилось, и не помнит, что уже ушло."""
    # Имя эталона кириллическое («эталон_iPhone-14-Pro_iOS26.5_…zip»), а в заголовке
    # multipart такое имя не проходит: httpx кодирует заголовки в ascii и падает. Поэтому
    # настоящее имя едет отдельным полем, а файл — под служебным.
    имя = os.path.basename(name or file.filename or "")[:160]
    имя = имя.replace("/", "_").replace("\\", "_")
    if not имя.endswith(".zip"):
        raise HTTPException(400, "эталон присылают zip-файлом")
    данные = await file.read()
    if not данные or len(данные) > 5 * 1024 * 1024:
        raise HTTPException(413, "эталон пустой или слишком большой")
    if db.scalar(select(ReferenceBundle).where(ReferenceBundle.name == имя)):
        return {"принят": False, "почему": "такой эталон уже есть"}
    папка = os.path.join(settings.media_dir, "эталоны")
    os.makedirs(папка, exist_ok=True)
    with open(os.path.join(папка, имя), "wb") as fh:
        fh.write(данные)
    модель, ios, вердикт = ref_service.из_имени(имя)
    db.add(ReferenceBundle(point_id=kiosk.point_id, kiosk_id=kiosk.id, name=имя, size=len(данные),
                           model_name=модель, ios=ios, verdict=вердикт))
    db.commit()
    return {"принят": True}


@router.post("/sickw")
def sickw(body: SickwIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    try:
        r = sickw_service.lookup(db, body.imei.strip(), services=body.services or None,
                                 use_cache=not body.fresh)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(502, str(e))
    r.pop("сырые_ответы", None)
    return r


@router.post("/evaluations")
def create_evaluation(body: EvaluationIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    ev, created = ev_service.create_from_kiosk(db, kiosk, body.model_dump())
    return {"id": ev.id, "номер": ev.number, "день": ev.day, "создана": created,
            "статус": ev.status, "ссылка_отчёта": ev_service.report_url(ev),
            "ссылка_чека": ev_service.check_url(ev),
            "уже_приносили": bool(ev.device and ev.device.evaluations_count > 1)}


@router.patch("/evaluations/{ev_id}")
def update_evaluation(ev_id: int, body: UpdateIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    ev = db.get(Evaluation, ev_id)
    if not ev or ev.kiosk_id != kiosk.id:
        raise HTTPException(404, "оценка не найдена")
    ev_service.update_from_kiosk(db, kiosk, ev, body.report, body.snapshot_patch)
    return {"id": ev.id, "статус": ev.status, "apple": ev.apple_summary}


@router.post("/evaluations/{ev_id}/decision")
def client_decision(ev_id: int, body: DecisionIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    ev = db.get(Evaluation, ev_id)
    if not ev or ev.kiosk_id != kiosk.id:
        raise HTTPException(404, "оценка не найдена")
    if body.decision not in ("sell", "viewed"):
        raise HTTPException(400, "decision: sell | viewed")
    ev_service.client_decision(db, kiosk, ev, body.decision)
    return {"статус": ev.status}


@router.get("/evaluations/{ev_id}/media")
def list_media(ev_id: int, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    """Список фото/видео, загруженных сотрудником в кассе (данные клиента и медиа вносятся там)."""
    ev = _own(db, kiosk, ev_id)
    return ev_service.intake_state(ev)


@router.get("/evaluations/{ev_id}/intake")
def intake(ev_id: int, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    """Состояние заявки для киоска: номер (выдаёт сотрудник в кассе), ссылка на отчёт, медиа."""
    ev = _own(db, kiosk, ev_id)
    return ev_service.intake_state(ev)


@router.post("/evaluations/{ev_id}/import")
def import_to_ocenka(ev_id: int, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    """Отправить готовую сделку в Pintel Оценку (создаётся номер, уходит админам «Новая оценка»)."""
    ev = _own(db, kiosk, ev_id)
    try:
        res = ocenka_import.import_evaluation(db, ev)
    except ocenka_import.ImportError_ as e:
        raise HTTPException(400, str(e))
    except Exception as e:                                       # noqa: BLE001
        raise HTTPException(502, f"импорт в Оценку не удался: {e}")
    audit.log(db, None, "evaluation.ocenka_import",
              f"Оценка {ev_service.label(ev)} → сделка Оценки №{res.get('device_id')}",
              entity="evaluation", entity_id=ev.id, kiosk=kiosk, details=res)
    return {"id": ev.id, "номер_сделки": res.get("device_id"), **res}


# ---------- тест на телефоне клиента ----------

class PhoneTestIn(BaseModel):
    token: str
    eval_id: int | None = None


@router.post("/phone")
def open_phone_test(body: PhoneTestIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    """Открыть сессию теста: касса придумывает токен, сервер заводит под него строку.

    Строку создаёт только касса — поэтому на выдуманный токен с улицы результат не положить:
    такого токена в базе просто нет. В ответ — адрес страницы для QR на домене.
    """
    токен = (body.token or "").strip()[:32]
    if not токен.isalnum():
        raise HTTPException(400, "токен: только буквы и цифры")
    pt = db.scalar(select(PhoneTest).where(PhoneTest.token == токен))
    if pt is None:
        pt = PhoneTest(token=токен, kiosk_id=kiosk.id, eval_id=body.eval_id)
        db.add(pt)
    else:
        pt.kiosk_id, pt.eval_id = kiosk.id, body.eval_id or pt.eval_id
    db.commit()
    return {"токен": токен, "ссылка": f"{settings.public_url}/t/{токен}"}


@router.get("/phone/{token}")
def phone_test_result(token: str, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    """Результат теста: касса спрашивает его, пока клиент проходит тест на своём телефоне."""
    pt = db.scalar(select(PhoneTest).where(PhoneTest.token == token))
    if not pt:
        raise HTTPException(404, "проверка не найдена")
    return {"готов": pt.answered_at is not None, "результат": pt.result or {},
            "когда": pt.answered_at.isoformat() if pt.answered_at else None}


@router.get("/history")
def history(imei: str = "", imei2: str = "", ev_id: int | None = None,
            kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    """Что с этим аппаратом у нас уже было: сделки Оценки, заявки с сайта, наши проверки.

    Киоск спрашивает это, как только прочитал IMEI, и показывает сотруднику в углу экрана —
    до того, как тот назовёт цену. Источник, который не ответил, уезжает в «почему»: пустая
    история и молчащая Оценка на экране обязаны выглядеть по-разному."""
    return history_service.по_имеи(db, [imei, imei2], кроме=ev_id)


@router.post("/heartbeat")
def heartbeat(body: HeartbeatIn, kiosk: Kiosk = Depends(current_kiosk), db: DbSession = Depends(get_db)):
    kiosk.version = (body.version or kiosk.version or "")[:32]
    kiosk.status = body.status or kiosk.status
    kiosk.last_seen_at = now()
    db.commit()
    return {"ok": True, "время_сервера": now().isoformat()}
