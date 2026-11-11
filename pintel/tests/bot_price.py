# -*- coding: utf-8 -*-
"""Настоящий `utils/google_price.py` бота Оценки — тот, что лежит у нас в `deploy/оценка_бот/`.

На сервер он ставится руками, поэтому проверяется здесь, до установки. Наружу в тестах он
не ходит: Google, настройки бота и его база подменены пустышками.
"""
import importlib.util
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ФАЙЛ = os.path.join(HERE, "..", "deploy", "оценка_бот", "google_price.py")


def загрузить(monkeypatch):
    """Модуль под именем `utils.google_price` — так его зовёт и `handlers/kiosk_price.py`."""
    def _нельзя(*a, **k):
        raise AssertionError("в тесте Google не зовём")

    gspread = types.ModuleType("gspread")
    gspread.Client = object
    gspread.authorize = _нельзя
    config = types.ModuleType("config")
    config.settings = types.SimpleNamespace(GOOGLE_SHEETS_CREDS_JSON={},
                                            GOOGLE_SHEETS_SPREADSHEET_ID="ключ", GOOGLE_SHEETS_SHEET_GID=1)
    database = types.ModuleType("database")
    models = types.ModuleType("database.models")
    models.Device = type("Device", (), {})
    database.models = models

    spec = importlib.util.spec_from_file_location("utils.google_price", ФАЙЛ)
    модуль = importlib.util.module_from_spec(spec)
    utils = types.ModuleType("utils")
    utils.google_price = модуль
    for имя, подмена in (("gspread", gspread), ("config", config), ("database", database),
                         ("database.models", models), ("utils", utils),
                         ("utils.google_price", модуль)):
        monkeypatch.setitem(sys.modules, имя, подмена)
    spec.loader.exec_module(модуль)
    модуль._get_client = _нельзя
    return модуль
