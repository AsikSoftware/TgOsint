# -*- coding: utf-8 -*-
"""Отправка готовой оценки в Pintel Оценка — прямо из приложения на точке.

Пишем в базу Оценки ровно то же, что её собственный бот (`create_device_from_fsm_data`
и шаг после него): device → device_imeis, клиент в `users` (роль 3), статус и автоцена.
Код Оценки не трогаем, поэтому важны мелочи — они разобраны по её исходникам:

* **видео обязательно.** Открытие сделки у неё делает
  `media = [InputMediaVideo(media=device.video_phone)]` без проверки на пусто: сделка без
  видео просто не открывается по кнопке. Поэтому без видео мы её не создаём вовсе —
  лучше честный отказ на точке, чем «висяк» у оценщика.
* **статус как у бота.** «Не был в ремонте» и есть автоцена → status_id 1 (клиенту сразу
  видна цена). Иначе → status_id 2, сделка уходит админу на ручную оценку.
* **словарь полей — её.** `sim` бывает «Dual sim», «E-sim», «Прочее», «Стандарт»;
  `phone_status` — «Не был в ремонте» или «Ранее был в ремонте». Другие значения её
  карточка показывает как есть, и выглядит это как ошибка.

Фото и видео заливаем через Telegram Bot API тем же токеном, что крутит бота: Оценка
хранит не файлы, а `file_id`, и показывает их в карточке сделки.
"""
from __future__ import annotations

import logging
import os
import re

log = logging.getLogger("pintel.ocenka")

SIM_ВАРИАНТЫ = ("Dual sim", "E-sim", "Прочее", "Стандарт")
СТАТУС_ЧИСТЫЙ = "Не был в ремонте"
СТАТУС_РЕМОНТ = "Ранее был в ремонте"
# status_id в Оценке: 1 — автооценка показана клиенту, 2 — ждёт оценки администратора
СТАТУС_АВТО, СТАТУС_АДМИН = 1, 2


class ОшибкаЭкспорта(RuntimeError):
    """Человеческий текст, почему сделка не ушла."""


# ---------------------------------------------------------------- поля сделки

def sim_для_оценки(pas: dict) -> str:
    """Какой SIM у аппарата — словами Оценки. Пустое поле её карточка печатает как «None»."""
    if pas.get("esim_only"):
        return "E-sim"
    if pas.get("esim") or (pas.get("imei2") or "").strip():
        return "Dual sim"            # физический лоток плюс eSIM — у Apple это «две SIM»
    if pas.get("sim_в_лотке") is not None or pas.get("sim"):
        return "Стандарт"
    return "Прочее"


_НЕ_ЦВЕТ = re.compile(r"(?i)^(pro max|pro|plus|mini|air|se|max|a\d{4}|iphone)\b")


def цвет_для_оценки(цвет) -> str | None:
    """Цвет, если это действительно цвет. В карточке Оценки уже видели «Цвет: Pro A2891» —
    так выглядит кусок описания модели, принятый за цвет. Лучше пусто, чем мусор."""
    c = str(цвет or "").strip()
    if not c or _НЕ_ЦВЕТ.match(c) or re.fullmatch(r"(?i)a?\d{3,5}", c):
        return None
    return c[:40]


def статус_ремонта(вердикт_деталей: str | None) -> str | None:
    """Наш вердикт по деталям → «Ремонт статус» Оценки."""
    if вердикт_деталей == "родные":
        return СТАТУС_ЧИСТЫЙ
    if вердикт_деталей in ("замена", "ремонт"):
        return СТАТУС_РЕМОНТ
    return None                      # не подтверждено — пусть решает человек, не мы


def комментарий_оценщика(rep: dict, сверка: str = "", откуда: str = "") -> str:
    """Короткая техническая сводка в поле «Комментарий оценщика»."""
    куски = []
    итог = (rep.get("детали_вердикт") or {}).get("итог")
    if итог:
        куски.append(f"Детали: {итог}")
    if сверка:
        куски.append(сверка)
    журнал = rep.get("apple_история_источник") or rep.get("apple_история_статус")
    if журнал:
        куски.append(f"Apple: {журнал}")
    замки = []
    прав = rep.get("правовой") or {}
    sk = rep.get("sickw") or {}
    if sk.get("в_чёрном_списке") is True:
        замки.append("ЧЁРНЫЙ СПИСОК")
    if прав.get("найти_iphone") == "включён" or sk.get("fmi_включён") is True:
        замки.append("Найти iPhone вкл.")
    if прав.get("mdm") is True:
        замки.append("MDM")
    if замки:
        куски.append("Замки: " + ", ".join(замки))
    бат = rep.get("батарея") or {}
    if бат.get("циклы"):
        куски.append(f"Батарея: {бат.get('здоровье_%') or '?'}%, {бат['циклы']} циклов")
    if откуда:
        куски.append(откуда)
    return " · ".join(куски)[:4000]


def проверить_готовность(данные: dict) -> None:
    """Что обязано быть до вставки. Отдельно от вставки, чтобы экран оценки мог сказать
    сотруднику заранее, чего не хватает, а не после неудачной отправки."""
    нет = []
    if not данные.get("модель"):
        нет.append("модель")
    if not данные.get("память"):
        нет.append("объём памяти")
    if not (данные.get("имя_клиента") and данные.get("телефон_клиента")):
        нет.append("имя и телефон клиента")
    if not данные.get("видео"):
        нет.append("видео телефона (без него Оценка не открывает сделку)")
    if not данные.get("imei"):
        нет.append("IMEI")
    if нет:
        raise ОшибкаЭкспорта("не хватает: " + ", ".join(нет))


