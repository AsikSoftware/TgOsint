# -*- coding: utf-8 -*-
"""Слушатель истории Apple: обрыв потока, переподключение, записи после done."""
import asyncio
import pytest
from pintel_core.devicelink import repair_history as rh

BLOCK = ('Oct 23 16:33:33 iPhone Preferences(CoreRepairCore)[6674] <Notice>: repairHistoryForUI:{\n',
         '    Battery = "[CRRepairHistoryItem: componentName:Battery: componentType:1024: isRepaired:0: isUsed:0: repairDate:(null):]";\n',
         '    Display = "[CRRepairHistoryItem: componentName:Display: componentType:1025: isRepaired:1: isUsed:1: repairDate:2026-03-01:]";\n',
         '    FaceID = "[CRRepairHistoryItem: componentName:FaceID: componentType:1027: isRepaired:0: isUsed:0: repairDate:(null):]";\n')


class FakeSyslog:
    """Сценарий: список «подключений»; каждое — список строк; строка 'DROP' = обрыв."""
    script = []
    connects = 0
    closed = 0

    def __init__(self, ld):
        pass

    async def connect(self):
        FakeSyslog.connects += 1

    async def watch(self):
        idx = FakeSyslog.connects - 1
        lines = FakeSyslog.script[idx] if idx < len(FakeSyslog.script) else []
        for l in lines:
            if l == "DROP":
                raise ConnectionError("device closed")
            await asyncio.sleep(0.01)
            yield l
        while True:                                     # живой поток без строк
            await asyncio.sleep(0.05)

    async def close(self):
        FakeSyslog.closed += 1


@pytest.fixture
def fake(monkeypatch):
    FakeSyslog.connects = FakeSyslog.closed = 0
    monkeypatch.setattr(rh, "SyslogService", FakeSyslog)
    return FakeSyslog


def test_capture_survives_stream_drop(fake):
    fake.script = [["noise 1\n", "noise 2\n", "DROP"], ["mobilerepaird: something\n", *BLOCK]]
    items, raw, waited = asyncio.run(rh.capture(None, seconds=10))
    assert set(items) == {"Battery", "Display", "FaceID"} and items["Display"]["меняли"] and items["Display"]["бу"]
    assert items["Display"]["дата"] == "2026-03-01"
    assert "# syslog оборвался" in raw and fake.connects == 2 and waited < 10


def test_capture_times_out_and_keeps_related_lines(fake):
    fake.script = [["CoreRepairCore: cache hit\n", "noise\n"]]
    items, raw, waited = asyncio.run(rh.capture(None, seconds=0.6))
    assert items == {} and "# похожее: CoreRepairCore: cache hit" in raw and waited >= 0.6


def test_listener_keeps_running_after_wait(fake):
    """Киоск: wait вернулся пусто, слушатель живёт дальше и ловит записи позже."""
    fake.script = [["noise\n"] * 3]

    async def scenario():
        lst = rh.Listener(None, reconnect_delay=0.01)
        await lst.start()
        items, raw, _ = await lst.wait(0.3)
        assert items == {}
        # записи «приходят» позже — подкладываем их в живой поток
        for l in BLOCK:
            lst._feed(l)
        items, raw, _ = await lst.wait(5, grace=0.1)
        await lst.stop()
        return items, raw

    items, raw = asyncio.run(scenario())
    assert set(items) == {"Battery", "Display", "FaceID"} and "CRRepairHistoryItem" in raw


def test_listener_keep_going_stops_wait(fake):
    fake.script = [[]]

    async def scenario():
        lst = rh.Listener(None)
        await lst.start()
        flag = {"go": True}
        asyncio.get_event_loop().call_later(0.2, lambda: flag.update(go=False))
        items, raw, waited = await lst.wait(10, keep_going=lambda: flag["go"])
        await lst.stop()
        return waited

    assert asyncio.run(scenario()) < 2


