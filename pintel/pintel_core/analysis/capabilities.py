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
