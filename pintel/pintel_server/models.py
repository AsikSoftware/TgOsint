# -*- coding: utf-8 -*-
"""Таблицы. Всё, что нужно «по всем телефонам, по всем сотрудникам, по всем входам».

Оценка хранит ПОЛНЫЙ сырой слепок телефона (JSON): любой спор потом
пересчитывается из файла, а не из памяти кассира.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, TZDateTime, now

ROLE_CASHIER, ROLE_SENIOR, ROLE_ADMIN = "cashier", "senior", "admin"
ROLES = {ROLE_CASHIER: "Кассир", ROLE_SENIOR: "Старший", ROLE_ADMIN: "Администратор"}

# статусы оценки
ST_NEW, ST_VIEWED, ST_AT_COUNTER, ST_IN_WORK, ST_BOUGHT, ST_DECLINED = (
    "new", "viewed", "at_counter", "in_work", "bought", "declined")
STATUSES = {ST_NEW: "Новая", ST_VIEWED: "Клиент просто смотрел", ST_AT_COUNTER: "Клиент идёт к кассе",
            ST_IN_WORK: "В работе", ST_BOUGHT: "Выкуплен", ST_DECLINED: "Отказ"}


class Point(Base):
    __tablename__ = "points"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    city: Mapped[Optional[str]] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16), default=ROLE_CASHIER)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    point_id: Mapped[Optional[int]] = mapped_column(ForeignKey("points.id"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    point: Mapped[Optional[Point]] = relationship()

    @property
    def role_label(self):
        return ROLES.get(self.role, self.role)


class Session(Base):
    """Серверная сессия: в cookie только случайный токен, здесь — его хэш."""
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    ip: Mapped[Optional[str]] = mapped_column(String(64))
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    user: Mapped[User] = relationship()


class LoginEvent(Base):
    """Каждая попытка входа: удачная и неудачная."""
    __tablename__ = "login_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(TZDateTime, default=now, index=True)
    login: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    ok: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[Optional[str]] = mapped_column(String(80))
    ip: Mapped[Optional[str]] = mapped_column(String(64))
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))
    user: Mapped[Optional[User]] = relationship()


class AuditLog(Base):
    """Кто что сделал: сотрудник, киоск или сервер."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(TZDateTime, default=now, index=True)
    actor_type: Mapped[str] = mapped_column(String(16))        # user | kiosk | server
    actor_id: Mapped[Optional[int]] = mapped_column(Integer)
    actor_name: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[Optional[str]] = mapped_column(String(32))
    entity_id: Mapped[Optional[int]] = mapped_column(Integer)
    point_id: Mapped[Optional[int]] = mapped_column(ForeignKey("points.id"))
    text: Mapped[str] = mapped_column(Text)
    details: Mapped[Optional[dict]] = mapped_column(JSON)


class Kiosk(Base):
    __tablename__ = "kiosks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    point_id: Mapped[Optional[int]] = mapped_column(ForeignKey("points.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    version: Mapped[Optional[str]] = mapped_column(String(32))
    status: Mapped[Optional[dict]] = mapped_column(JSON)       # драйвер, последний телефон, …
    point: Mapped[Optional[Point]] = relationship()


