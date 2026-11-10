# -*- coding: utf-8 -*-
"""Процент батареи — тот же, что в Настройках телефона.

Сотрудник и клиент смотрят на экран телефона: «Аккумулятор → Состояние аккумулятора →
Максимальная ёмкость». Там стоит минимум за жизнь (NCCMin), а текущая ёмкость
(NominalChargeCapacity) гуляет выше на процент-два — и наш процент выходил больше того, что
видит клиент. По этому проценту выбирается колонка прайса, то есть это прямо деньги и
прямой спор у стойки.
"""
from pintel_core.analysis import battery


def узел(**ключи):
    """Узел AppleSmartBattery, как его отдаёт iOS 26: ёмкости во вложенном BatteryData."""
    d = {"NominalChargeCapacity": 2506, "CycleCount": 1670,
         "BatteryData": {"DesignCapacity": 3181, "LifetimeData": {}}}
    for имя, значение in ключи.items():
        if имя == "NCCMin":
            d["BatteryData"]["LifetimeData"]["NCCMin"] = значение
        elif имя == "design":
            d["BatteryData"]["DesignCapacity"] = значение
        elif имя == "nominal":
            d["NominalChargeCapacity"] = значение
        else:
            d[имя] = значение
    return d


def test_schitaem_po_minimumu_za_zhizn():
    b = battery.analyze(узел(NCCMin=2470))
    assert b["здоровье_%"] == 78                      # 2470/3181 — столько и на экране телефона
    assert b["здоровье_текущее_%"] == 79              # 2506/3181 — столько показывают сторонние
    assert b["минимум_мАч"] == 2470 and "минимум" in b["здоровье_основание"]


def test_bez_minimuma_schitaem_kak_prezhde():
    """Старые iOS этот ключ не отдают. Тогда остаётся текущая ёмкость — и отчёт говорит это."""
    b = battery.analyze(узел())
    assert b["здоровье_%"] == 79 and b["здоровье_текущее_%"] == 79
    assert b["минимум_мАч"] is None and b["здоровье_основание"] == "текущая ёмкость"


def test_musornomu_minimumu_ne_verim():
    """На живом аппарате NCCMin пришёл больше заводской ёмкости. Такому числу верить нельзя:
    оно дало бы 106% здоровья и «новую» батарею на убитом телефоне."""
    b = battery.analyze(узел(nominal=2774, design=3208, NCCMin=3394))
    assert b["здоровье_%"] == 86 and b["здоровье_основание"] == "текущая ёмкость"

    низкий = battery.analyze(узел(NCCMin=200))       # ниже рабочего предела — тоже мусор
    assert низкий["здоровье_%"] == 79 and низкий["здоровье_основание"] == "текущая ёмкость"


def test_podmenennaya_batareya_po_prezhnemu_lovitsya():
    """Проверка на неоригинальную батарею считается по ТЕКУЩЕЙ ёмкости: пак больше заводского
    — физически невозможная родная. Минимум за жизнь её бы спрятал."""
    b = battery.analyze(узел(nominal=3630, design=3208, NCCMin=3211))
    assert b["здоровье_%"] == 100 and b["подделка"], b
    assert "невозможно" in b["подделка"][0] and "3630" in b["подделка"][0]
