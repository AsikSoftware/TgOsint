# -*- coding: utf-8 -*-
import os
import sys
import tomllib

DEFAULTS = {
    "server": "",                 # https://pintel.example.kz
    "token": "",                  # pk_… из Настройки → Киоски
    "point": "",                  # подпись в шапке, если сервер недоступен
    "apple_history_seconds": 90,
    "return_seconds": 60,
    "fullscreen": True,
    "currency": "₸",
    "sickw": True,
    # Автономно (без сервера, одна точка): ключи прямо на киоске
    "sickw_key": "",
    "sickw_services": [61],
    "gservice_json": "gservice.json",
    "price_sheet_url": "",
    # Оценка: сделку создаёт её бот, приложение отдаёт ему посылку через Telegram
    # (в базу Оценки с точки хода нет — порт Postgres закрыт наружу)
    "ocenka_bot": "",             # имя бота Оценки без @: по ссылке на него сдают фото и видео
    "ocenka_bot_token": "",       # токен того же бота: им приложение отправляет сделку
    "ocenka_chat_id": "",         # рабочая группа, где оценщик подтверждает сделку кнопкой
    "ocenka_shop_litera": "",     # литера точки в таблице shops
    "сотрудник": "",              # имя для чека
}


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "PintelKiosk")
    for sub in ("queue", "cache", "out", "logs", "эталоны"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d


def load(path=None) -> dict:
    cfg = dict(DEFAULTS)
    p = path or os.path.join(app_dir(), "kiosk.toml")
    if os.path.isfile(p):
        with open(p, "rb") as f:
            cfg.update({k: v for k, v in tomllib.load(f).items() if k in DEFAULTS})
    cfg["_path"] = p
    cfg["server"] = str(cfg["server"]).rstrip("/")
    return cfg
