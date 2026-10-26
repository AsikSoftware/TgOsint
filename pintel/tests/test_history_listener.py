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
