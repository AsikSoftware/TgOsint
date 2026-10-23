# -*- coding: utf-8 -*-
"""Подключение к базе. SQLite — для разработки и тестов, PostgreSQL — на сервере."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, TypeDecorator, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


class TZDateTime(TypeDecorator):
    """Время всегда с зоной (UTC). SQLite зону не хранит — возвращаем её при чтении,
    иначе сравнения «naive vs aware» падают на ровном месте."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


def make_engine(url=None):
    url = url or settings.database_url
    kw = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
    eng = create_engine(url, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _pragmas(conn, _):
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    return eng


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(eng=None):
    """Создать таблицы напрямую (разработка/тесты). На сервере — alembic upgrade head."""
    from . import models  # noqa: F401  — регистрирует таблицы
    Base.metadata.create_all(eng or engine)


def now():
    return datetime.now(timezone.utc)
