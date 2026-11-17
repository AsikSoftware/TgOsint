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


# ---------------------------------------------------------------- ни один вопрос не держит чтение
#
# Боевые слепки за месяц (17.11.2026): всё чтение телефона — 2–4 секунды, из них домены — 0,1–0,3.
# Но у части телефонов этап «домены» шёл 45, 195 секунд: один из двадцати трёх вопросов телефон
# обдумывал минутами, а касса ждала его без предела — это и было зависание шага «Модель и
# память». Владелец заметил, что так бывает, когда телефон при подключении включает режим модема.

ЗАВИСАЕТ = "com.apple.mobile.data_sync"          # для теста годится любой не важный отчёту домен
ПОЗДНИЙ = "com.apple.mobile.battery"             # важный отчёту домен, который есть в слепке-образце


class Боковое:
    """Ещё одно соединение с тем же подставным телефоном. На домены из `молчит` не отвечает,
    пока не разрешат (`отпустить`); остальное отдаёт сразу."""

    def __init__(self, телефон, молчит=(), отпустить=None):
        self.т, self.молчит, self.отпустить = телефон, set(молчит), отпустить
        self.спрошено, self.закрыто = [], False

    async def get_value(self, domain=None, key=None):
        self.спрошено.append(domain or key or "root")
        if domain in self.молчит:
            await (self.отпустить or asyncio.Event()).wait()
        return (self.т.snap["domains"] or {}).get(domain) if domain else self.т.snap["root"]

    async def close(self):
        self.закрыто = True


def _боковые(телефон, молчит=(), отпустить=None, не_открывается_с=None):
    """`соединить` для collect и список соединений, которые он выдал."""
    выданы = []

    async def соединить():
        if не_открывается_с is not None and len(выданы) >= не_открывается_с:
            raise ConnectionRefusedError("usbmuxd rejected the Connect request")
        выданы.append(Боковое(телефон, молчит, отпустить))
        return выданы[-1]
    return соединить, выданы


@pytest.fixture
def скоро(monkeypatch):
    """Пределы ожидания — доли секунды: тест проверяет порядок действий, а не секундомер."""
    monkeypatch.setattr(snapshot, "ЖДАТЬ_ВАЖНЫЙ_ДОМЕН", 0.05)
    monkeypatch.setattr(snapshot, "ЖДАТЬ_ДОМЕН", 0.05)
    monkeypatch.setattr(snapshot, "ЖДАТЬ_СОЕДИНЕНИЕ", 0.5)


def test_domains_are_asked_on_a_side_connection_never_on_the_main_one(тихо, скоро):
    """С боковым соединением общее про домены не спрашивают вовсе: на нём потом работают
    диагностика, журнал и службы, и зависший на нём вопрос отравил бы всё остальное."""
    т = Телефон()
    соединить, выданы = _боковые(т)
    snap = asyncio.run(snapshot.collect(т, т, память=False, соединить=соединить))
    assert т.домены == [], "домены спрошены на общем соединении"
    assert len(выданы) == 1 and выданы[0].закрыто, "боковое соединение одно и закрыто за собой"
    полный = _слепок()["domains"]
    for домен in snapshot.ВАЖНЫЕ_ДОМЕНЫ:
        assert snap["domains"].get(домен) == полный.get(домен), домен
    assert выданы[0].спрошено[:2] == ["com.apple.mobile.battery", "com.apple.fmip"], "важное — первым"
    assert ДИСК not in выданы[0].спрошено
    assert "зависшие_домены" not in snap["quality"]
    assert report_mod.build(snap)["паспорт"]["модель"] == "iPhone 12"


