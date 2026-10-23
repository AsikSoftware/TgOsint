# -*- coding: utf-8 -*-
"""Настройки из переменных окружения (в Docker — из .env)."""
import os
from dataclasses import dataclass, field

from pintel_core.external import gsheet


def _list_int(s, default):
    try:
        return [int(x) for x in str(s).replace(";", ",").split(",") if x.strip()] or default
    except ValueError:
        return default


@dataclass
class Settings:
    database_url: str = os.environ.get("PINTEL_DATABASE_URL", "sqlite:///./pintel.db")
    secret_key: str = os.environ.get("PINTEL_SECRET_KEY", "dev-secret-change-me")
    public_url: str = os.environ.get("PINTEL_PUBLIC_URL", "http://localhost:8000").rstrip("/")
    sickw_key: str = os.environ.get("PINTEL_SICKW_KEY", "")
    sickw_services: list = field(default_factory=lambda: _list_int(os.environ.get("PINTEL_SICKW_SERVICES", "61"), [61]))
    price_sheet_url: str = os.environ.get("PINTEL_PRICE_SHEET_URL", gsheet.DEFAULT_URL)
    gservice_json: str = os.environ.get("PINTEL_GSERVICE_JSON", "gservice.json")
    tz: str = os.environ.get("PINTEL_TZ", "Asia/Almaty")
    session_days: int = int(os.environ.get("PINTEL_SESSION_DAYS", "14"))
    currency: str = os.environ.get("PINTEL_CURRENCY", "₸")
    kiosk_return_seconds: int = int(os.environ.get("PINTEL_KIOSK_RETURN_SECONDS", "60"))
    apple_history_seconds: int = int(os.environ.get("PINTEL_APPLE_HISTORY_SECONDS", "90"))

    @property
    def secure_cookies(self):
        return self.public_url.startswith("https://")

    @property
    def is_sqlite(self):
        return self.database_url.startswith("sqlite")


settings = Settings()
