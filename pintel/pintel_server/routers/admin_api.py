# -*- coding: utf-8 -*-
"""Выдача данных административной программе (мак).

Почему не страницы. Веб-касса отдаёт HTML сотруднику за стойкой; административная
программа — отдельное окно у владельца, и ей нужны данные, а не вёрстка.

Вход тот же, что в кассе: логин и пароль, дальше токен сессии. Токен программа шлёт
заголовком `x-admin-token` — cookie у настольной программы нет. Сессии и срок жизни общие
с кассой (`auth`), поэтому отозвать доступ можно в одном месте.

Пока здесь только ЧТЕНИЕ. Действия (обновить машину, заблокировать, править прайс) добавятся
отдельно и каждое — с записью в журнал: кто и что сделал.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session as DbSession

from .. import audit, auth
from ..db import get_db
from ..models import ROLE_ADMIN, User
from ..services import admin_data

router = APIRouter(prefix="/api/admin", tags=["admin"])

ЗАГОЛОВОК = "x-admin-token"


def админ(request: Request, db: DbSession = Depends(get_db)) -> User:
    """Кто спрашивает. Без входа и не администратору — отказ.

    Роль проверяется здесь, а не на каждом обработчике: забыть проверку в одном месте
    проще, чем в одном общем."""
    токен = request.headers.get(ЗАГОЛОВОК) or request.cookies.get(auth.COOKIE)
    пользователь = auth.user_from_token(db, токен)
    if not пользователь:
        raise HTTPException(401, "нужен вход")
    if пользователь.role != ROLE_ADMIN:
        raise HTTPException(403, "административная программа — только для администратора")
    return пользователь


@router.post("/login")
async def вход(request: Request, db: DbSession = Depends(get_db)):
    """Логин и пароль → токен. Неудачные попытки пишутся в журнал входов, как и в кассе."""
    данные = await request.json()
    логин = str((данные or {}).get("логин") or (данные or {}).get("login") or "")
    пароль = str((данные or {}).get("пароль") or (данные or {}).get("password") or "")
    пользователь = auth.authenticate(db, логин, пароль, request)
    if not пользователь:
        raise HTTPException(401, "неверный логин или пароль")
    if пользователь.role != ROLE_ADMIN:
        raise HTTPException(403, "административная программа — только для администратора")
    return {"токен": auth.create_session(db, пользователь, request),
            "имя": пользователь.name, "роль": пользователь.role}


@router.post("/logout")
def выход(request: Request, db: DbSession = Depends(get_db), _=Depends(админ)):
    auth.revoke_session(db, request.headers.get(ЗАГОЛОВОК) or request.cookies.get(auth.COOKIE))
    return {"ок": True}


@router.get("/overview")
def обзор(db: DbSession = Depends(get_db), _=Depends(админ)):
    return admin_data.обзор(db)


@router.get("/points")
def точки(db: DbSession = Depends(get_db), _=Depends(админ)):
    return {"точки": admin_data.точки(db)}


@router.get("/machines")
def компьютеры(db: DbSession = Depends(get_db), _=Depends(админ)):
    return {"компьютеры": admin_data.компьютеры(db)}


@router.get("/alerts")
def тревоги(request: Request, db: DbSession = Depends(get_db), _=Depends(админ)):
    свежая = request.query_params.get("сборка") or request.query_params.get("build") or ""
    return {"тревоги": admin_data.тревоги(db, свежая)}


@router.get("/people")
def люди(db: DbSession = Depends(get_db), _=Depends(админ)):
    return {"люди": admin_data.люди(db)}


@router.get("/funnel")
def воронка(request: Request, db: DbSession = Depends(get_db), _=Depends(админ)):
    дней = request.query_params.get("дней") or request.query_params.get("days") or "30"
    return admin_data.воронка(db, int(дней) if str(дней).isdigit() else 30)


@router.get("/references")
def эталоны(db: DbSession = Depends(get_db), _=Depends(админ)):
    return admin_data.эталоны_коротко(db)


# ---------------------------------------------------------------- остальные разделы


def _дней(request: Request, по_умолчанию: int = 30) -> int:
    значение = request.query_params.get("дней") or request.query_params.get("days") or ""
    return int(значение) if str(значение).isdigit() else по_умолчанию


@router.get("/money")
def деньги(request: Request, db: DbSession = Depends(get_db), _=Depends(админ)):
    return admin_data.деньги(db, _дней(request))


@router.get("/stock")
def товар(request: Request, db: DbSession = Depends(get_db), _=Depends(админ)):
    return admin_data.товар_на_руках(db, _дней(request, 120))


@router.get("/checks")
def проверки(request: Request, db: DbSession = Depends(get_db), _=Depends(админ)):
    return admin_data.проверки_без_сделки(db, _дней(request))


@router.get("/certificates")
def сертификаты(request: Request, db: DbSession = Depends(get_db), _=Depends(админ)):
    return admin_data.сертификаты(db, _дней(request))


@router.get("/reference-list")
def эталоны_списком(db: DbSession = Depends(get_db), _=Depends(админ)):
    return admin_data.эталоны(db)


@router.get("/phone")
def телефон(request: Request, db: DbSession = Depends(get_db), _=Depends(админ)):
    return admin_data.телефон(db, request.query_params.get("q") or "")


@router.get("/audit")
def журнал(db: DbSession = Depends(get_db), _=Depends(админ)):
    return {"журнал": admin_data.журнал(db)}


@router.get("/roles")
def роли(db: DbSession = Depends(get_db), _=Depends(админ)):
    return admin_data.роли(db)


# ---------------------------------------------------------------- чёрный список
#
# Единственное место, где программа пока ПИШЕТ. Каждая правка идёт в журнал: «кто добавил
# аппарат в чёрный список» — это разговор, который однажды случится.


@router.get("/blacklist")
def чёрный(db: DbSession = Depends(get_db), _=Depends(админ)):
    return {"записи": admin_data.чёрный_список(db)}


@router.post("/blacklist")
async def чёрный_добавить(request: Request, db: DbSession = Depends(get_db),
                          кто: User = Depends(админ)):
    данные = await request.json()
    try:
        записи = admin_data.чёрный_добавить(db, (данные or {}).get("imei"),
                                            (данные or {}).get("почему"), кто.name)
    except ValueError as беда:
        raise HTTPException(400, str(беда)) from беда
    audit.log(db, кто, "чёрный_список_добавил",
              f"добавил аппарат в чёрный список: {(данные or {}).get('почему') or 'без причины'}")
    return {"записи": записи}


@router.delete("/blacklist/{imei}")
def чёрный_убрать(imei: str, db: DbSession = Depends(get_db), кто: User = Depends(админ)):
    записи = admin_data.чёрный_убрать(db, imei)
    audit.log(db, кто, "чёрный_список_убрал", "убрал аппарат из чёрного списка")
    return {"записи": записи}


# ---------------------------------------------------------------- действия
#
# Всё, что меняет мир, живёт здесь и каждое пишется в журнал. Правило простое: через год
# спросят «кто закрыл точку в субботу» — и ответ должен быть, а не догадки.


def _действие(db, кто: User, что: str, словами: str):
    """Запись в журнал и сразу на диск: `audit.log` только добавляет строку в сессию, а
    обработчик после себя ничего не сохраняет — без этого запись пропадала бы."""
    audit.log(db, кто, что, словами)
    db.commit()


@router.post("/machines/{kiosk_id}/command")
async def команда_машине(kiosk_id: int, request: Request, db: DbSession = Depends(get_db),
                         кто: User = Depends(админ)):
    """Сейчас одна команда — «обновиться». Машина заберёт её ближайшим пульсом, раз в минуту."""
    данные = await request.json()
    команда = str((данные or {}).get("команда") or "обновиться")
    if команда not in ("обновиться",):
        raise HTTPException(400, "неизвестная команда")
    admin_data.команда_машине(db, kiosk_id, команда)
    _действие(db, кто, "команда_машине", f"велел машине {kiosk_id}: {команда}")
    return {"ок": True, "команда": команда}


@router.post("/machines/{kiosk_id}/active")
async def машина_работает(kiosk_id: int, request: Request, db: DbSession = Depends(get_db),
                          кто: User = Depends(админ)):
    данные = await request.json()
    работает = bool((данные or {}).get("работает"))
    try:
        итог = admin_data.машина_работает(db, kiosk_id, работает)
    except ValueError as беда:
        raise HTTPException(404, str(беда)) from беда
    _действие(db, кто, "машина_доступ",
              ("открыл" if работает else "закрыл") + f" машину «{итог['машина']}»")
    return итог


@router.delete("/machines/{kiosk_id}")
def машину_забыть(kiosk_id: int, db: DbSession = Depends(get_db), кто: User = Depends(админ)):
    try:
        итог = admin_data.машину_забыть(db, kiosk_id)
    except ValueError as беда:
        raise HTTPException(404, str(беда)) from беда
    _действие(db, кто, "машину_забыли", f"убрал машину «{итог['машина']}» из списка")
    return итог


@router.post("/points/{point_id}/active")
async def точка_работает(point_id: int, request: Request, db: DbSession = Depends(get_db),
                         кто: User = Depends(админ)):
    данные = await request.json()
    работает = bool((данные or {}).get("работает"))
    try:
        итог = admin_data.точка_работает(db, point_id, работает)
    except ValueError as беда:
        raise HTTPException(404, str(беда)) from беда
    _действие(db, кто, "точка_доступ",
              ("открыл" if работает else "закрыл") + f" точку «{итог['точка']}»")
    return итог


@router.post("/people/{user_id}/access")
async def доступ_человеку(user_id: int, request: Request, db: DbSession = Depends(get_db),
                          кто: User = Depends(админ)):
    данные = await request.json()
    доступ = bool((данные or {}).get("доступ"))
    if user_id == кто.id and not доступ:
        raise HTTPException(400, "себе доступ не закрывают: войти обратно будет некому")
    try:
        итог = admin_data.доступ_человеку(db, user_id, доступ)
    except ValueError as беда:
        raise HTTPException(404, str(беда)) from беда
    _действие(db, кто, "доступ_человеку",
              ("открыл" if доступ else "закрыл") + f" доступ сотруднику «{итог['сотрудник']}»")
    return итог
