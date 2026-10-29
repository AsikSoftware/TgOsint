# -*- coding: utf-8 -*-
"""Что у модели вообще есть — чтобы «у этой модели такого нет» не превращалось
в «не прочиталось» и не портило вердикт."""
import re

# В эпоху Face ID с кнопкой «Домой» и Touch ID вышли только iPhone SE 2 и SE 3
TOUCH_ID_IN_FACE_ID_ERA = {"iPhone12,8", "iPhone14,6"}


def _major(pt):
    m = re.match(r"iPhone(\d+),(\d+)", str(pt or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def has_face_id(pt):
    """True/False; None — не iPhone или не распознан."""
    major, _ = _major(pt)
    if major is None:
        return None
    if pt in TOUCH_ID_IN_FACE_ID_ERA:
        return False
    if major >= 11:
        return True
    return pt in ("iPhone10,3", "iPhone10,6")          # iPhone X


def has_touch_id(pt):
    fid = has_face_id(pt)
    return None if fid is None else (not fid)


# Какие детали Apple вообще отслеживает в разделе «Детали и обслуживание» —
# официальная таблица Apple (support.apple.com/ru-ru/102658):
#   iPhone XR / XS / XS Max / SE 2 / SE 3 — только аккумулятор;
#   iPhone 11 — аккумулятор и дисплей;
#   iPhone 12 и новее — + материнская плата, фронтальная и задние камеры.
# Чего в таблице нет, того Apple не подтвердит никогда: требовать по такой детали
# подтверждения нельзя, надо честно сказать, что по ней судим только по кабелю.
APPLE_PARTS_BATTERY = ("Battery",)
APPLE_PARTS_11 = ("Battery", "Display")
APPLE_PARTS_12 = ("Battery", "Display", "LogicBoard", "FrontCamera", "Camera")
# С 15-й серии заднее стекло меняется отдельно, и Apple ведёт его в разделе. Видно на
# эталонах: в строках systemhealth BackGlass = 1 у iPhone 15 Pro и 0 (не отслеживается)
# у 14 Pro. Нумерация моделей это не разделяет — 14 Pro это iPhone15,2, а iPhone 15 —
# iPhone15,4, поэтому сравниваем пару «поколение, модификация».
APPLE_PARTS_15 = APPLE_PARTS_12 + ("BackGlass",)


def apple_tracked_parts(pt):
    """→ детали, по которым Apple ведёт историю для этой модели. Пусто — раздела нет."""
    major, minor = _major(pt)
    if major is None:
        return ()
    if pt in TOUCH_ID_IN_FACE_ID_ERA:                 # SE 2 и SE 3 — только аккумулятор
        return APPLE_PARTS_BATTERY
    if major < 11:                                    # iPhone X и старше — раздела нет
        return ()
    if major == 11:                                   # XR, XS, XS Max
        return APPLE_PARTS_BATTERY
    if major == 12:                                   # iPhone 11 семейство
        return APPLE_PARTS_11
    if (major, minor) >= (15, 4):                     # iPhone 15 и новее
        return APPLE_PARTS_15
    return APPLE_PARTS_12


# Калибровка подсветки: lMinPanel/lMidPanel/lMaxPanel против *Product. На iPhone 11
# (единственный ЖК-экран среди проверенных) все три пары расходятся ВСЕГДА, причём у
# двух разных аппаратов значения совпали побайтово — так не бывает при настоящей
# замене. Там плата хранит номинал, а панель отдаёт измеренное, и равенство — не тот
# вопрос. На OLED-моделях (12 и новее) обе величины сходятся.
#
# Пока сигнал не разобран, на этих моделях он не вывод, а молчание: ложное «экран
# меняли» отказывает в сделке на КАЖДОМ таком телефоне, а подлинность экрана здесь
# подтверждает раздел «Детали и обслуживание» — iPhone 11 Apple в нём отслеживает.
БЕЗ_СРАВНИМОЙ_КАЛИБРОВКИ = ("iPhone12,1", "iPhone12,3", "iPhone12,5")   # 11, 11 Pro, Pro Max


def сравнимая_калибровка_экрана(pt) -> bool:
    """Можно ли на этой модели судить о замене экрана по калибровке подсветки."""
    return str(pt or "") not in БЕЗ_СРАВНИМОЙ_КАЛИБРОВКИ