def test_a_question_the_phone_never_answers_does_not_hold_the_reading(тихо, скоро):
    """Главное: телефон молчит на один вопрос — чтение идёт дальше и доходит до конца, а в
    слепке записано, какой домен молчал. Раньше касса ждала его без предела."""
    т = Телефон()
    соединить, выданы = _боковые(т, молчит=[ЗАВИСАЕТ])

    async def прогон():
        поздние = snapshot.ПоздниеДомены()
        try:
            return await asyncio.wait_for(
                snapshot.collect(т, т, память=False, соединить=соединить, поздние=поздние), 5), len(поздние)
        finally:
            await поздние.закрыть()
    snap, ждут = asyncio.run(прогон())
    кач = snap["quality"]
    assert list(кач["зависшие_домены"]) == [ЗАВИСАЕТ] and ждут == 1
    # отчёту этот домен не нужен — проверка из-за него неполной не становится, автоцена остаётся
    assert ЗАВИСАЕТ not in кач["не_прочиталось"]
    assert т.домены == [], "после зависшего вопроса на общее соединение не перешли"
    assert len(выданы) == 2, "после зависшего вопроса — новое боковое соединение"
    после = выданы[1].спрошено
    assert "com.apple.fairplay" in после and ЗАВИСАЕТ not in после, "остальные домены дочитаны"
    assert all(с.закрыто for с in выданы)
    rep = report_mod.build(snap)
    assert rep["паспорт"]["модель"] == "iPhone 12" and rep["правовой"]["найти_iphone"] != "не определился"
    assert not any("не прочиталась" in x for x in rep["не_прочиталось"]), rep["не_прочиталось"]
    assert any("не ответил вовремя" in x and "mobile.data_sync" in x for x in rep["служебное"]), rep["служебное"]


def test_a_silent_domain_the_report_needs_makes_the_check_incomplete(тихо, скоро):
    """Молчит домен, из которого отчёт что-то берёт, — это уже незнание о телефоне: проверка
    неполная, автоцены нет. Сомнение — не зелёный. Причина названа словами, и это не «обрыв»:
    перечитывать по кругу и ждать телефон заново из-за неё не нужно."""
    т = Телефон()
    соединить, выданы = _боковые(т, молчит=[ПОЗДНИЙ])
    snap = asyncio.run(snapshot.collect(т, т, память=False, соединить=соединить))
    почему = snap["quality"]["не_прочиталось"][ПОЗДНИЙ]
    assert почему.startswith(snapshot.НЕ_ОТВЕТИЛ) and not snapshot._обрыв(почему)
    assert ПОЗДНИЙ in snap["quality"]["зависшие_домены"]
    rep = report_mod.build(snap)
    assert any("не прочиталась" in x for x in rep["не_прочиталось"]), rep["не_прочиталось"]


def test_a_late_answer_is_picked_up_at_the_end_of_the_check(тихо, скоро):
    """Вопрос остался ждать на своём соединении. Ответ пришёл, пока шла остальная проверка, —
    касса кладёт его в слепок и снимает пометку «не ответил»."""
    т = Телефон()

    async def прогон(ответит):
        отпустить = asyncio.Event()
        соединить, выданы = _боковые(т, молчит=[ПОЗДНИЙ], отпустить=отпустить)
        поздние = snapshot.ПоздниеДомены()
        snap = await snapshot.collect(т, т, память=False, соединить=соединить, поздние=поздние)
        assert ПОЗДНИЙ not in snap["domains"]
        if ответит:
            отпустить.set()
        пришли = await поздние.вложить(snap, ждать=0.3)
        await поздние.закрыть()
        return snap, пришли, выданы

    snap, пришли, выданы = asyncio.run(прогон(True))
    assert пришли == [ПОЗДНИЙ] and snap["domains"][ПОЗДНИЙ]
    assert ПОЗДНИЙ not in snap["quality"]["не_прочиталось"]
    assert "зависшие_домены" not in snap["quality"] and ПОЗДНИЙ in snap["quality"]["поздние_домены"]
    assert all(с.закрыто for с in выданы)

    snap, пришли, выданы = asyncio.run(прогон(False))
    assert пришли == [] and ПОЗДНИЙ not in snap["domains"]
    assert ПОЗДНИЙ in snap["quality"]["зависшие_домены"], "сколько молчал — записано"
    assert all(с.закрыто for с in выданы), "брошенный вопрос закрывает своё соединение"
    # отчёту это не мешает: главный ответ про «Найти iPhone» лежит в корневом домене
    assert report_mod.build(snap)["правовой"]["найти_iphone"] in ("включён", "выключен")


