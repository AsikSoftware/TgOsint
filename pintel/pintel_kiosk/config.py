# -*- coding: utf-8 -*-
import os
import shutil
import sys
import tomllib

# Ключи — только латиницей: в TOML голый ключ это буквы ASCII, цифры, «_» и «-».
# Кириллический ключ («сотрудник = …») tomllib отвергает, и киоск не поднимается вовсе.
DEFAULTS = {
    "server": "",                 # https://pintel.example.kz
    "token": "",                  # pk_… из Настройки → Киоски
    "point": "",                  # подпись в шапке, если сервер недоступен
    "apple_history_seconds": 90,
    "return_seconds": 60,
    "fullscreen": True,
    "sickw": True,
    # Автономно (без сервера, одна точка): ключи прямо на киоске
    "sickw_key": "",
    "sickw_services": [61],
    "sickw_services_sealed": [147],   # запечатанный: модель, объём, цвет и активация по IMEI с коробки
    # Реестр IMEI РФС РК: оба IMEI сверяются при любой оценке (без ключа, стандартная библиотека)
    "rfs": True,
    "rfs_proxy": "",              # прокси KZ, если реестр не отвечает из-за рубежа (пусто — напрямую)
    # Оценка: сделку создаёт её бот, приложение отдаёт ему посылку через Telegram
    # (в базу Оценки с точки хода нет — порт Postgres закрыт наружу)
    "ocenka_bot": "",             # имя бота Оценки без @: по ссылке на него сдают фото и видео
    "ocenka_bot_token": "",       # токен того же бота: им приложение отправляет сделку
    "ocenka_chat_id": "",         # рабочая группа, где оценщик подтверждает сделку кнопкой
    "staff_name": "",             # имя сотрудника для чека клиенту
    # Реквизиты в шапке чека: пустые строки просто не печатаются
    "company_name": "Pintel.kz",
    "company_phone": "+77472461313",
    "company_site": "pintelkz.taplink.kz",
    "company_address": "",
    "company_bin": "",
    "reference_keep": 500,        # сколько обезличенных эталонов держать на точке
    "keep_days": 90,              # сколько дней хранить оценки в папке out (0 — не убирать)
    # Архив слепков: своего сервера нет, поэтому файлы уходят в закрытый чат Telegram
    "archive_chat_id": "",        # чат для слепков (пусто — не выгружать)
    "archive_snapshots": False,   # True — слать и полные слепки, в них серийники и IMEI
    # Обновление по интернету: сборки лежат в релизах GitHub
    "update_repo": "AsikSoftware/TgOsint",
    "update_token": "",           # токен только на чтение релизов (пусто — не проверять)
    "update_asset": "pintel-kiosk_Windows_x64.zip",
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


КОПИЯ = "kiosk.toml.копия"


def сберечь(настройки: str, папка_данных: str) -> str:
    """Копия настроек вне папки программы. → путь копии («» — нечего беречь).

    Папку программы сносит и обновление, и обычная переустановка распаковкой поверх.
    Настройки точки (токены, chat_id, кто работает) заполняют руками один раз, и ехать
    на точку, чтобы заполнить их заново, никто не станет."""
    if not os.path.isfile(настройки):
        return ""
    цель = os.path.join(папка_данных, КОПИЯ)
    try:
        if os.path.isfile(цель) and os.path.getmtime(цель) >= os.path.getmtime(настройки):
            return цель                       # не переписываем тем же на каждом запуске
        shutil.copy2(настройки, цель)
    except OSError:
        return ""
    return цель


def вернуть(настройки: str, папка_данных: str) -> bool:
    """Настроек нет, а копия есть — вернуть их на место. → вернули ли."""
    копия = os.path.join(папка_данных, КОПИЯ)
    if os.path.exists(настройки) or not os.path.isfile(копия):
        return False
    try:
        shutil.copy2(копия, настройки)
    except OSError:
        return False
    return True


def load(path=None) -> dict:
    """Настройки рядом с exe.

    Сломанный файл не роняет программу: на точке киоск должен подняться и показать
    причину на экране, а не traceback в окне Windows. Незнакомые ключи тоже называем —
    молча проглоченная опечатка выглядит как «настройка не работает»."""
    cfg = dict(DEFAULTS)
    p = path or os.path.join(app_dir(), "kiosk.toml")
    беда, данные, вернули = "", {}, False
    if path is None:
        try:
            вернули = вернуть(p, data_dir())
        except OSError:
            вернули = False
    if os.path.isfile(p):
        try:
            with open(p, "rb") as f:
                данные = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            беда = f"kiosk.toml не прочитан ({e}) — работаем на умолчаниях"
        except OSError as e:
            беда = f"kiosk.toml не открылся ({e}) — работаем на умолчаниях"
        else:
            лишние = sorted(set(данные) - set(DEFAULTS))
            if лишние:
                беда = "в kiosk.toml незнакомые ключи: " + ", ".join(лишние)
        cfg.update({k: v for k, v in данные.items() if k in DEFAULTS})
        if path is None and not беда:
            try:
                сберечь(p, data_dir())
            except OSError:
                pass
    if вернули and not беда:
        беда = "kiosk.toml пропал и восстановлен из копии — проверьте настройки точки"
    cfg["_path"] = p
    cfg["_ошибка"] = беда
    cfg["server"] = str(cfg["server"]).rstrip("/")
    return cfg
