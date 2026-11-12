# -*- coding: utf-8 -*-
"""Процент батареи — тот же, что в Настройках телефона.

Сотрудник и клиент смотрят на экран телефона: «Аккумулятор → Состояние аккумулятора →
Максимальная ёмкость». По этому проценту выбирается колонка прайса, то есть это прямо
деньги и прямой спор у стойки. Телефон называет это число сам, в журнале (iOS 14 и новее);
если строка не пришла, оно считается от минимума за жизнь (NCCMin) с округлением вверх.
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


def test_ot_minimuma_okruglyaem_vverh():
    """iPhone 12 на iOS 18.7.8, 12.11.2026: на экране телефона 79, программа показала 78.

    Телефон своё число в журнал не назвал, и считали мы сами: 2194/2798 = 78,41 → 78.
    Экран телефона всегда чуть выше доли минимума за жизнь (на шести аппаратах — на
    0,2–1,3 процента), поэтому округляем вверх, а не к ближайшему."""
    b = battery.analyze(узел(nominal=2235, design=2798, NCCMin=2194))
    assert b["здоровье_%"] == 79 and b["здоровье_основание"] == "минимум за жизнь"
    # те же аппараты, где известны и экран, и ёмкости: экран 77, 76, 94, 82
    for design, минимум, экран in ((3092, 2366, 77), (4395, 3332, 76), (3544, 3301, 94),
                                   (4395, 3581, 82)):
        b = battery.analyze(узел(nominal=минимум + 5, design=design, NCCMin=минимум))
        assert b["здоровье_%"] == экран, (design, минимум, b["здоровье_%"])
    ровно = battery.analyze(узел(nominal=2600, design=3125, NCCMin=2500))
    assert ровно["здоровье_%"] == 80, "ровные 80,0 остаются 80, а не 81"


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


# Сняты с проверок 11.11.2026, iPhone 16 Pro на iOS 26.6.2 (имя телефона заменено).
СТРОКИ_IOS26 = [
    "Nov 11 16:42:46 iPhone powerd[48] <Notice>: Previous Battery Health: Flags:3 State:0 "
    "MaxCapacity:94 CycleCount:423",
    "Nov 11 16:42:46 iPhone powerd[48] <Notice>: Updated Battery Health: Flags:3",
    "Nov 11 16:42:46 iPhone powerd[48] <Notice>: Updated Battery Health: State:0",
    "Nov 11 16:42:46 iPhone powerd[48] <Notice>: Updated Battery Health: MaxCapacity:94",
    "Nov 11 16:42:46 iPhone powerd[48] <Notice>: Updated Battery Health: CycleCount:423",
]


def test_slushatel_lovit_chislo_ios26():
    """iOS 26 пишет число телефона другими словами, и «Updated» — по полю в строке.

    Пока узнавали только вид iOS 27, на этом аппарате выходило 93 по нашему расчёту, а
    телефон говорил 94 — и по 94 его видел клиент."""
    from pintel_core.devicelink import repair_history as rh

    lst = rh.Listener(None)
    for строка in СТРОКИ_IOS26:
        lst._feed(строка)
    сказал = lst.meta["батарея_телефона"]
    assert сказал == {"процент": 94, "циклы": 423, "состояние": 0, "свежая": True}, сказал
    b = battery.analyze(узел(nominal=3311, design=3544, NCCMin=3301), сказал)
    assert b["здоровье_%"] == 94 and b["здоровье_основание"] == "сказал сам телефон"


# Сняты 12.11.2026 с живого iPhone 13 на iOS 18.7.8, как есть (имя телефона — общее).
# Между «Previous» и «Updated» телефон печатает свои служебные строки — они числу не мешают.
СТРОКИ_IOS18 = [
    "Nov 12 02:50:18 iPhone powerd[16873] <Notice>: Previous Battery Health: Flags:1048579 "
    "State:1 MaxCapacity:75 CycleCount:1756",
    "Nov 12 02:50:18 iPhone powerd[16873] <Notice>: calib: svcFlags pre: 0x3",
    "Nov 12 02:50:18 iPhone powerd[16873] <Notice>: calib: device not relevant",
    "Nov 12 02:50:18 iPhone powerd[16873] <Notice>: calib: svcFlags post: 0x3",
    "Nov 12 02:50:18 iPhone powerd[16873] <Notice>: Nominal Capacity percentage(75) is less "
    "than the threshold(80)",
    "Nov 12 02:50:18 iPhone powerd[16873] <Notice>: Updated Battery Health: Flags:1048579",
    "Nov 12 02:50:18 iPhone powerd[16873] <Notice>: Updated Battery Health: State:1",
    "Nov 12 02:50:18 iPhone powerd[16873] <Notice>: Updated Battery Health: MaxCapacity:75",
    "Nov 12 02:50:18 iPhone powerd[16873] <Notice>: Updated Battery Health: CycleCount:1756",
]


def test_slushatel_lovit_chislo_ios18():
    """iOS 18 называет процент той же строкой, что и iOS 26, — раз в 20 секунд на кабеле.

    До 12.11.2026 считалось, что iOS 18 молчит: сборки до 0.5.0 эти строки не сохраняли, а
    единственная проверка новой сборкой их не дождалась."""
    from pintel_core.devicelink import repair_history as rh

    lst = rh.Listener(None)
    for строка in СТРОКИ_IOS18:
        lst._feed(строка)
    сказал = lst.meta["батарея_телефона"]
    assert сказал == {"процент": 75, "циклы": 1756, "состояние": 1, "свежая": True}, сказал
    # тот же телефон: узел называет 1810 циклов, телефон помнит 1756 — это не расхождение
    этот = узел(nominal=2410, design=3208, NCCMin=2375, CycleCount=1810)
    b = battery.analyze(этот, сказал)
    assert b["здоровье_%"] == 75 and b["здоровье_основание"] == "сказал сам телефон"
    assert b["циклы"] == 1810 and b["циклы_по_телефону"] == 1756 and not b["сомнения"], b
    # и без строки наш расчёт даёт то же: ceil(2375 / 3208 × 100) = 75
    сами = battery.analyze(этот)
    assert сами["здоровье_%"] == 75 and сами["здоровье_основание"] == "минимум за жизнь"


def test_ios26_previous_goditsya_poka_net_svezhego():
    """Одна строка «Previous» — уже число телефона; свежие поля потом ложатся поверх."""
    from pintel_core.devicelink import repair_history as rh

    lst = rh.Listener(None)
    lst._feed(СТРОКИ_IOS26[0].replace("MaxCapacity:94", "MaxCapacity:95"))
    assert lst.meta["батарея_телефона"] == {"процент": 95, "циклы": 423, "состояние": 0,
                                            "свежая": False}
    lst._feed(СТРОКИ_IOS26[1])                       # свежая, но про флаги — процент прежний
    assert lst.meta["батарея_телефона"]["процент"] == 95
    lst._feed(СТРОКИ_IOS26[3])
    assert lst.meta["батарея_телефона"]["процент"] == 94
    lst._feed(СТРОКИ_IOS26[0].replace("MaxCapacity:94", "MaxCapacity:95"))
    assert lst.meta["батарея_телефона"]["процент"] == 94, "«Previous» не затирает свежее"


def test_chuzhie_stroki_ne_schitayutsya_chislom_telefona():
    """Раздел ремонта тоже пишет «Battery Health State{» — это не процент."""
    from pintel_core.devicelink import repair_history as rh

    for строка in ("Nov 12 01:23:20 iPhone Preferences(CoreRepairUI)[1868] <Notice>: Battery Health State{",
                   "    IOPSBatteryHealthState = 3;",
                   "Nov 11 16:42:46 iPhone powerd[48] <Notice>: Updated Battery Health: Flags:3"):
        сказал = rh.батарея_из_строки(строка)
        assert сказал is None or "процент" not in сказал[1], строка
    lst = rh.Listener(None)
    lst._feed("Nov 11 16:42:46 iPhone powerd[48] <Notice>: Updated Battery Health: Flags:3")
    b = battery.analyze(узел(NCCMin=2470), lst.meta.get("батарея_телефона"))
    assert b["здоровье_основание"] == "минимум за жизнь", "одни флаги — ещё не число телефона"


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
    """Телефон помнит циклы на момент последнего изменения процента. Счётчик батареи меньше
    этого числа быть не может — значит, его сбрасывали, а по циклам идёт самая дорогая
    колонка прайса («100 (0-30)»)."""
    b = battery.analyze(узел(CycleCount=12), {"процент": 100, "циклы": 980})
    assert any("счётчик батареи сбрасывали" in с for с in b["сомнения"]), b["сомнения"]
    ровно = battery.analyze(узел(CycleCount=1064), {"процент": 79, "циклы": 1064})
    assert not any("цикл" in с for с in ровно["сомнения"])
    # ноль по узлу — самый опасный случай: «новая» батарея при 980 циклах у телефона
    ноль = battery.analyze(узел(CycleCount=0), {"процент": 100, "циклы": 980})
    assert any("счётчик батареи сбрасывали" in с for с in ноль["сомнения"]), ноль["сомнения"]
    # сброс не до нуля: обе стороны «не новая», прежнее правило это пропускало
    сорок = battery.analyze(узел(CycleCount=40), {"процент": 88, "циклы": 500})
    assert any("счётчик батареи сбрасывали" in с for с in сорок["сомнения"]), сорок["сомнения"]
    # цикл-два в запас — не сброс
    рядом = battery.analyze(узел(CycleCount=402), {"процент": 93, "циклы": 403})
    assert not рядом["сомнения"], рядом["сомнения"]


def test_cikly_rashodyatsya_i_na_ispravnyh_telefonah():
    """iPhone 15 Pro Max, 11.11.2026: узел называет 1241 цикл, сам телефон — 1021.

    Это не сорванное чтение, так бывает на исправных аппаратах, и пугать сотрудника тут
    нечем. Оба числа лежат в отчёте рядом."""
    b = battery.analyze(узел(CycleCount=1241), {"процент": 82, "циклы": 1021})
    assert b["циклы"] == 1241 and b["циклы_по_телефону"] == 1021
    assert not b["сомнения"], b["сомнения"]
    assert battery.analyze(узел(CycleCount=1241))["циклы_по_телефону"] is None
    # здоровая батарея держит 100 % с пятого цикла: телефон помнит 5, счётчик ушёл на 300.
    # Прежнее правило («один источник говорит новая, другой нет») пугало тут сотрудника зря.
    свежая = battery.analyze(узел(CycleCount=300), {"процент": 100, "циклы": 5})
    assert not свежая["сомнения"], свежая["сомнения"]


def test_schetchik_shleifa_ne_otdali_znachit_ne_znaem():
    """iOS 27 счётчик снятий шлейфа не отдаёт. Раньше в отчёте стоял ноль — «не снимали»."""
    assert battery.analyze(узел())["снятий_шлейфа"] is None
    assert battery.analyze(узел(BatteryCellDisconnectCount=0))["снятий_шлейфа"] == 0
    вскрыт = battery.analyze(узел(BatteryCellDisconnectCount=2))
    assert вскрыт["снятий_шлейфа"] == 2 and any("шлейф" in с for с in вскрыт["сомнения"])


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
