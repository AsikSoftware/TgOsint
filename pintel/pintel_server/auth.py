# -*- coding: utf-8 -*-
"""Учётные записи и доступ. Единственное место, где решается «кто ты».

Сейчас: логин + пароль (scrypt из стандартной библиотеки, без внешних
зависимостей), серверные сессии, cookie с случайным токеном. Если тип
входа поменяется (одноразовые коды, SSO), меняется этот модуль, а
зависимости `current_user` / `require_role` остаются теми же.
"""
import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .config import settings
from .db import get_db, now
from .models import ROLE_ADMIN, ROLE_CASHIER, ROLE_SENIOR, Kiosk, LoginEvent, Session, User

COOKIE = "pintel_session"
KIOSK_HEADER = "x-kiosk-token"
_N, _R, _P = 2 ** 14, 8, 1


# ---------- пароли ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(h).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt),
                              n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:                                   # noqa: BLE001
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------- вход / сессии ----------

class LoginRequired(Exception):
    """Страница требует входа — обработчик в main.py перенаправит на /login."""


def _client(request: Request):
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else None)
    return ip, (request.headers.get("user-agent") or "")[:255]


def authenticate(db: DbSession, login: str, password: str, request: Optional[Request] = None):
    """→ User или None. Каждая попытка пишется в login_events."""
    ip, ua = _client(request) if request else (None, None)
    user = db.scalar(select(User).where(User.login == login.strip().lower()))
    ok, reason = False, None
    if not user:
        reason = "нет такого логина"
    elif not user.is_active:
        reason = "доступ отключён"
    elif not verify_password(password, user.password_hash):
        reason = "неверный пароль"
    else:
        ok = True
    db.add(LoginEvent(login=login.strip().lower()[:64], user_id=user.id if user else None, ok=ok,
                      reason=reason, ip=ip, user_agent=ua))
    if ok:
        user.last_login_at = now()
    db.commit()
    return user if ok else None


def create_session(db: DbSession, user: User, request: Optional[Request] = None) -> str:
    token = secrets.token_urlsafe(32)
    ip, ua = _client(request) if request else (None, None)
    db.add(Session(token_hash=_hash_token(token), user_id=user.id,
                   expires_at=now() + timedelta(days=settings.session_days), ip=ip, user_agent=ua))
    db.commit()
    return token


def revoke_session(db: DbSession, token: Optional[str]):
    if not token:
        return
    s = db.scalar(select(Session).where(Session.token_hash == _hash_token(token)))
    if s:
        s.revoked = True
        db.commit()


def user_from_token(db: DbSession, token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    s = db.scalar(select(Session).where(Session.token_hash == _hash_token(token)))
    if not s or s.revoked or s.expires_at < now():
        return None
    if not s.user or not s.user.is_active:
        return None
    s.last_seen_at = now()
    db.commit()
    return s.user


def set_cookie(response, token: str):
    response.set_cookie(COOKIE, token, max_age=settings.session_days * 86400, httponly=True,
                        samesite="lax", secure=settings.secure_cookies, path="/")


def clear_cookie(response):
    response.delete_cookie(COOKIE, path="/")


# ---------- зависимости FastAPI ----------

def current_user(request: Request, db: DbSession = Depends(get_db)) -> Optional[User]:
    return user_from_token(db, request.cookies.get(COOKIE))


def require_user(user: Optional[User] = Depends(current_user)) -> User:
    if not user:
        raise LoginRequired()
    return user


def require_role(*roles):
    def dep(user: User = Depends(require_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Недостаточно прав")
        return user
    return dep


require_admin = require_role(ROLE_ADMIN)
require_senior = require_role(ROLE_ADMIN, ROLE_SENIOR)
require_staff = require_role(ROLE_ADMIN, ROLE_SENIOR, ROLE_CASHIER)


# ---------- киоски ----------

def new_kiosk_token() -> tuple[str, str]:
    """→ (токен для киоска, его хэш для базы). Токен показывается один раз."""
    token = "pk_" + secrets.token_urlsafe(24)
    return token, _hash_token(token)


def current_kiosk(request: Request, db: DbSession = Depends(get_db)) -> Kiosk:
    token = request.headers.get(KIOSK_HEADER) or ""
    k = db.scalar(select(Kiosk).where(Kiosk.token_hash == _hash_token(token))) if token else None
    if not k or not k.is_active:
        raise HTTPException(401, "Киоск не опознан: проверьте токен в kiosk.toml")
    k.last_seen_at = now()
    db.commit()
    return k
