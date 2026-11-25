# -*- coding: utf-8 -*-
"""Где программа держит своё: адрес сервера и токен входа.

Токен — это доступ ко всей сети, поэтому он лежит не рядом с программой, а в папке данных
пользователя, и только там. Пароль не хранится нигде и никогда: ввёл — обменяли на токен.
"""
import json
import os
import sys

СЕРВЕР = "https://kiosk.pintelkz.com"
ФАЙЛ = "admin.json"


def data_dir() -> str:
    """Папка данных программы. На маке — там, где их держат маковские программы."""
    база = os.environ.get("LOCALAPPDATA")
    if not база:
        база = (os.path.expanduser("~/Library/Application Support") if sys.platform == "darwin"
                else os.path.expanduser("~"))
    путь = os.path.join(база, "PintelAdmin")
    os.makedirs(путь, exist_ok=True)
    return путь


def _путь() -> str:
    return os.path.join(data_dir(), ФАЙЛ)


def load() -> dict:
    try:
        with open(_путь(), encoding="utf-8") as f:
            данные = json.load(f)
        return данные if isinstance(данные, dict) else {}
    except Exception:                                    # noqa: BLE001 — нет файла или он битый
        return {}


def save(**поля):
    """Дописать поля к сохранённому. Файл читает только эта программа."""
    данные = load()
    данные.update(поля)
    with open(_путь(), "w", encoding="utf-8") as f:
        json.dump(данные, f, ensure_ascii=False, indent=1)
    try:
        os.chmod(_путь(), 0o600)                         # токен — не для соседних программ
    except OSError:
        pass


def сервер() -> str:
    return str(load().get("сервер") or СЕРВЕР).rstrip("/")


def токен() -> str:
    return str(load().get("токен") or "")


def забыть_токен():
    save(токен="")