# ---------------------------------------------------------------- Telegram

def залить_в_телеграм(путь: str, токен: str, чат: str, видео: bool = False) -> str | None:
    """Файл → Telegram file_id. Оценка хранит в сделке именно file_id, а не файлы."""
    if not (токен and чат and os.path.isfile(путь)):
        return None
    import httpx
    метод, поле = ("sendVideo", "video") if видео else ("sendPhoto", "photo")
    try:
        with open(путь, "rb") as f:
            r = httpx.post(f"https://api.telegram.org/bot{токен}/{метод}",
                           data={"chat_id": чат}, files={поле: (os.path.basename(путь), f)},
                           timeout=120)
        r.raise_for_status()
        res = r.json()["result"]
        return res["video"]["file_id"] if видео else res["photo"][-1]["file_id"]
    except Exception as exc:                                     # noqa: BLE001
        log.warning("ocenka: файл %s не залился: %s", путь, exc)
        return None


# ---------------------------------------------------------------- вставка

def _движок(url: str):
    from sqlalchemy import create_engine
    return create_engine(url, pool_pre_ping=True, future=True)


def отправить(url: str, данные: dict, литера: str = "", оценщик_id: int | None = None) -> dict:
    """Создать сделку в Оценке. → {id, статус, автоцена}.

    `данные` собирает экран оценки: модель, память, акб, цвет, sim, комплектность,
    статус ремонта, цена, комментарии, imei-список, file_id фото и видео, клиент.
    """
    from sqlalchemy import text
    проверить_готовность(данные)
    eng = _движок(url)
    with eng.begin() as conn:
        shop_id = None
        if литера:
            shop_id = conn.scalar(text("SELECT id FROM shops WHERE litera = :lit"), {"lit": литера})
            if shop_id is None:
                raise ОшибкаЭкспорта(f"в Оценке нет магазина с литерой «{литера}»")

        телефон = str(данные["телефон_клиента"]).strip()[:13]
        client_id = conn.scalar(text("SELECT id FROM users WHERE phone = :ph"), {"ph": телефон})
        if client_id is None:
            client_id = conn.scalar(text(
                "INSERT INTO users (first_name, last_name, phone, active, lang, staff_id) "
                "VALUES (:fn, NULL, :ph, true, 'ru', 3) RETURNING id"),
                {"fn": str(данные["имя_клиента"]).strip()[:150], "ph": телефон})

        статус = данные.get("статус_ремонта")
        цена = данные.get("цена")
        # то же правило, что у бота: сразу показываем цену только чистому аппарату с автоценой
        status_id = СТАТУС_АВТО if (статус == СТАТУС_ЧИСТЫЙ and цена) else СТАТУС_АДМИН
        фото = данные.get("фото") or []
        device_id = conn.scalar(text("""
            INSERT INTO devices (
                producer, model, code_name, ddr, akb, akb_exact, color, sim,
                box, cord, panic_full, phone_status, online, status_id,
                price_grade_auto, user_client, user_grade, shop_id_grade,
                photo_phone, video_phone, comment, comment_ocenka
            ) VALUES (
                'Apple', :model, :code_name, :ddr, :akb, :akb_exact, :color, :sim,
                :box, :cord, :panic_full, :phone_status, false, :status_id,
                :price, :client, :grader, :shop,
                :photo, :video, :comment, :comment_ocenka
            ) RETURNING id
        """), {
            "model": str(данные["модель"])[:50],
            "code_name": (данные.get("код_модели") or None),
            "ddr": int(данные["память"]),
            "akb": (f"{данные['акб']}%" if данные.get("акб") is not None else None),
            "akb_exact": данные.get("акб"),
            "color": цвет_для_оценки(данные.get("цвет")),
            "sim": (данные.get("sim") if данные.get("sim") in SIM_ВАРИАНТЫ else "Прочее"),
            "box": данные.get("коробка"), "cord": данные.get("шнур"),
            "panic_full": данные.get("panic_full"), "phone_status": статус,
            "status_id": status_id, "price": цена, "client": client_id,
            "grader": оценщик_id, "shop": shop_id,
            "photo": ("||".join(фото) if фото else None),
            "video": данные["видео"][:200],
            "comment": (данные.get("комментарий") or None),
            "comment_ocenka": (данные.get("комментарий_оценщика") or None),
        })

        первый = (данные.get("imei") or "").strip()
        for imei in dict.fromkeys([первый] + list(данные.get("imei_все") or [])):
            if imei:
                conn.execute(text(
                    "INSERT INTO device_imeis (device_id, imei, verifi, first) "
                    "VALUES (:d, :i, :v, :f)"),
                    {"d": device_id, "i": str(imei)[:20],
                     "v": bool(данные.get("imei_проверен", True)), "f": imei == первый})
    log.info("ocenka: сделка №%s создана (статус %s, цена %s)", device_id, status_id, цена)
    return {"id": int(device_id), "статус": status_id, "автоцена": цена}
