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