def test_parse_handles_duplicates_and_unicode_dates():
    txt = ('componentName:Display: componentType:1025: isRepaired:1: isUsed:0: repairDate:(null):"\n'
           'componentName:Display: componentType:1025: isRepaired:1: isUsed:0: repairDate:1 \\U043c\\U0430\\U044f 2026:"\n')
    items = rh.parse(txt)
    assert items["Display"]["дата"] == "1 мая 2026"
    items2 = rh.parse(txt.split("\n")[1] + "\n" + txt.split("\n")[0])
    assert items2["Display"]["дата"] == "1 мая 2026"               # дата не затирается пустой


# ---------- iOS 18.7: сверка с заводской печатью (строки с живых iPhone 12 и iPhone 13, обезличены) ----------
IOS18_CLEAN = [
    "Oct 26 12:47:27 iPhone Preferences(CoreRepairCore)[23371] <Notice>: Getting local sealing manifest\n",
    "Oct 26 12:47:28 iPhone Preferences(CoreRepairUI)[23371] <Notice>: updateSpecifiersWithCompletionHandler\n",
    "Oct 26 12:47:28 iPhone Preferences(CoreRepairCore)[23371] <Notice>: fetched RCHL successfully: (null) length = 0\n",
    "Oct 26 12:47:28 iPhone corerepaird[23321] <Notice>: Received a connection on com.apple.corerepair.preflightControl!\n",
    "Oct 26 12:47:28 iPhone corerepaird(libamsupport.dylib)[23321] <Notice>: _copyIdentifierListForSealingMapEntry: Using value GHD00000XX0XXXX0X+00000000000000000000000000 for key CoverglassSerialNumber from query cache\n",
    "Oct 26 12:47:28 iPhone corerepaird(libamsupport.dylib)[23321] <Notice>: _copyIdentifierListForSealingMapEntry: Using value 0000000A000E for key AmbientLightSensorSerialNumber from query cache\n",
    "Oct 26 12:47:28 iPhone corerepaird(CoreRepairCore)[23321] <Notice>: Read live data: 1\n",
    "Oct 26 12:47:28 iPhone corerepaird(CoreRepairCore)[23321] <Notice>: Unsealed: {\n    }\n",
    "Oct 26 12:47:28 iPhone corerepaird(CoreRepairCore)[23321] <Notice>: No delta components found\n",
    "Oct 26 12:47:28 iPhone Preferences(CoreRepairCore)[23371] <Notice>: delta components: {\n    }\n",
]
IOS18_DELTA = IOS18_CLEAN[:-2] + [
    "Oct 26 12:47:28 iPhone corerepaird(CoreRepairCore)[23321] <Notice>: delta components found: 1\n",
    "Oct 26 12:47:28 iPhone Preferences(CoreRepairCore)[23371] <Notice>: delta components: {\n    Display =     {\n        state = 2;\n    };\n}\n",
]


def test_ios18_clean_seal_means_all_original(fake):
    fake.script = [["noise\n"] + IOS18_CLEAN]

    async def scenario():
        lst = rh.Listener(None)
        await lst.start()
        items, raw, waited = await lst.wait(10, grace=0.1)
        meta = lst.meta
        await lst.stop()
        return items, raw, waited, meta

    items, raw, waited, meta = asyncio.run(scenario())
    assert set(items) == {"Battery", "Display", "Camera", "FaceID"}
    assert not any(v["меняли"] for v in items.values()) and items["FaceID"]["источник"].startswith("сверка")
    assert meta["раздел_открыт"] and meta["дельта"] == [] and meta["rchl_байт"] == 0
    assert meta["формат"].startswith("сверка") and meta["печать"]["AmbientLightSensorSerialNumber"] == "0000000A000E"
    assert "delta components" in raw and "# похожее" in raw and waited < 10


def test_ios18_delta_component_is_unknown_part(fake):
    fake.script = [IOS18_DELTA]
    items, raw, _ = asyncio.run(rh.capture(None, seconds=10))
    assert items["Display"]["меняли"] and items["Display"]["неизвестная"] and not items["Battery"]["меняли"]


def test_ios26_items_win_over_synthesis(fake):
    fake.script = [IOS18_CLEAN[:3] + list(BLOCK)]
    items, raw, _ = asyncio.run(rh.capture(None, seconds=10))
    assert items["Display"]["меняли"] and items["Display"]["бу"] and "источник" not in items["Display"]


