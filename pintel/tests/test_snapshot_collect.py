# -*- coding: utf-8 -*-
"""Слепок телефона: связь оборвалась — чтение останавливается сразу; про память спрашивают
один раз и только когда просят.

Шаг «Модель и память» на точках зависал по двум причинам (журналы касс за 30 дней, 17.11.2026):
обрыв USB посреди чтения — и тогда слепок по три раза с паузами стучался в мёртвое соединение
за каждым из двадцати узлов, 1,5–3,5 минуты; и телефон, который долго считает ответ про
занятую память. Здесь — проверки на подставном телефоне, без кабеля.
"""
import asyncio
import os

import pytest

from pintel_core.analysis import report as report_mod
from pintel_core.analysis import storage
from pintel_core.devicelink import snapshot

HERE = os.path.dirname(os.path.abspath(__file__))
ДИСК = snapshot.ДОМЕН_ДИСКА


def _слепок():
    return snapshot.loads(open(os.path.join(HERE, "fixtures_real", "iphone12_ios26_anon.snapshot.json"),
                               encoding="utf-8").read())


class Телефон:
    """Подставные lockdown и диагностика поверх настоящего слепка. `оборвать_после` — на каком
    по счёту чтении связь рвётся насовсем; `моргнуть_на` — одно чтение срывается, дальше всё идёт."""

    def __init__(self, оборвать_после=None, моргнуть_на=None):
        self.snap = _слепок()
        self.чтений, self.домены = 0, []
        self.оборвать_после, self.моргнуть_на = оборвать_после, моргнуть_на

    def _шаг(self):
        self.чтений += 1
        if self.оборвать_после is not None and self.чтений > self.оборвать_после:
            raise ConnectionAbortedError("ConnectionTerminatedError: usbmux has no device")
        if self.чтений == self.моргнуть_на:
            raise ConnectionAbortedError("ConnectionTerminatedError: blink")

    # lockdown
    async def get_value(self, domain=None, key=None):
        self._шаг()
        if key:
            return (self.snap["root"] or {}).get(key)
        if domain:
            self.домены.append(domain)
            return (self.snap["domains"] or {}).get(domain)
        return self.snap["root"]

    # диагностика
    async def ioregistry(self, plane=None, name=None, ioclass=None):
        self._шаг()
        if plane:
            return (self.snap.get("ioreg_planes") or {}).get(plane)
        if name:
            узлы, кач = self.snap.get("nodes") or {}, self.snap.get("quality") or {}
            # камера, память и датчик приближения лежат в слепке под своими ролями, а телефон
            # отдаёт их по именам узлов — имена записаны рядом, в quality
            по_имени = {кач.get(f"{роль}_узел"): узлы.get(роль) for роль in ("nvme", "camera", "prox")}
            return по_имени.get(name) or узлы.get(name)
        return None


@pytest.fixture
def тихо(monkeypatch):
    """MobileGestalt, джейлбрейк, паника и MDM — отдельные службы со своими тестами."""
    async def mg(diag, serial=None):
        return {"значения": {}, "канал": "нет"}

    async def пусто(ld):
        return {}
    monkeypatch.setattr(snapshot.mg_mod, "read", mg)
    monkeypatch.setattr(snapshot.jailbreak, "probe", пусто)
    monkeypatch.setattr(snapshot.panic, "probe", пусто)
    monkeypatch.setattr(snapshot.mdm, "probe", пусто)

    async def без_пауз(секунд):
        return None
    monkeypatch.setattr(snapshot.asyncio, "sleep", без_пауз)


def test_the_kiosk_snapshot_does_not_ask_about_memory_at_all(тихо):
    """Касса читает слепок с `память=False`: домен диска не трогается, свободное место никого
    не задерживает. Объём при этом известен — с контроллера NVMe."""
    т = Телефон()
    snap = asyncio.run(snapshot.collect(т, т, память=False))
    assert ДИСК not in т.домены and ДИСК not in snap["domains"]
    assert snap["quality"]["не_прочиталось"].get(ДИСК) is None
    rep = report_mod.build(snap)
    assert rep["память"]["объём_гб"] == 64 and rep["память"]["диск_гб"] is None
    assert rep["паспорт"]["модель"] == "iPhone 12"


