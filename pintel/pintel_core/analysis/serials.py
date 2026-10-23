# -*- coding: utf-8 -*-
"""Серийники деталей и даты выпуска — как в отчёте 3uTools.

Дата из 17-значного серийника детали Apple (проверено на пяти примерах
против 3uTools): знак 4 — последняя цифра года, знаки 5–6 — номер недели
(на единицу больше ISO-недели), знак 7 — день недели (1 = понедельник).
    FG92027038HQ68CAT → 2022-01-09, DNL15271CEAMFGR99 → 2021-12-26,
    GVH14011L5ULQHMAU → 2021-09-27.

Дата выпуска самого телефона — из 12-значного серийника старой схемы
(до 2021 года): знак 4 — год и полугодие, знак 5 — неделя. У моделей
2021+ серийники случайные, даты в них нет.
"""
import re
from datetime import date, timedelta

from ..devicelink.nodes import deep, txt

# Год выхода по коду модели — чтобы снять неоднозначность десятилетия
_RELEASE_YEAR = {8: 2015, 9: 2016, 10: 2017, 11: 2018, 12: 2019, 13: 2020, 14: 2021,
                 15: 2022, 16: 2023, 17: 2024, 18: 2025, 19: 2026}

# Старая схема 12-значных серийников: 4-й знак → (год, полугодие)
_YEAR_CODES = "CDFGHJKLMNPQRSTVWXYZ"          # C=H1 2010 … Z=H2 2019, затем по кругу
_WEEK_CODES = "123456789CDFGHJKLMNPQRTVWXY"   # 1..9, затем буквы = недели 10..27

_PANEL_VENDOR = {"GVH": "LG", "GVC": "LG", "G9N": "Samsung", "G9P": "Samsung", "GV7": "Samsung",
                 "GH0": "BOE"}
# Таблицы «префикс → фабрика» для плат/батарей/камер не подтверждены ничем, кроме
# слухов (у 3uTools FG — SIMPLO для батарей и FIH Vietnam для аксессуаров, у нас было
# Desay — и всё это для одного и того же префикса). Показываем только то, что
# сверено с отчётом 3uTools: производителя панели.
_FACTORY = {}


def release_year(product_type):
    m = re.match(r"iPhone(\d+),", str(product_type or ""))
    return _RELEASE_YEAR.get(int(m.group(1))) if m else None


def part_date(serial, hint_year=None):
    """Дата выпуска детали из 17-значного серийника, иначе None."""
    s = str(serial or "").strip()
    if len(s) < 7 or not s[3].isdigit() or not s[4:6].isdigit() or not s[6].isdigit():
        return None
    y, week, wd = int(s[3]), int(s[4:6]), int(s[6])
    if not (1 <= week <= 54 and 1 <= wd <= 7):
        return None
    base = (hint_year or date.today().year) // 10 * 10
    year = base + y
    if hint_year and year > hint_year + 5:       # цифра года из прошлого десятилетия
        year -= 10
    try:
        iso_week = week - 1
        if iso_week >= 1:
            d = date.fromisocalendar(year, iso_week, wd)
        else:
            d = date.fromisocalendar(year, 1, wd) - timedelta(days=7)
    except ValueError:
        return None
    return d.isoformat()


def device_production(serial, product_type=None):
    """(год, неделя) из 12-значного серийника старой схемы, иначе None."""
    s = str(serial or "").strip()
    if len(s) != 12 or s[3] not in _YEAR_CODES or s[4] not in _WEEK_CODES:
        return None
    idx = _YEAR_CODES.index(s[3])
    half, year10 = idx % 2, 2010 + idx // 2
    week = _WEEK_CODES.index(s[4]) + 1 + (26 if half else 0)
    ry = release_year(product_type)
    year = year10
    while ry and year < ry:
        year += 10
    return {"год": year, "неделя": week, "полугодие": half + 1}


def collect(snap, product_type=None):
    """Список деталей: серийник, дата, фабрика — всё, что телефон называет."""
    nodes = snap.get("nodes") or {}
    root = snap.get("root") or {}
    cam, prod, bat = nodes.get("camera") or {}, nodes.get("product") or {}, nodes.get("AppleSmartBattery") or {}
    hint = release_year(product_type) or None
    items = []

    def add(name, serial, vendor=None):
        full = txt(serial).strip("\x00 ")
        if not full:
            return
        serial = full.split("+")[0]           # панель/стекло: за «+» идут серийники соседних слоёв
        items.append({"деталь": name, "серийник": serial, "дата": part_date(serial, hint),
                      "фабрика": _FACTORY.get(serial[:3]), "производитель": vendor,
                      "полный": full if full != serial else None})

    add("Материнская плата", root.get("MLBSerialNumber"))
    add("Аккумулятор", deep(bat, "Serial"))
    add("Основная камера", deep(cam, "BackCameraModuleSerialNumString"))
    add("Сверхширокая камера", deep(cam, "BackSuperWideCameraModuleSerialNumString"))
    add("Телефото камера", deep(cam, "BackTeleCameraModuleSerialNumString"))
    add("Фронтальная камера", deep(cam, "FrontCameraModuleSerialNumString"))
    add("ИК-камера Face ID", deep(cam, "FrontIRCameraModuleSerialNumString"))
    panel = deep(prod, "raw-panel-serial-number")
    panel = bytes(panel).decode("ascii", "replace").strip("\x00 ") if isinstance(panel, (bytes, bytearray)) else txt(panel)
    if panel:
        add("Экран (панель)", panel, _PANEL_VENDOR.get(panel[:3]))
    add("Экран (стекло)", deep(prod, "coverglass-serial-number"))
    arc = nodes.get("AppleHapticsSupportArcEEPROM") or {}
    add("Taptic Engine", deep(arc, "ArcSerialNumber"))
    prox_node = nodes.get("prox") or nodes.get("AppleProxHIDEventDriver") or {}
    add("Датчик приближения", deep(prod, "rosaline-serial-num") or deep(prox_node, "SerialNumber"))
    add("Модуль Nova (назначение уточняется)", deep(prod, "nova-serial-num"))
    return items
