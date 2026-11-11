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
    assert b["здоровье_%"] == 78                      # 2470/3181 — ближе всего к экрану
    assert b["здоровье_текущее_%"] == 79              # 2506/3181 — столько показывают сторонние
    assert b["минимум_мАч"] == 2470 and "минимум" in b["здоровье_основание"]


def test_bez_minimuma_schitaem_kak_prezhde():
    """Старые iOS этот ключ не отдают. Тогда остаётся текущая ёмкость — и отчёт говорит это."""
    b = battery.analyze(узел())
    assert b["здоровье_%"] == 79 and b["здоровье_текущее_%"] == 79
    assert b["минимум_мАч"] is None and b["здоровье_основание"].startswith("текущая ёмкость")


def test_musornomu_minimumu_ne_verim():
    """На живом аппарате NCCMin пришёл больше заводской ёмкости. Такому числу верить нельзя:
    оно дало бы 106% здоровья и «новую» батарею на убитом телефоне."""
    b = battery.analyze(узел(nominal=2774, design=3208, NCCMin=3394))
    assert b["здоровье_%"] == 86 and b["здоровье_основание"].startswith("текущая ёмкость")

    низкий = battery.analyze(узел(NCCMin=200))       # ниже рабочего предела — тоже мусор
    assert низкий["здоровье_%"] == 79 and низкий["здоровье_основание"].startswith("текущая ёмкость")


def test_podmenennaya_batareya_po_prezhnemu_lovitsya():
    """Проверка на неоригинальную батарею считается по ТЕКУЩЕЙ ёмкости: пак больше заводского
    — физически невозможная родная. Минимум за жизнь её бы спрятал."""
    b = battery.analyze(узел(nominal=3630, design=3208, NCCMin=3211))
    assert b["здоровье_%"] == 100 and b["подделка"], b
    assert "невозможно" in b["подделка"][0] and "3630" in b["подделка"][0]


# ---------------------------------------------------------------- число от самого телефона

СТРОКА_POWERD = ("Nov 11 12:52:15 iPhone powerd[51] <Notice>: Updated battery health "
                 "(packId=0 flags=1048580 state=1 maxCap=79 cycleCount=1064)")
СТРОКА_ПРЕЖНЯЯ = СТРОКА_POWERD.replace("Updated", "Previous").replace("maxCap=79", "maxCap=81")


def test_slushatel_lovit_chislo_telefona():
    """powerd печатает здоровье батареи каждые 10–20 секунд, сам, без открытых экранов.

    Проверка живая: строка снята с iPhone 15 Pro на iOS 27.0.1, где на экране стояло 79."""
    from pintel_core.devicelink import repair_history as rh

    lst = rh.Listener(None)
    lst._feed(СТРОКА_ПРЕЖНЯЯ)
    assert lst.meta["батарея_телефона"]["процент"] == 81, "пока ничего нового — берём что есть"
    lst._feed(СТРОКА_POWERD)
    сказал = lst.meta["батарея_телефона"]
    assert сказал["процент"] == 79 and сказал["циклы"] == 1064 and сказал["состояние"] == 1
    lst._feed(СТРОКА_ПРЕЖНЯЯ)
    assert lst.meta["батарея_телефона"]["процент"] == 79, "«Previous» не затирает свежее"


def test_chislo_telefona_glavnee_nashego_scheta():
    """Телефон сказал 79 — значит 79, хотя наше деление ёмкостей даёт 80.

    Ровно это и расходилось у стойки: клиент смотрит на свой экран, а не на наши ёмкости."""
    b = battery.analyze(узел(nominal=2593, design=3254),
                        {"процент": 79, "циклы": 1064, "состояние": 1})
    assert b["здоровье_%"] == 79 and b["здоровье_основание"] == "сказал сам телефон"
    assert b["здоровье_текущее_%"] == 80            # столько вышло бы у нас
    assert b["здоровье_по_телефону_%"] == 79 and b["обслуживание_флаг"] == 1


def test_vyshe_sta_telefon_i_sam_ne_risuet():
    """На новом аппарате powerd говорит 103, а на экране 100. Рисуем как телефон."""
    b = battery.analyze(узел(nominal=5621, design=5509), {"процент": 103, "циклы": 22})
    assert b["здоровье_%"] == 100 and b["здоровье_по_телефону_%"] == 103


def test_bez_stroki_schitaem_sami_i_govorim_ob_etom():
    """Строка могла не успеть прийти — тогда считаем сами, но основание это называет."""
    b = battery.analyze(узел(NCCMin=2470), None)
    assert b["здоровье_%"] == 78 and b["здоровье_основание"] != "сказал сам телефон"
    assert b["здоровье_по_телефону_%"] is None


def test_rashozhdenie_ciklov_ne_zamalchivaem():
    """Узел и журнал читаются из одного места. Разошлись — значит чтение протухло, а по
    циклам идёт самая дорогая колонка прайса («100 (0-30)»)."""
    b = battery.analyze(узел(CycleCount=12), {"процент": 100, "циклы": 980})
    assert any("циклы расходятся" in с for с in b["сомнения"]), b["сомнения"]
    ровно = battery.analyze(узел(CycleCount=1064), {"процент": 79, "циклы": 1064})
    assert not any("циклы" in с for с in ровно["сомнения"])


def test_otchet_beret_chislo_telefona_iz_zhurnala():
    """Сквозь весь отчёт: слушатель положил число в метаданные — батарея в отчёте его взяла."""
    import json
    import os

    from pintel_core.analysis import report as report_mod
    from pintel_core.devicelink import snapshot as snap_mod

    здесь = os.path.dirname(os.path.abspath(__file__))
    путь = os.path.join(здесь, "fixtures_real", "iphone12_ios26_anon.snapshot.json")
    снимок = snap_mod.loads(open(путь, encoding="utf-8").read())

    свой = report_mod.build(снимок)["батарея"]
    assert свой["здоровье_%"] == 77 and свой["здоровье_основание"] != "сказал сам телефон"

    снимок["repair_history_meta"] = {**(снимок.get("repair_history_meta") or {}),
                                     "батарея_телефона": {"процент": 74, "циклы": 2096,
                                                          "состояние": 1, "свежая": True}}
    сказал = report_mod.build(снимок)["батарея"]
    assert сказал["здоровье_%"] == 74 and сказал["здоровье_основание"] == "сказал сам телефон"
    assert сказал["здоровье_текущее_%"] == 78