BLOCK_CLEAN = tuple(l.replace("isRepaired:1: isUsed:1: repairDate:2026-03-01", "isRepaired:0: isUsed:0: repairDate:(null)")
                    for l in BLOCK)


def test_seal_delta_merges_into_records(fake):
    """iPhone 15 Pro с подменённым экраном: записи обслуживания молчат (ремонтов Apple не было),
    а сверка с печатью видит «Неизвестная деталь» — она не должна теряться из-за записей."""
    fake.script = [list(BLOCK_CLEAN) + IOS18_DELTA]
    items, raw, _ = asyncio.run(rh.capture(None, seconds=10))
    assert items["Display"]["меняли"] and items["Display"]["неизвестная"] and items["Display"]["источник"].startswith("сверка")
    assert not items["Battery"]["меняли"] and not items["FaceID"]["меняли"]
    fake.connects = 0
    fake.script = [IOS18_DELTA + list(BLOCK_CLEAN)]                 # и в обратном порядке
    items, raw, _ = asyncio.run(rh.capture(None, seconds=10))
    assert items["Display"]["неизвестная"] and not items["Battery"]["меняли"]


def test_parse_tolerates_new_fields_and_accumulates():
    txt = ('componentName:Battery: componentType:1024: isRepaired:0: isUsed:0: repairDate:(null):"\n'
           'componentName:Battery: componentType:1024: isRepaired:1: isUsed:0: repairDate:2026-02-02:"\n'
           'componentName:Battery: componentType:1024: isRepaired:0: isUsed:0: repairDate:(null):"\n'
           'componentName:Display: componentType:1025: isRepaired:0: isUsed:0: isUnknownPart:1: repairDate:(null):"\n'
           'componentName:Camera: componentType:1026: isRepaired:0: isUsed:0: isGenuine:1: repairDate:(null):"\n')
    items = rh.parse(txt)
    assert items["Battery"]["меняли"] and items["Battery"]["дата"] == "2026-02-02"   # поздняя пустая строка не снимает флаг
    assert items["Display"]["неизвестная"] and items["Display"]["меняли"] and items["Display"]["поля"] == {"isUnknownPart": "1"}
    assert not items["Camera"]["меняли"] and items["Camera"]["поля"] == {"isGenuine": "1"}
    assert rh.signature(items) != rh.signature({})


def test_wait_change_sees_late_update(fake):
    """После первого вердикта телефон допечатал записи с заменой — wait_change это замечает."""
    fake.script = [list(BLOCK_CLEAN) + ["DROP"], list(BLOCK)]

    async def scenario():
        lst = rh.Listener(None, reconnect_delay=1.5)            # вторая печать — через 1,5 с, после первого wait
        await lst.start()
        items, _, _ = await lst.wait(10, grace=0.1, settle=0.2)
        seen = rh.signature(items)
        deadline = asyncio.get_running_loop().time() + 8
        items2, _, waited = await lst.wait_change(seen, grace=0.1,
                                                  keep_going=lambda: asyncio.get_running_loop().time() < deadline)
        await lst.stop()
        return items, items2, waited

    items, items2, waited = asyncio.run(scenario())
    assert not items["Display"]["меняли"] and items2["Display"]["меняли"] and items2["Display"]["бу"] and waited < 10


def test_report_uses_seal_verdict_for_face_id_and_unknown_part_is_stop():
    import os, json
    from pintel_core.devicelink import snapshot
    from pintel_core.analysis import report as report_mod
    HERE = os.path.dirname(os.path.abspath(__file__))
    snap = snapshot.loads(open(os.path.join(HERE, "fixtures_real", "iphone17pro_anon.snapshot.json"), encoding="utf-8").read())
    meta = {"раздел_открыт": True, "дельта": [], "rchl_байт": 0, "печать": {}, "формат": "сверка с заводской печатью (iOS 18)"}
    snap["repair_history"] = rh.synthesize(meta)
    snap["repair_history_meta"] = meta
    rep = report_mod.build(snap)
    assert rep["сигналы"]["Face ID ↔ плата"]["ок"] is True and rep["apple_история_источник"].startswith("сверка")
    assert rep["итог"]["вердикт"] != "ПРОВЕРКА НЕПОЛНАЯ"
    meta["дельта"] = ["Display"]
    snap["repair_history"] = rh.synthesize(meta)
    rep = report_mod.build(snap)
    assert any("неизвестного происхождения" in x for x in rep["стоп"]) and rep["итог"]["вердикт"] == "ПРОБЛЕМНЫЙ"


