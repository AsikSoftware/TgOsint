"""Правила: из сырых данных — вердикт по деталям и предварительная цена.

Главный принцип, выстраданный на живых аппаратах: ОТСУТСТВИЕ ДАННЫХ НИКОГДА
НЕ ПРЕВРАЩАЕТСЯ В ВЕРДИКТ. Не прочиталось — так и пишем. Ложное срабатывание
обвиняет честного клиента и стоит дороже пропуска.
"""
import json, os, re
from .device import deep, txt, num

from .paths import bundled
# Справочник моделей не редактируется, поэтому читаем из комплекта.
MODELS = json.load(open(bundled("core", "models.json"), encoding="utf-8"))

# Отпечаток батареи по модели: ёмкость, старшие 16 бит ChemID и AlgoChemID,
# код детали в серийнике пака, и на скольких НЕЗАВИСИМЫХ аппаратах подтверждён.
# Порог: пока подтверждений меньше трёх, вердикт по отпечатку не выносится —
# эталон, снятый с аппарата, где уже стоял китайский пак, перевернул бы правило
# и начал обвинять родные батареи.
BATT_REF = {
    "iPhone13,2": (2798, 0x3C13, 0x3C1D, "Q68", 2),
    "iPhone14,5": (3208, 0x3C2D, 0x3C3E, "18F", 1),
    "iPhone15,2": (3181, 0x3C5A, 0x3C5A, "21P", 1),
}
BATT_REF_MIN = 3


