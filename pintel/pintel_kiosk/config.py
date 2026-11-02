# -*- coding: utf-8 -*-
"""Настройки программы на точке: ничего не вписывают руками.

Программа — внешняя часть, источник правды снаружи. Адрес сервера зашит в сборку, токен
точки сотрудник вводит в самой программе один раз (и меняет через меню администратора), а
все настройки — имя точки, кто у кассы, бот Оценки, сроки, реквизиты чека, откуда брать
обновления — приходят с сервера и складываются в копию рядом с данными, чтобы программа
поднялась и без связи.

Раньше всё это жило в `kiosk.toml` у exe: менять настройку значило объехать девятнадцать
компьютеров, а узнать, что на них стоит, было нельзя вовсе. Файла больше нет.
"""
import json
import os
import sys

# Один сервер с базой на всю сеть.
СЕРВЕР = "https://kiosk.pintelkz.com"

# Чем программа живёт, пока сервер не ответил (первый запуск или нет связи). Имена ключей те
# же, что на сервере (`pintel_server/services/kiosk_settings.py`): сервер присылает ровно этот
# набор, и переименовывать в коде нечего.
УМОЛЧАНИЯ = {
    "point": "",                  # имя точки — его говорит сервер, оно же в углу экрана
    "staff_name": "",             # кто у кассы — в чек клиенту
    "apple_history_seconds": 90,
    "return_seconds": 60,
    "fullscreen": True,
    "keep_days": 90,              # сколько дней хранить оценки в папке out (0 — не убирать)
    "reference_keep": 500,        # сколько обезличенных эталонов держать на точке
    "phone_test_port": 8765,      # порт страницы теста в локальной сети
    "sickw": True,
    "sickw_services_sealed": [147],
    "rfs": True,
    "rfs_proxy": "",
    "ocenka_bot": "",
    "ocenka_bot_token": "",
    "ocenka_chat_id": "",
    "archive_chat_id": "",        # архив слепков в Telegram остался на крайний случай
    "archive_snapshots": False,
    "update_repo": "AsikSoftware/TgOsint",
    "update_token": "",
    "update_asset": "pintel-kiosk_Windows_x64.zip",
    "company_name": "Pintel.kz",
    "company_phone": "+77472461313",
    "company_site": "pintelkz.taplink.kz",
    "company_address": "",
    "company_bin": "",
}

ФАЙЛ_ТОКЕНА = "точка.json"
ФАЙЛ_НАСТРОЕК = "настройки.json"


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


def _прочитать(путь: str) -> dict:
    try:
        with open(путь, encoding="utf-8") as f:
            данные = json.load(f)
        return данные if isinstance(данные, dict) else {}
    except Exception:                                            # noqa: BLE001 — нет файла или он битый
        return {}


def _записать(путь: str, данные: dict) -> None:
    os.makedirs(os.path.dirname(путь), exist_ok=True)
    with open(путь, "w", encoding="utf-8") as f:
        json.dump(данные, f, ensure_ascii=False, indent=1)


def токен(папка=None) -> str:
    """Токен точки. Пусто — программа спросит точку и токен на первом экране."""
    return str(_прочитать(os.path.join(папка or data_dir(), ФАЙЛ_ТОКЕНА)).get("token") or "")


def точка_id(папка=None):
    """id точки = id магазина в Оценке. Его выбирают при первой настройке."""
    v = _прочитать(os.path.join(папка or data_dir(), ФАЙЛ_ТОКЕНА)).get("point_id")
    return int(v) if str(v or "").isdigit() else None


def запомнить_токен(значение: str, point_id=None, папка=None) -> None:
    """Токен и выбранная точка живут рядом с данными, а не в папке программы: обновление
    сносит папку программы распаковкой поверх, и ехать на точку вводить это заново никто
    не станет."""
    _записать(os.path.join(папка or data_dir(), ФАЙЛ_ТОКЕНА),
              {"token": str(значение or "").strip(), "point_id": point_id})


def сохранить_настройки(данные: dict, папка=None) -> dict:
    """Запомнить то, что прислал сервер. Чужие ключи не храним."""
    своё = {k: v for k, v in (данные or {}).items() if k in УМОЛЧАНИЯ}
    _записать(os.path.join(папка or data_dir(), ФАЙЛ_НАСТРОЕК), своё)
    return своё


# Мост на время перехода: до этой версии настройки лежали в kiosk.toml рядом с exe. Пока
# их не перенесли в базу, читаем оттуда то, без чего точка не работает, — иначе первая же
# обновившаяся точка останется без бота Оценки и не сможет отправить сделку. Как только
# настройки заведены на сервере, они перекрывают файл: сервер всегда главнее.
ИЗ_СТАРОГО_ФАЙЛА = ("ocenka_bot", "ocenka_bot_token", "ocenka_chat_id", "archive_chat_id",
                    "update_token", "staff_name")


def из_старого_файла(папка_программы=None) -> dict:
    """Что удалось вычитать из прежнего kiosk.toml. Нет файла — пустой словарь."""
    import tomllib
    путь = os.path.join(папка_программы or app_dir(), "kiosk.toml")
    try:
        with open(путь, "rb") as f:
            данные = tomllib.load(f)
    except Exception:                                            # noqa: BLE001 — нет файла или битый
        return {}
    return {k: v for k, v in данные.items() if k in ИЗ_СТАРОГО_ФАЙЛА and v not in ("", None)}


def load(папка=None) -> dict:
    """Настройки для запуска: умолчания, поверх — последняя копия с сервера.

    Ломаться тут нечему: руками сюда никто не пишет. Сервер ещё ничего не присылал —
    программа поднимется на умолчаниях и скажет на первом экране, чего она ждёт.
    """
    папка = папка or data_dir()
    сохранённые = _прочитать(os.path.join(папка, ФАЙЛ_НАСТРОЕК))
    cfg = dict(УМОЛЧАНИЯ)
    cfg.update(из_старого_файла())            # мост: то, что ещё не перенесли в базу
    cfg.update({k: v for k, v in сохранённые.items() if k in УМОЛЧАНИЯ})
    cfg["server"] = СЕРВЕР
    cfg["token"] = токен(папка)
    cfg["point_id"] = точка_id(папка)         # он же id магазина в Оценке
    cfg["_настройки_с_сервера"] = bool(сохранённые)
    cfg["_ошибка"] = ""
    return cfg
