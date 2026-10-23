# -*- coding: utf-8 -*-
"""Сопряжения деталей с платой — сигналы для сотрудника.

Сильнее «серийник есть»: серийник можно прочитать с донорской детали,
сопряжение — нет. Проверено побайтно на реальных аппаратах. Отсутствие
данных НИКОГДА не превращается в вердикт: вернётся None.
"""
from ..devicelink.nodes import deep, num, txt


def faceid(camera):
    """SavageSNUM[4:12] == FrontIRCameraSerialNumber. Только это равенство:
    SavageDeviceID/Rev — константы семейства чипа, дают ложные срабатывания."""
    sn, ir = deep(camera or {}, "SavageSNUM"), deep(camera or {}, "FrontIRCameraSerialNumber")
    if not (isinstance(sn, (bytes, bytearray)) and isinstance(ir, (bytes, bytearray))):
        return None
    if len(sn) < 12 or len(ir) != 8:
        return None
    return bytes(sn)[4:12] == bytes(ir)


def taptic(arc_eeprom, iface):
    arc = txt(deep(arc_eeprom or {}, "ArcSerialNumber"))
    valid = deep(arc_eeprom or {}, "IsArcSerialNumberValid")
    pscl = deep(iface or {}, "pscl-cal")
    pscl = bytes(pscl).decode("ascii", "replace") if isinstance(pscl, (bytes, bytearray)) else txt(pscl)
    if valid is False:
        return False
    if arc and pscl:
        return arc in pscl
    return None


def screen_calibration(backlight):
    """*Panel (что стоит) против *Product (что ожидает плата)."""
    bl = backlight or {}
    pairs = [(num(deep(bl, a)), num(deep(bl, b))) for a, b in
             (("lMinPanel", "lMinProduct"), ("lMidPanel", "lMidProduct"),
              ("lMaxPanel", "lMaxProduct"))]
    pairs = [(a, b) for a, b in pairs if a and b]
    if len(pairs) < 3:
        return None
    return all(a == b for a, b in pairs)


def coverglass(product):
    """product/coverglass-serial-number входит в raw-panel-serial-number."""
    p = product or {}
    cg = txt(deep(p, "coverglass-serial-number")).rstrip("\x00")
    raw = deep(p, "raw-panel-serial-number")
    raw = bytes(raw).decode("ascii", "replace") if isinstance(raw, (bytes, bytearray)) else txt(raw)
    if not cg or not raw:
        return None
    return cg in raw


def proximity(product, prox):
    a = txt(deep(product or {}, "rosaline-serial-num"))
    b = txt(deep(prox or {}, "SerialNumber"))
    if not a or not b:
        return None
    return a == b


def cameras(camera):
    """Наличие серийников модулей. Статусы *ValidationStatus — константа
    прошивки, в правила не годятся. Фронтальная RGB не проверяется."""
    cam = camera or {}
    out = {}
    for label, ser_key, exp_key in (
        ("Основная камера", "BackCameraModuleSerialNumString", "BackCameraExpected"),
        ("Сверхширокая", "BackSuperWideCameraModuleSerialNumString", "BackSuperWideCameraExpected"),
        ("Телефото", "BackTeleCameraModuleSerialNumString", "BackTeleCameraExpected"),
    ):
        if not cam:
            continue
        expected = bool(deep(cam, exp_key))
        ser = txt(deep(cam, ser_key))
        if ser:
            out[label] = ("серийник есть", True)
        elif expected:
            out[label] = ("модуль не называет серийный номер", False)
    if cam and deep(cam, "FrontCameraExpected"):
        out["Фронтальная"] = ("наличие есть, подлинность по кабелю не проверяется", None)
    return out


def touch(touch_node):
    t = touch_node or {}
    if not t:
        return None, None
    errs = num(deep(t, "Critical Errors"))
    return errs == 0, errs


def signals(snap):
    """Сводка сигналов: {имя: {"ок": True/False/None, "почему": str}}."""
    n = snap.get("nodes", {})
    out = {}

    def put(name, ok, why_ok, why_bad, why_none="данных нет"):
        out[name] = {"ок": ok, "почему": why_ok if ok else (why_bad if ok is False else why_none)}

    f = faceid(n.get("camera"))
    put("Face ID ↔ плата", f, "криптопривязка модуля к чипу сошлась",
        "криптопривязка ИК-камеры к чипу нарушена — модуль с другого аппарата")
    t = taptic(n.get("AppleHapticsSupportArcEEPROM"), n.get("haptics-support-interface"))
    put("Taptic ↔ плата", t, "модуль сопряжён с платой", "модуль не тот, под который прошита плата")
    s = screen_calibration(n.get("AppleARMBacklight"))
    put("Экран: калибровка", s, "калибровка панели совпадает с ожидаемой",
        "калибровка панели не совпадает — вероятна замена")
    c = coverglass(n.get("product"))
    put("Экран: стекло ↔ панель", c, "серийник стекла входит в серийник панели",
        "серийник стекла не совпадает с панелью")
    p = proximity(n.get("product"), n.get("prox") or n.get("AppleProxHIDEventDriver"))
    put("Датчик приближения", p, "серийник совпадает с записанным в плате",
        "серийник отличается от записанного в плате")
    ok, errs = touch(n.get("AppleMultitouchDevice"))
    put("Тачскрин", ok, "критических ошибок нет", f"критических ошибок: {errs}")
    for label, (why, ok2) in cameras(n.get("camera")).items():
        out[label] = {"ок": ok2, "почему": why}
    return out