def test_memory_is_asked_once_not_twice(тихо):
    """Без кассы (доктор) память читается здесь же — но один раз. Раньше домен читали дважды с
    паузой, и на iOS 27 второй ответ каждый раз шёл по 20 секунд."""
    т = Телефон()
    snap = asyncio.run(snapshot.collect(т, т))
    assert т.домены.count(ДИСК) == 1 and т.домены[-1] == ДИСК, "память — один раз и последней"
    assert snap["domains"][ДИСК]["TotalDiskCapacity"] and snap["quality"]["устарело"] == []
    assert report_mod.build(snap)["память"]["диск_гб"] == 64


def test_a_dead_link_stops_the_reading_at_once(тихо):
    """Связь оборвалась на пятом чтении. Раньше слепок шёл до конца: по три попытки с паузами
    на каждый из двадцати узлов. Теперь — два сорвавшихся чтения, проба, и `СвязьПропала`."""
    т = Телефон(оборвать_после=5)
    with pytest.raises(snapshot.СвязьПропала):
        asyncio.run(snapshot.collect(т, т, память=False))
    assert т.чтений <= 5 + 3, f"после обрыва сделано ещё {т.чтений - 5} чтений"


def test_a_single_blink_is_reread_and_the_snapshot_goes_on(тихо):
    """Одно сорвавшееся чтение — не обрыв: его перечитывают, слепок доходит до конца."""
    т = Телефон(моргнуть_на=1)                               # сорвалось самое первое чтение — паспорт
    snap = asyncio.run(snapshot.collect(т, т, память=False))
    assert snap["root"]["ProductType"] and snap["quality"]["повторы"].get("root") == 2
    assert report_mod.build(snap)["паспорт"]["модель"] == "iPhone 12"


def test_a_cancelled_reading_stops_between_reads(тихо):
    """Чтение отменили — оно останавливается на ближайшем шаге, а не дочитывает телефон."""
    т = Телефон()
    with pytest.raises(snapshot.Остановлено):
        asyncio.run(snapshot.collect(т, т, жив=lambda: т.чтений < 4, память=False))
    assert т.чтений <= 5


def test_capacity_comes_from_the_controller_when_the_disk_is_silent():
    """Телефон про память не ответил — объём берём с контроллера NVMe: его ёмкость, а нет её —
    число из номера модели. Сверка «объём сошёлся» тогда идёт только между ними."""
    nvme = _слепок()["nodes"]["nvme"]
    без_диска = storage.analyze(None, nvme)
    assert без_диска["объём_гб"] == 64 and без_диска["диск_гб"] is None and без_диска["занято_гб"] is None
    с_диском = storage.analyze(_слепок()["domains"][ДИСК], nvme)
    assert с_диском["объём_гб"] == 64 and с_диском["диск_гб"] == 64 and с_диском["объём_сошёлся"] is True
    assert storage.analyze(None, None)["объём_гб"] is None        # ни диска, ни контроллера — не выдумываем


def test_the_side_read_puts_the_answer_into_the_snapshot_or_says_it_did_not_wait(тихо):
    """`ЧтениеДиска` — вопрос про память в стороне от слепка: пришёл ответ — он в слепке вместе с
    разбором NANDInfo; не пришёл за отведённое время — в слепке записано, сколько ждали."""
    полный = _слепок()

    class Соединение:
        def __init__(self, ждать):
            self.ждать, self.закрыто = ждать, False

        async def get_value(self, domain=None, key=None):
            await asyncio.wait_for(asyncio.Event().wait(), self.ждать) if self.ждать else None
            return полный["domains"][ДИСК]

        async def close(self):
            self.закрыто = True

    async def прогон(ждать_телефон, ждать_касса):
        т = Телефон()
        snap = await snapshot.collect(т, т, память=False)
        соединение = Соединение(ждать_телефон)

        async def соединить():
            return соединение
        чтение = snapshot.ЧтениеДиска(соединить)
        пришло = await чтение.вложить(snap, ждать=ждать_касса)
        await чтение.закрыть()
        return пришло, snap, соединение

    пришло, snap, соединение = asyncio.run(прогон(0, 1.0))
    assert пришло and snap["domains"][ДИСК]["TotalDiskCapacity"] and соединение.закрыто
    assert snap["nand_summary"].get("записей") and "память_не_дождались_с" not in snap["quality"]

    пришло, snap, соединение = asyncio.run(прогон(30, 0.05))
    assert not пришло and ДИСК not in snap["domains"] and соединение.закрыто
    assert snap["quality"]["память_не_дождались_с"] >= 0
    rep = report_mod.build(snap)
    assert rep["память"]["объём_гб"] == 64 and any("не ответил про память" in x for x in rep["служебное"])
