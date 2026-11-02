# -*- coding: utf-8 -*-
"""Настройки программы на точке — в базе, а не в файле у неё под боком.

Раньше всё это лежало в `kiosk.toml` на каждом компьютере: имя точки, имя сотрудника, бот
Оценки с его токеном, чат архива, репозиторий обновлений, реквизиты для чека, сроки и
пороги. Менять что-то значило объехать точки, а узнать, что на них стоит, — вообще никак.
Поэтому настройки живут здесь: общие на всю сеть (`settings`, ключ `kiosk`) плюс то, что
переопределено для конкретной точки (`points.settings`). Программа забирает их при запуске
и держит последнюю копию у себя, чтобы подняться и без связи.

Имена ключей — те же, что программа читала из файла: так ничего не нужно переименовывать в
её коде, и старый файл на точке остаётся понятной шпаргалкой, даже когда он уже не читается.
"""
from __future__ import annotations

from sqlalchemy import select

from ..models import Point, Setting

КЛЮЧ = "kiosk"

# Что программа спрашивает у сервера. Значения — разумные умолчания; всё, что пусто, задаётся
# в кассе («Настройки → Программа на точках»).
УМОЛЧАНИЯ = {
    # сроки и пороги
    "apple_history_seconds": 90,
    "return_seconds": 60,
    "fullscreen": True,
    "keep_days": 90,
    "reference_keep": 500,
    "phone_test_port": 8765,
    # проверки
    "sickw": True,
    "sickw_services_sealed": [147],
    "rfs": True,
    "rfs_proxy": "",
    # Оценка: сделку создаёт её бот
    "ocenka_bot": "",
    "ocenka_bot_token": "",
    "ocenka_chat_id": "",
    # архив слепков в Telegram остался на крайний случай: эталоны теперь уезжают к нам
    "archive_chat_id": "",
    "archive_snapshots": False,
    # обновление программы
    "update_repo": "AsikSoftware/TgOsint",
    "update_token": "",
    "update_asset": "pintel-kiosk_Windows_x64.zip",
    # реквизиты в шапке чека
    "company_name": "Pintel.kz",
    "company_phone": "+77472461313",
    "company_site": "pintelkz.taplink.kz",
    "company_address": "",
    "company_bin": "",
}

# Эти ключи программа не спрашивает: они её собственные (адрес сервера зашит в сборку, токен
# вводит сотрудник). Перечислены, чтобы случайно не завести их в базе и не путать себя.
НЕ_ОТСЮДА = ("server", "token", "server_key", "point", "staff_name")


def общие(db) -> dict:
    """Настройки на всю сеть. Чего нет в базе — берётся из умолчаний."""
    строка = db.get(Setting, КЛЮЧ)
    значения = dict(УМОЛЧАНИЯ)
    значения.update({k: v for k, v in ((строка.value if строка else None) or {}).items()
                     if k in УМОЛЧАНИЯ})
    return значения


def сохранить_общие(db, данные: dict) -> dict:
    """Записать общие настройки. Чужие ключи не принимаем: пусть в базе лежит ровно то, что
    программа умеет читать."""
    строка = db.get(Setting, КЛЮЧ)
    было = dict((строка.value if строка else None) or {})
    было.update({k: v for k, v in (данные or {}).items() if k in УМОЛЧАНИЯ})
    if строка is None:
        db.add(Setting(key=КЛЮЧ, value=было))
    else:
        строка.value = было
    db.commit()
    return общие(db)


def для_точки(db, точка: Point | None) -> dict:
    """Что отдать программе этой точки: общее, поверх — её собственное, плюс её имя.

    Имя точки и имя сотрудника идут отсюда же: надпись в углу экрана обязана совпадать с
    тем, что записано в базе, иначе по чеку и по отчёту не понять, где аппарат смотрели.
    """
    значения = общие(db)
    if точка is not None:
        значения.update({k: v for k, v in (точка.settings or {}).items() if k in УМОЛЧАНИЯ})
        значения["point"] = точка.name
        значения["staff_name"] = точка.staff_name or ""
    else:
        значения["point"] = ""
        значения["staff_name"] = ""
    return значения


def точки_с_токенами(db) -> list:
    return list(db.scalars(select(Point).order_by(Point.name)))