def _battery(raw):
    b = raw["battery"]
    des = num(deep(b, "DesignCapacity"))
    # Здоровье считаем по NominalChargeCapacity: именно эта цифра совпадает
    # с Настройками. MaxCapacity здесь НЕ используется намеренно — это не
    # процент здоровья, а константа шкалы, равная 100 даже на убитой батарее.
    now = num(deep(b, "NominalChargeCapacity")) or num(deep(b, "AppleRawMaxCapacity"))
    cycles = num(deep(b, "CycleCount"))
    op_h = num(deep(b, "TotalOperatingTime"))
    tmax = num(deep(b, "MaximumTemperature")) // 10
    out = {
        "есть_данные": bool(b),
        "ёмкость": now, "завод": des,
        "износ": (min(now * 100 // des, 100) if (des and now) else None),
        "циклы": cycles,
        "наработка_лет": round(op_h / 8760, 1) if op_h else None,
        "макс_темп": tmax if 0 < tmax <= 90 else None,
        "серийник": txt(deep(b, "Serial")),
        "снятий_шлейфа": num(deep(b, "BatteryCellDisconnectCount")),
        "подделка": [], "сомнения": [],
    }
    if des and now:
        r = now / des
        # Порог 1.03 обоснован сверкой с вердиктом Apple на шести аппаратах:
        # три с заменённой батареей — выше 103%, два с родной — ниже.
        if r > 1.08:
            out["подделка"].append(
                f"заявляет {now} мА·ч при заводских {des} (+{(r-1)*100:.0f}%) — для родной физически невозможно")
        elif r > 1.03:
            out["подделка"].append(
                f"заявляет {now} мА·ч при заводских {des} (+{(r-1)*100:.0f}%) — выше заводской, у родной так не бывает")
        elif r < 0.45:
            out["подделка"].append(f"заявляет {now} мА·ч при заводских {des} — ниже рабочего предела")
    if cycles == 0 and out["наработка_лет"] and out["наработка_лет"] > 0.25:
        out["подделка"].append(
            f"ноль циклов при наработке {out['наработка_лет']} года — пак новее аппарата")
    return out


def _faceid(raw):
    """Единственная криптографическая проверка: в 20 байтах SavageSNUM
    крипточипа TrueDepth зашит серийник ИК-камеры. Ловит даже камеру,
    переставленную с другого живого iPhone.
    Сверяется РОВНО это равенство: SavageDeviceID и SavageDeviceRev —
    константы семейства чипа, меняются между поколениями, и их порядок
    байтов непостоянен, поэтому их сверка даёт ложные срабатывания."""
    cam = raw["camera"]
    sn, ir = deep(cam, "SavageSNUM"), deep(cam, "FrontIRCameraSerialNumber")
    if not (isinstance(sn, (bytes, bytearray)) and isinstance(ir, (bytes, bytearray))):
        return None
    if len(sn) < 12 or len(ir) != 8:
        return None
    return bytes(sn)[4:12] == bytes(ir)


def _taptic(raw):
    """Серийник, записанный в самом модуле, должен встречаться в калибровке
    со стороны платы. Если таптик меняли, не перепрошивая плату, разойдутся."""
    arc = txt(deep(raw["haptic_eeprom"], "ArcSerialNumber"))
    valid = deep(raw["haptic_eeprom"], "IsArcSerialNumberValid")
    pscl = deep(raw["haptic_iface"], "pscl-cal")
    pscl = bytes(pscl).decode("ascii", "replace") if isinstance(pscl, (bytes, bytearray)) else str(pscl or "")
    if valid is False:
        return False
    if arc and pscl:
        return arc in pscl
    return None


def _screen(raw):
    """AppleARMBacklight держит ДВА набора, и имена различают их прямо:
    *Panel — характеристики установленной панели, *Product — что аппарат
    ожидает. На шести исправных совпали, значения разные по моделям.
    Не подтверждено на аппарате с заведомо менянным экраном, поэтому
    вердикт мягкий."""
    bl = raw["backlight"]
    pairs = [(num(deep(bl, a)), num(deep(bl, b))) for a, b in
             (("lMinPanel", "lMinProduct"), ("lMidPanel", "lMidProduct"),
              ("lMaxPanel", "lMaxProduct"))]
    pairs = [(a, b) for a, b in pairs if a and b]
    if len(pairs) < 3:
        return None
    return all(a == b for a, b in pairs)


def build(raw):
    r = raw["root"]
    pt = str(r.get("ProductType") or "")
    parts, stop, todo, warn = {}, [], [], []

    bat = _battery(raw)
    # --- паспорт ---
    out = {
        "паспорт": {
            "модель": MODELS.get(pt, f"{pt} — модель не в справочнике"),
            "код_модели": pt,
            "номер_модели": str(r.get("ModelNumber") or "") + str(r.get("RegionInfo") or ""),
            "серийник": str(r.get("SerialNumber") or ""),
            "серийник_платы": str(r.get("MLBSerialNumber") or ""),
            "imei": str(r.get("InternationalMobileEquipmentIdentity") or ""),
            "imei2": str(r.get("InternationalMobileEquipmentIdentity2") or ""),
            "ios": str(r.get("ProductVersion") or ""),
            "память_гб": raw["disk_total_gb"],
            "свободно_гб": raw["disk_free_gb"],
            # Цвет по кабелю НЕ определяется: DeviceColor равнялся 1 на всех
            # собранных аппаратах. Настоящий цвет даёт только внешняя база.
            "цвет": None,
        },
        "батарея": bat,
    }

    # --- детали ---
    def put(name, verdict, why=""):
        parts[name] = {"вердикт": verdict, "почему": why}

    if not bat["есть_данные"]:
        put("Батарея", "НЕТ ДАННЫХ", "запись батареи не ответила")
    elif bat["подделка"]:
        put("Батарея", "НЕОРИГИНАЛ", bat["подделка"][0])
    elif bat["серийник"]:
        put("Батарея", "ОРИГИНАЛ", f"износ {bat['износ']}%" if bat["износ"] else "")
    else:
        put("Батарея", "ЗАМЕНЕНА", "нет серийного номера")

    fid = _faceid(raw)
    if fid is True:
        put("Face ID", "ОРИГИНАЛ", "криптопривязка модуля к чипу сошлась")
    elif fid is False:
        put("Face ID", "ЗАМЕНЕНА", "криптопривязка ИК-камеры к чипу нарушена")

    tap = _taptic(raw)
    if tap is True:
        put("Taptic Engine", "ОРИГИНАЛ", "модуль сопряжён с платой")
    elif tap is False:
        put("Taptic Engine", "ЗАМЕНЕНА", "модуль не тот, под который прошита плата")

    scr = _screen(raw)
    if scr is True:
        put("Экран", "ОРИГИНАЛ", "калибровка панели совпадает с ожидаемой")
    elif scr is False:
        put("Экран", "ПОД ВОПРОСОМ", "калибровка панели не совпадает — вероятна замена")
    elif raw["display"]:
        put("Экран", "НА МЕСТЕ", "панель отвечает, калибровку сверить не удалось")

    # Камеры: наличие серийника. Слабее сопряжения, но лучше ничего.
    cam = raw["camera"]
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
            put(label, "ОРИГИНАЛ", "")
        elif expected:
            put(label, "ЗАМЕНЕНА", "модуль не называет серийный номер")
        # нет ключа Expected — камеры нет в этой модели, молчим

    # Фронтальная RGB: криптопривязки для неё НЕТ, SavageSNUM связывает только
    # ИК-камеру. Писать «оригинал» значило бы создавать ложную уверенность.
    if cam and deep(cam, "FrontCameraExpected"):
        put("Фронтальная", "НА МЕСТЕ", "подлинность по кабелю не проверяется, только наличие")

    te = num(deep(raw["touch"], "Critical Errors"))
    if raw["touch"]:
        put("Тачскрин", "СБОИ" if te else "ИСПРАВЕН", f"критических ошибок: {te}" if te else "ошибок нет")

    out["детали"] = parts

    # --- юридический статус ---
    # Значение приходит БАЙТАМИ (b'YES'). Раньше здесь был str(), а у второго
    # канала txt() — и один читался как "b'YES'", второй как "YES". Из-за этого
    # исправный аппарат получал «не определился» и ложное «данные подменены».
    # Оба канала обязаны декодироваться одинаково.
    fm = txt(deep(r, "fm-activation-locked")).strip().upper()
    fm_opt = txt(deep(raw["options"], "fm-activation-locked")).strip().upper()
    sup = any(deep(raw[k], v) is True for k, v in (("aidbus", "TRM_TransportSupervised"),))
    out["юридический"] = {
        "найти_iphone": {"NO": "выключен", "YES": "включён"}.get(fm, "не определился"),
        "каналы_сошлись": (None if not fm_opt or not fm else fm == fm_opt),
        "активация": str(r.get("ActivationState") or ""),
        "пароль": bool(r.get("PasswordProtected")),
        "mdm": sup,
    }
    if out["юридический"]["найти_iphone"] == "включён":
        todo.append("«Найти iPhone» включён — клиент должен выйти из Apple ID")
    if out["юридический"]["пароль"]:
        todo.append("на телефоне стоит пароль — попроси снять")
    if sup:
        stop.append("аппарат под корпоративным надзором (MDM) — перепродать нельзя")
    if out["юридический"]["каналы_сошлись"] is False:
        stop.append("статус «Найти iPhone» различается в двух источниках — данные подменены")

    # --- износ в цену ---
    if bat["износ"] and bat["износ"] < 80:
        warn.append(f"износ батареи {bat['износ']}% — под замену")
    if bat["циклы"] > 800:
        warn.append(f"{bat['циклы']} циклов — ресурс выработан")

    for lbl, pv in parts.items():
        v = pv["вердикт"]
        if v.startswith(("ЗАМЕН", "НЕОРИГ")) or v == "СБОИ":
            stop.append(f"{lbl}: {v.lower()}" + (f" ({pv['почему']})" if pv["почему"] else ""))
        elif v == "ПОД ВОПРОСОМ":
            warn.append(f"{lbl}: {pv['почему']}")

    out["стоп"], out["сделать"], out["внимание"] = stop, todo, warn

    # --- итог по аппарату ---
    no_data = [l for l, v in parts.items() if v["вердикт"] == "НЕТ ДАННЫХ"]
    replaced = [l for l, v in parts.items() if v["вердикт"].startswith(("ЗАМЕН", "НЕОРИГ"))]
    doubt = [l for l, v in parts.items() if v["вердикт"] == "ПОД ВОПРОСОМ"]
    unver = [l for l, v in parts.items() if v["вердикт"] == "НА МЕСТЕ"]
    if stop and not replaced:
        итог = ("ПРОБЛЕМНЫЙ", "есть причины не принимать")
    elif replaced:
        итог = ("РЕМОНТИРОВАН", "заменено: " + ", ".join(replaced))
    elif no_data:
        # «Идеал» не выдаётся, когда что-то не прочиталось: на идеале платят
        # больше, и отсутствие флагов — не то же самое, что отсутствие проблем.
        итог = ("ПРОВЕРКА НЕПОЛНАЯ", "не прочиталось: " + ", ".join(no_data))
    elif doubt:
        итог = ("ПОД ВОПРОСОМ", "сомнения по: " + ", ".join(doubt))
    elif bat["износ"] and bat["износ"] >= 85 and not warn:
        итог = ("ИДЕАЛ", "проверенные детали оригинальные, аппарат не вскрывался")
    else:
        итог = ("ХОРОШИЙ", "проверенные детали оригинальные, есть износ")
    tail = f" (по кабелю не проверяются: {', '.join(x.lower() for x in unver)})" if unver else ""
    out["итог"] = {"вердикт": итог[0], "почему": итог[1] + tail}
    return out
