# -*- coding: utf-8 -*-
"""Батарея из узла AppleSmartBattery.

Здоровье = NominalChargeCapacity / DesignCapacity — именно эта цифра
совпадает с Настройками. MaxCapacity — НЕ процент здоровья, а константа
шкалы (100 даже на убитой батарее). В новых iOS (26/27) ёмкости переехали
во вложенный словарь BatteryData — deep() достаёт их на любой глубине.
"""
from ..devicelink.nodes import deep, num, txt

# Отпечаток батареи по модели: заводская ёмкость одна на модель
# (iPhone13,2 = 2798, а не рекламные 2815).
# Порог подделки 1.03 обоснован сверкой с вердиктом Apple на шести аппаратах.


def analyze(node):
    b = node or {}
    design = num(deep(b, "DesignCapacity"))
    nominal = num(deep(b, "NominalChargeCapacity")) or num(deep(b, "AppleRawMaxCapacity"))
    cycles = num(deep(b, "CycleCount"))
    op_h = num(deep(b, "TotalOperatingTime"))
    tmax = num(deep(b, "MaximumTemperature")) // 10
    serial = txt(deep(b, "Serial"))
    disconnects = num(deep(b, "BatteryCellDisconnectCount"))
    health = None
    if design and nominal:
        health = min(round(nominal * 100 / design), 100)

    flags, doubts = [], []
    if design and nominal:
        r = nominal / design
        if r > 1.08:
            flags.append(f"заявляет {nominal} мА·ч при заводских {design} (+{(r-1)*100:.0f}%) — для родной физически невозможно")
        elif r > 1.03:
            flags.append(f"заявляет {nominal} мА·ч при заводских {design} (+{(r-1)*100:.0f}%) — выше заводской, у родной так не бывает")
        elif r < 0.45:
            flags.append(f"заявляет {nominal} мА·ч при заводских {design} — ниже рабочего предела")
    years = round(op_h / 8760, 1) if op_h else None
    if cycles == 0 and years and years > 0.25:
        flags.append(f"ноль циклов при наработке {years} года — пак новее аппарата")
    if disconnects:
        doubts.append(f"шлейф батареи снимали {disconnects} раз(а) — аппарат вскрывали")

    return {
        "есть_данные": bool(b),
        "здоровье_%": health,
        "ёмкость_мАч": nominal or None,
        "заводская_мАч": design or None,
        "циклы": cycles if b else None,
        "наработка_лет": years,
        "макс_температура": tmax if 0 < tmax <= 90 else None,
        "серийник": serial,
        "снятий_шлейфа": disconnects,
        "заряд_%": num(deep(b, "CurrentCapacity")) or None,
        "подделка": flags,
        "сомнения": doubts,
    }