# ---------------------------------------------------------------- проверка компонентов (iOS 26)
# Значения сверены на двух живых аппаратах: чистый iPhone 14 Pro (iOS 26.5) и iPhone 15 Pro
# с «Неизвестно» на экране (iOS 26.6.1). Это единственный известный канал, который даёт
# вердикт Apple по деталям, поэтому его смысл закреплён тестами подетально.
CLEAN_14PRO = (
    'Oct 27 19:35:24 iPhone Preferences(CoreRepairKit)[2093] <Notice>: systemhealth {\n'
    '    Audio = 1;\n    AudioCodec = 1;\n    BackGlass = 0;\n    Baseband = 1;\n    Battery = 1;\n'
    '    Bluetooth = 1;\n    Camera = 1;\n    CoverGlass = 0;\n    Display = 1;\n    Enclosure = 0;\n'
    '    FaceID = 1;\n    MTUB = 0;\n    NFC = 1;\n    RCameraFailed = 1;\n    TouchID = 0;\n'
    '    UWB = 1;\n    VolumeButton = 0;\n    Wifi = 1;\n}\n'
    'Oct 27 19:35:24 iPhone mobilerepaird(CoreRepairCore)[212] <Notice>: component: Display isComponentRepairedUsingRCHL: 0\n'
    'Oct 27 19:35:24 iPhone mobilerepaird[212] <Notice>: Battery Health State{\n'
    '    IOPSBatteryHealthServiceState = 0;\n    IOPSBatteryHealthState = 0;\n}\n')


def test_components_clean_phone_is_a_confirmation():
    """Чистый аппарат: 1 — деталь в порядке, 0 — Apple её у этой модели не отслеживает.
    Ноль не имеет права стать «плохой деталью», иначе чистый телефон получит СТОП зря.
    RCameraFailed = 1 стоит и на чистом аппарате — по нему вердикт не строим."""
    comp = rh.parse_components(CLEAN_14PRO)
    assert set(comp["детали"]) == {"Battery", "Display", "Camera", "FaceID"}
    assert not any(d["меняли"] or d.get("неизвестная") for d in comp["детали"].values())
    for ноль in ("BackGlass", "CoverGlass", "Enclosure", "MTUB", "TouchID", "VolumeButton"):
        assert ноль not in comp["детали"], ноль
    assert "RCamera" not in comp["детали"] and "RCameraFailed" not in comp["детали"]
    assert comp["аккумулятор"]["IOPSBatteryHealthServiceState"] == 0       # обслуживание не требуется


def test_components_minus_one_is_stop():
    """iPhone 15 Pro: Display = "-1" — на экране телефона «Неизвестно», для выкупа это СТОП."""
    comp = rh.parse_components(CLEAN_14PRO.replace("    Display = 1;", '    Display = "-1";'))
    assert comp["детали"]["Display"]["неизвестная"] and comp["детали"]["Display"]["меняли"]
    assert not comp["детали"]["Battery"]["меняли"]                         # соседние детали не задеты


def test_battery_health_alone_is_not_a_verdict():
    """iOS 18 пишет состояние аккумулятора всегда. Одна эта строка не имеет права
    выдать себя за проверку компонентов — иначе любой открытый экран станет «вердиктом»."""
    only_battery = ('Oct 27 19:35:24 iPhone mobilerepaird[212] <Notice>: Battery Health State{\n'
                    '    IOPSBatteryHealthServiceState = 1;\n    IOPSBatteryHealthState = 3;\n}\n')
    comp = rh.parse_components(only_battery)
    assert comp["аккумулятор"] and not comp["детали"]