class Device(Base):
    """Телефон как сущность: уже приносили? что было тогда?"""
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial: Mapped[str] = mapped_column(String(32), unique=True)
    imei: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    model_code: Mapped[Optional[str]] = mapped_column(String(32))
    model_name: Mapped[Optional[str]] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)
    last_seen_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)
    evaluations_count: Mapped[int] = mapped_column(Integer, default=0)


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (UniqueConstraint("client_id", name="uq_eval_client"),
                      Index("ix_eval_day_point", "day", "point_id"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64))         # идемпотентность с киоска
    number: Mapped[int] = mapped_column(Integer)               # номер талона в этот день на точке
    day: Mapped[str] = mapped_column(String(10))               # YYYY-MM-DD по местному времени
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=now, index=True)
    kiosk_id: Mapped[Optional[int]] = mapped_column(ForeignKey("kiosks.id"))
    point_id: Mapped[Optional[int]] = mapped_column(ForeignKey("points.id"))
    device_id: Mapped[Optional[int]] = mapped_column(ForeignKey("devices.id"))
    serial: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    imei: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(64))
    model_code: Mapped[Optional[str]] = mapped_column(String(32))
    capacity_gb: Mapped[Optional[int]] = mapped_column(Integer)
    colour: Mapped[Optional[str]] = mapped_column(String(64))
    ios: Mapped[Optional[str]] = mapped_column(String(16))
    battery_health: Mapped[Optional[int]] = mapped_column(Integer)
    battery_cycles: Mapped[Optional[int]] = mapped_column(Integer)
    verdict: Mapped[Optional[str]] = mapped_column(String(32))
    price_offer: Mapped[Optional[int]] = mapped_column(Integer)
    price_column: Mapped[Optional[str]] = mapped_column(String(32))
    apple_summary: Mapped[Optional[str]] = mapped_column(String(120))   # «всё родное» / «экран менялся»
    locks_summary: Mapped[Optional[str]] = mapped_column(String(120))   # «чисто» / «Найти iPhone вкл.»
    status: Mapped[str] = mapped_column(String(16), default=ST_NEW, index=True)
    report: Mapped[dict] = mapped_column(JSON)
    snapshot: Mapped[Optional[dict]] = mapped_column(JSON)
    public_token: Mapped[str] = mapped_column(String(32), unique=True)
    assigned_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    final_price: Mapped[Optional[int]] = mapped_column(Integer)
    deal_kind: Mapped[Optional[str]] = mapped_column(String(16))        # buyout | tradein
    inspection: Mapped[Optional[dict]] = mapped_column(JSON)            # чек-лист осмотра
    decision_note: Mapped[Optional[str]] = mapped_column(Text)
    decided_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    decided_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    # данные, собираемые киоском вручную перед импортом в Оценку
    client_name: Mapped[Optional[str]] = mapped_column(String(120))
    client_phone: Mapped[Optional[str]] = mapped_column(String(20))
    has_box: Mapped[Optional[bool]] = mapped_column(Boolean)
    has_cord: Mapped[Optional[bool]] = mapped_column(Boolean)
    panic_full: Mapped[Optional[bool]] = mapped_column(Boolean)
    # загрузка фото/видео клиентом по QR
    upload_token: Mapped[Optional[str]] = mapped_column(String(32), unique=True)
    # результат импорта в Pintel Оценка
    ocenka_device_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    ocenka_imported_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime)
    kiosk: Mapped[Optional[Kiosk]] = relationship()
    point: Mapped[Optional[Point]] = relationship()
    device: Mapped[Optional[Device]] = relationship()
    assigned_user: Mapped[Optional[User]] = relationship(foreign_keys=[assigned_user_id])
    decided_by: Mapped[Optional[User]] = relationship(foreign_keys=[decided_by_id])
    media: Mapped[list["EvaluationMedia"]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan", order_by="EvaluationMedia.id")

    @property
    def status_label(self):
        return STATUSES.get(self.status, self.status)


# виды медиа, которые грузит клиент
MEDIA_PHOTO, MEDIA_VIDEO = "photo", "video"


class EvaluationMedia(Base):
    """Фото/видео телефона, загруженные клиентом по временной ссылке (QR)."""
    __tablename__ = "evaluation_media"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    eval_id: Mapped[int] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8), default=MEDIA_PHOTO)   # photo | video
    filename: Mapped[str] = mapped_column(String(160))                  # имя файла на диске сервера
    content_type: Mapped[Optional[str]] = mapped_column(String(80))
    size: Mapped[Optional[int]] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)
    tg_file_id: Mapped[Optional[str]] = mapped_column(String(200))      # появляется после импорта в Оценку
    evaluation: Mapped[Evaluation] = relationship(back_populates="media")


class PriceGrid(Base):
    __tablename__ = "price_grids"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)
    source: Mapped[Optional[str]] = mapped_column(String(32))
    models_count: Mapped[int] = mapped_column(Integer, default=0)
    positions_count: Mapped[int] = mapped_column(Integer, default=0)
    grid: Mapped[dict] = mapped_column(JSON)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    fetched_by: Mapped[Optional[str]] = mapped_column(String(120))


class SickwCache(Base):
    __tablename__ = "sickw_cache"
    __table_args__ = (UniqueConstraint("imei", "service", name="uq_sickw_imei_service"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imei: Mapped[str] = mapped_column(String(20), index=True)
    service: Mapped[int] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(TZDateTime, default=now)
    raw: Mapped[Optional[str]] = mapped_column(Text)
    normalized: Mapped[Optional[dict]] = mapped_column(JSON)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Optional[dict]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=now, onupdate=now)
