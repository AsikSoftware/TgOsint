# -*- coding: utf-8 -*-
import os
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
    "staff_name": "",             # имя сотрудника для чека клиенту
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
    """Настройки рядом с exe.

    Сломанный файл не роняет программу: на точке киоск должен подняться и показать
    причину на экране, а не traceback в окне Windows. Незнакомые ключи тоже называем —
    молча проглоченная опечатка выглядит как «настройка не работает»."""
    cfg = dict(DEFAULTS)
    p = path or os.path.join(app_dir(), "kiosk.toml")
    беда, данные = "", {}
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
    cfg["_path"] = p
    cfg["_ошибка"] = беда
    cfg["server"] = str(cfg["server"]).rstrip("/")
    return cfg