def test_a_phone_that_answers_nothing_is_not_asked_twenty_times(тихо, скоро):
    """Три вопроса подряд без ответа — телефон занят собой: остальные не задаём, иначе
    двадцать вопросов по два предела снова сложились бы в минуту ожидания."""
    т = Телефон()
    все = [d for d in snapshot.DOMAINS if d != ДИСК]
    соединить, выданы = _боковые(т, молчит=все)
    snap = asyncio.run(snapshot.collect(т, т, память=False, соединить=соединить))
    кач = snap["quality"]
    assert len(кач["зависшие_домены"]) == snapshot.ЗАВИСШИХ_НЕ_БОЛЬШЕ == len(выданы)
    не_спрашивали = ([d for d, почему in кач["не_прочиталось"].items() if почему.startswith("не спрашивали")]
                     + кач["домены_не_спрашивали"])
    assert len(не_спрашивали) == len(все) - snapshot.ЗАВИСШИХ_НЕ_БОЛЬШЕ
    assert not set(кач["домены_не_спрашивали"]) & set(snapshot.ВАЖНЫЕ_ДОМЕНЫ)
    assert т.домены == [] and all(с.закрыто for с in выданы)
    assert report_mod.build(snap)["паспорт"]["модель"] == "iPhone 12", "паспорт и узлы прочитаны"


def test_without_a_side_connection_only_what_the_report_needs_is_asked(тихо, скоро):
    """Второе соединение не открылось вовсе — на общем спрашиваем только то, что нужно отчёту
    (четыре домена, а не двадцать три), и это записано в слепке."""
    т = Телефон()
    соединить, выданы = _боковые(т, не_открывается_с=0)
    snap = asyncio.run(snapshot.collect(т, т, память=False, соединить=соединить))
    assert выданы == [] and sorted(т.домены) == sorted(snapshot.ВАЖНЫЕ_ДОМЕНЫ)
    assert "ConnectionRefusedError" in snap["quality"]["боковое_соединение"]
    assert "com.apple.fairplay" in snap["quality"]["домены_не_спрашивали"]
    assert "com.apple.fairplay" not in snap["quality"]["не_прочиталось"]

    # зависло, а нового соединения уже не дают — на общее с вопросами не идём: зависнет всё
    т = Телефон()
    соединить, выданы = _боковые(т, молчит=["com.apple.mobile.battery"], не_открывается_с=1)
    snap = asyncio.run(snapshot.collect(т, т, память=False, соединить=соединить))
    assert т.домены == [] and len(выданы) == 1
    assert snap["quality"]["не_прочиталось"]["com.apple.fmip"].startswith("не спрашивали")


def test_one_bounded_question_on_its_own_connection(скоро):
    """`спросить_в_стороне` — один вопрос на своём соединении: ответ или причина словами, и
    соединение закрыто в любом случае. Так касса сверяет прошлую проверку с живым телефоном."""
    т = Телефон()

    async def прогон(молчит):
        соединить, выданы = _боковые(т, молчит=молчит)
        ответ, почему = await snapshot.спросить_в_стороне(соединить, домен=ПОЗДНИЙ, ждать=0.05)
        return ответ, почему, выданы
    ответ, почему, выданы = asyncio.run(прогон([]))
    assert ответ == _слепок()["domains"][ПОЗДНИЙ] and почему == "" and выданы[0].закрыто
    ответ, почему, выданы = asyncio.run(прогон([ПОЗДНИЙ]))
    assert ответ is None and почему.startswith(snapshot.НЕ_ОТВЕТИЛ) and выданы[0].закрыто

    async def не_соединить():
        raise ConnectionRefusedError("нет телефона")
    ответ, почему = asyncio.run(snapshot.спросить_в_стороне(не_соединить, домен=ПОЗДНИЙ))
    assert ответ is None and "ConnectionRefusedError" in почему


def test_the_doctor_reads_memory_on_its_own_connection_too(тихо, скоро, monkeypatch):
    """Доктор читает память сам. С боковым соединением — тоже в стороне и с пределом: вопрос
    про память телефон считает когда как."""
    monkeypatch.setattr(snapshot, "ЖДАТЬ_ПАМЯТЬ_ЗДЕСЬ", 0.05)
    т = Телефон()
    соединить, выданы = _боковые(т)
    snap = asyncio.run(snapshot.collect(т, т, соединить=соединить))
    assert т.домены == [] and snap["domains"][ДИСК]["TotalDiskCapacity"]
    assert snap["nand_summary"].get("записей") and report_mod.build(snap)["память"]["диск_гб"] == 64

    т = Телефон()
    соединить, выданы = _боковые(т, молчит=[ДИСК])
    snap = asyncio.run(asyncio.wait_for(snapshot.collect(т, т, соединить=соединить), 5))
    assert ДИСК not in snap["domains"] and snap["quality"]["память_не_дождались_с"] >= 0
    assert all(с.закрыто for с in выданы)
    assert report_mod.build(snap)["память"]["объём_гб"] == 64, "объём — с контроллера"
