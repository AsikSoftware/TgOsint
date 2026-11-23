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
import types

import pytest

from pintel_core.analysis import report as report_mod
from pintel_core.analysis import storage
from pintel_core.devicelink import snapshot

HERE = os.path.dirname(os.path.abspath(__file__))
ДИСК = snapshot.ДОМЕН_ДИСКА

_ПЕТЛЯ = []                # петля текущего теста: её ставит и убирает фикстура `своя_петля`


@pytest.fixture(autouse=True)
def своя_петля():
    """Своя петля событий на тест, и уборка остатков — С ПРЕДЕЛОМ.

    Вопрос, который телефон обдумывает, остаётся живой задачей нарочно: ответ подберут позже.
    Поэтому после теста в петле почти всегда что-то живо. `asyncio.run` снимает такие остатки
    без предела — и 19.11.2026 сборка Windows встала ровно в этой уборке и шла в тупике 17
    минут, до обрыва шага по времени. Здесь остатки снимаются с пределом: зависший остаток
    портит один тест, а не всю сборку.
    """
    петля = asyncio.new_event_loop()
    asyncio.set_event_loop(петля)
    _ПЕТЛЯ.append(петля)
    try:
        yield петля
    finally:
        _ПЕТЛЯ.pop()
        остатки = [з for з in asyncio.all_tasks(петля) if not з.done()]
        for з in остатки:
            з.cancel()
        if остатки:
            петля.run_until_complete(asyncio.wait(остатки, timeout=5))
        петля.close()
        asyncio.set_event_loop(None)


def прогнать(корутина):
    """Прогнать корутину в петле теста — вместо `asyncio.run` (см. `своя_петля`)."""
    if _ПЕТЛЯ:
        return _ПЕТЛЯ[-1].run_until_complete(корутина)
    return asyncio.run(корутина)


def _слепок():
    return snapshot.loads(open(os.path.join(HERE, "fixtures_real", "iphone12_ios26_anon.snapshot.json"),
                               encoding="utf-8").read())


class Телефон:
    """Подставные lockdown и диагностика поверх настоящего слепка. `оборвать_после` — на каком
    по счёту чтении связь рвётся насовсем; `моргнуть_на` — одно чтение срывается, дальше всё идёт."""

    def __init__(self, оборвать_после=None, моргнуть_на=None, молчит_о=()):
        self.snap = _слепок()
        self.чтений, self.домены = 0, []
        self.оборвать_после, self.моргнуть_на = оборвать_после, моргнуть_на
        # о чём телефон не отвечает вовсе: имя домена, имя узла, «root» или план IOService
        self.молчит_о = set(молчит_о)

    def _шаг(self):
        self.чтений += 1
        if self.оборвать_после is not None and self.чтений > self.оборвать_после:
            raise ConnectionAbortedError("ConnectionTerminatedError: usbmux has no device")
        if self.чтений == self.моргнуть_на:
            raise ConnectionAbortedError("ConnectionTerminatedError: blink")

    # lockdown
    async def get_value(self, domain=None, key=None):
        self._шаг()
        if (domain or ("root" if not key else key)) in self.молчит_о:
            await asyncio.Event().wait()                   # ответа не будет никогда
        if key:
            return (self.snap["root"] or {}).get(key)
        if domain:
            self.домены.append(domain)
            return (self.snap["domains"] or {}).get(domain)
        return self.snap["root"]

    # диагностика
    async def ioregistry(self, plane=None, name=None, ioclass=None):
        self._шаг()
        if (plane or name or ioclass) in self.молчит_о:
            await asyncio.Event().wait()                   # ответа не будет никогда
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
    snap = прогнать(snapshot.collect(т, т, память=False))
    assert ДИСК not in т.домены and ДИСК not in snap["domains"]
    assert snap["quality"]["не_прочиталось"].get(ДИСК) is None
    rep = report_mod.build(snap)
    assert rep["память"]["объём_гб"] == 64 and rep["память"]["диск_гб"] is None
    assert rep["паспорт"]["модель"] == "iPhone 12"


def test_memory_is_asked_once_not_twice(тихо):
    """Без кассы (доктор) память читается здесь же — но один раз. Раньше домен читали дважды с
    паузой, и на iOS 27 второй ответ каждый раз шёл по 20 секунд."""
    т = Телефон()
    snap = прогнать(snapshot.collect(т, т))
    assert т.домены.count(ДИСК) == 1 and т.домены[-1] == ДИСК, "память — один раз и последней"
    assert snap["domains"][ДИСК]["TotalDiskCapacity"] and snap["quality"]["устарело"] == []
    assert report_mod.build(snap)["память"]["диск_гб"] == 64


def test_a_dead_link_stops_the_reading_at_once(тихо):
    """Связь оборвалась на пятом чтении. Раньше слепок шёл до конца: по три попытки с паузами
    на каждый из двадцати узлов. Теперь — два сорвавшихся чтения, проба, и `СвязьПропала`."""
    т = Телефон(оборвать_после=5)
    with pytest.raises(snapshot.СвязьПропала):
        прогнать(snapshot.collect(т, т, память=False))
    assert т.чтений <= 5 + 3, f"после обрыва сделано ещё {т.чтений - 5} чтений"


def test_a_single_blink_is_reread_and_the_snapshot_goes_on(тихо):
    """Одно сорвавшееся чтение — не обрыв: его перечитывают, слепок доходит до конца."""
    т = Телефон(моргнуть_на=1)                               # сорвалось самое первое чтение — паспорт
    snap = прогнать(snapshot.collect(т, т, память=False))
    assert snap["root"]["ProductType"] and snap["quality"]["повторы"].get("root") == 2
    assert report_mod.build(snap)["паспорт"]["модель"] == "iPhone 12"


def test_a_cancelled_reading_stops_between_reads(тихо):
    """Чтение отменили — оно останавливается на ближайшем шаге, а не дочитывает телефон."""
    т = Телефон()
    with pytest.raises(snapshot.Остановлено):
        прогнать(snapshot.collect(т, т, жив=lambda: т.чтений < 4, память=False))
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

    пришло, snap, соединение = прогнать(прогон(0, 1.0))
    assert пришло and snap["domains"][ДИСК]["TotalDiskCapacity"] and соединение.закрыто
    assert snap["nand_summary"].get("записей") and "память_не_дождались_с" not in snap["quality"]

    пришло, snap, соединение = прогнать(прогон(30, 0.05))
    assert not пришло and ДИСК not in snap["domains"] and соединение.закрыто
    assert snap["quality"]["память_не_дождались_с"] >= 0
    rep = report_mod.build(snap)
    assert rep["память"]["объём_гб"] == 64 and any("не ответил про память" in x for x in rep["служебное"])


# ---------------------------------------------------------------- собираем ВСЁ и не вешаем проверку
#
# Боевые слепки за месяц (17.11.2026): всё чтение телефона — 2–4 секунды, из них все 23 домена
# lockdown — 0,1–0,3 с. Но у части телефонов этап «домены» шёл 45 и 195 секунд: один вопрос из
# двадцати трёх телефон обдумывал минутами, а касса ждала его без предела — это и было
# зависание шага «Модель и память». Владелец заметил, что так бывает, когда телефон при
# подключении включает режим модема.
#
# Требование владельца: собрать ВСЁ, ничего не потерять, не висеть и не падать. Поэтому здесь
# проверяется ровно это: ни один вопрос не держит чтение, ни один вопрос не выбрасывается, и
# ответ, который телефон додумал позже, доходит до слепка.

ЗАВИСАЕТ = "com.apple.mobile.data_sync"          # есть в слепке-образце и отчёту не нужен
ПОЗДНИЙ = "com.apple.mobile.battery"             # тоже есть в образце
БЕЗ_ДИСКА = [d for d in snapshot.DOMAINS if d != ДИСК]


class Боковое:
    """Боковое соединение с подставным телефоном.

    `молчит` — домены, ответа на которые не будет (пока не разрешит `отпустить`);
    `срывается` — {домен: сколько первых раз ответить ошибкой}; счётчик общий на все
    соединения, иначе перезапрос на новом соединении срывался бы вечно."""

    def __init__(self, телефон, журнал, молчит, срывается, отпустить):
        self.т, self.журнал = телефон, журнал
        self.молчит, self.срывается, self.отпустить = молчит, срывается, отпустить
        self.спрошено, self.закрыто = [], False

    async def get_value(self, domain=None, key=None):
        self.спрошено.append(domain)
        self.журнал.append(domain)
        if self.срывается.get(domain):
            self.срывается[domain] -= 1
            raise ConnectionResetError("ConnectionTerminatedError: соединение сорвалось")
        if domain in self.молчит:
            await (self.отпустить or asyncio.Event()).wait()
        return (self.т.snap["domains"] or {}).get(domain)

    async def close(self):
        self.закрыто = True


def _боковые(телефон, молчит=(), срывается=None, отпустить=None, не_открывается_с=None):
    """→ (соединить, выданные соединения, журнал всех вопросов)."""
    выданы, журнал = [], []
    молчит, срывается = set(молчит), dict(срывается or {})

    async def соединить():
        if не_открывается_с is not None and len(выданы) >= не_открывается_с:
            raise ConnectionRefusedError("usbmuxd rejected the Connect request")
        выданы.append(Боковое(телефон, журнал, молчит, срывается, отпустить))
        return выданы[-1]
    return соединить, выданы, журнал


@pytest.fixture
def скоро(monkeypatch):
    """Пределы — доли секунды: тесты проверяют порядок действий, а не секундомер."""
    monkeypatch.setattr(snapshot, "ЖДАТЬ_ДОМЕН", 0.05)
    monkeypatch.setattr(snapshot, "ЖДАТЬ_СОЕДИНЕНИЕ", 0.3)
    monkeypatch.setattr(snapshot, "ЖДАТЬ_ДОМЕНЫ_В_СЛЕПКЕ", 0.3)
    monkeypatch.setattr(snapshot, "ЖДАТЬ_ОСТАТОК", 0.2)
    monkeypatch.setattr(snapshot, "ЖДАТЬ_ОТВЕТА", 0.3)
    monkeypatch.setattr(snapshot, "ЖДАТЬ_ПАМЯТЬ_ЗДЕСЬ", 0.2)


def _собрать(т, соединить, *, память=False, ждать_остаток=None):
    """Прогнать слепок со сборщиком и вернуть (слепок, сборщик)."""
    async def прогон():
        сбор = snapshot.СборДоменов(соединить, log=lambda *a: None)
        try:
            snap = await asyncio.wait_for(
                snapshot.collect(т, т, память=память, соединить=соединить, сбор=сбор), 20)
            if ждать_остаток is not None:
                await сбор.собрать(snap, ждать=ждать_остаток)
            сбор.итог(snap)
            return snap, сбор
        finally:
            pass
    return прогнать(прогон())


def test_every_domain_is_collected_on_side_connections(тихо, скоро):
    """Обычный телефон: собраны ВСЕ домены, и ни об одном не спрошено по общему соединению —
    на нём работают слепок, диагностика и журнал, и зависший вопрос отравил бы их все."""
    т = Телефон()
    соединить, выданы, журнал = _боковые(т)
    snap, сбор = _собрать(т, соединить)
    assert т.домены == [], "домены спрошены на общем соединении"
    assert sorted(журнал) == sorted(БЕЗ_ДИСКА), "спрошены не все домены"
    assert сбор.осталось() == [] and not сбор.сдались
    полный = _слепок()["domains"]
    for домен, значение in полный.items():
        if домен != ДИСК:
            assert snap["domains"][домен] == значение, домен
    assert журнал[0] in snapshot.ЧИТАЕМЫЕ_ДОМЕНЫ, "те, что читает отчёт, спрашиваем первыми"
    спрашивали = [с for с in выданы if с.спрошено]
    assert len(спрашивали) <= snapshot.ПОТОКОВ_ДОМЕНОВ, "боковых соединений больше, чем рабочих"
    assert all(с.закрыто for с in выданы), "боковые соединения закрыты за собой"
    assert not [d for d in snap["quality"]["не_прочиталось"] if d.startswith("com.apple.")]
    assert "домены_без_ответа" not in snap["quality"]
    assert report_mod.build(snap)["паспорт"]["модель"] == "iPhone 12"


def test_a_question_the_phone_never_answers_does_not_stop_the_others(тихо, скоро):
    """Главное. Телефон не отвечает на один вопрос — остальные двадцать два всё равно
    спрошены и собраны, а чтение не ждёт ни секунды лишней. Раньше после трёх таких вопросов
    касса не спрашивала больше ни об одном домене вовсе — это и была потеря данных."""
    т = Телефон()
    соединить, выданы, журнал = _боковые(т, молчит=[ЗАВИСАЕТ])
    snap, сбор = _собрать(т, соединить)
    assert sorted(set(журнал)) == sorted(БЕЗ_ДИСКА), "спрошены не все домены"
    собрано = set(сбор.ответы)
    assert собрано == set(БЕЗ_ДИСКА) - {ЗАВИСАЕТ}, "часть доменов потеряна"
    assert сбор.осталось() == [ЗАВИСАЕТ] and not сбор.сдались, "вопрос не должен быть брошен"
    # после «итога» это уже «не дождались», а не «ещё ждём» — но вопрос всё ещё в работе,
    # и поздний ответ снимет запись (см. test_a_late_answer_is_folded_in_whenever_it_arrives)
    assert ЗАВИСАЕТ in snap["quality"]["домены_без_ответа"]
    assert ЗАВИСАЕТ not in (snap["quality"].get("ждём_домены") or {}), "две записи об одном домене"
    assert т.домены == [], "после зависшего вопроса на общее соединение не перешли"
    # вопрос остался ждать на СВОЁМ соединении, и по нему больше ничего не спрашивали
    молчащие = [с for с in выданы if ЗАВИСАЕТ in с.спрошено]
    assert len(молчащие) == 1 and молчащие[0].спрошено[-1] == ЗАВИСАЕТ
    assert not молчащие[0].закрыто, "соединение с обдумываемым вопросом рано закрыли"
    rep = report_mod.build(snap)
    assert not any("по кабелю не прочиталась" in x for x in rep["не_прочиталось"]), (
        "домен, которого никто не читает, сделал проверку неполной")
    assert any("так и не ответил" in x for x in rep["служебное"]), rep["служебное"]
    прогнать(сбор.закрыть())
    assert all(с.закрыто for с in выданы)


def test_a_domain_that_failed_is_asked_again_until_it_answers(тихо, скоро):
    """Сорвавшийся вопрос — не потеря: домен спрашивается заново, и ответ доходит до слепка.
    Прежде одного моргнувшего USB хватало, чтобы домен остался непрочитанным."""
    т = Телефон()
    соединить, выданы, журнал = _боковые(т, срывается={ПОЗДНИЙ: 2})
    snap, сбор = _собрать(т, соединить)
    assert журнал.count(ПОЗДНИЙ) == 3, "должно быть две осечки и удачный третий раз"
    assert snap["domains"][ПОЗДНИЙ] == _слепок()["domains"][ПОЗДНИЙ]
    assert сбор.осталось() == [] and ПОЗДНИЙ not in сбор.ошибки
    assert sorted(set(журнал)) == sorted(БЕЗ_ДИСКА), "остальные домены тоже собраны"
    assert not any("по кабелю не прочиталась" in x for x in report_mod.build(snap)["не_прочиталось"])


def test_a_phone_that_answers_nothing_is_still_asked_about_everything(тихо, скоро):
    """Телефон не отвечает ни на один вопрос о себе. Проверка всё равно не висит, но и ни
    один вопрос не пропущен молча: каждый домен спрошен, а чего телефон так и не сказал —
    записано в слепке по имени. На общее соединение при этом НЕ переходим: телефон спрошен и
    думает, а брошенный там вопрос испортил бы всё остальное чтение."""
    т = Телефон()
    соединить, выданы, журнал = _боковые(т, молчит=БЕЗ_ДИСКА)
    # ждём, пока сбор переберёт все домены: 22 вопроса по три попытки на двух соединениях
    snap, сбор = _собрать(т, соединить, ждать_остаток=4.0)
    assert sorted(set(журнал)) == sorted(БЕЗ_ДИСКА), "спрошены не все домены"
    без_ответа = snap["quality"]["домены_без_ответа"]
    assert sorted(без_ответа) == sorted(БЕЗ_ДИСКА) and not snap["domains"]
    assert т.домены == [] and "боковое_соединение_нет" not in snap["quality"]
    assert all(snapshot.НЕ_ОТВЕТИЛ in п or "ответа нет" in п for п in без_ответа.values())
    # ни один из них не делает проверку неполной: их не читает ни Оценка, ни чек, ни экран
    rep = report_mod.build(snap)
    assert not any("по кабелю не прочиталась" in x for x in rep["не_прочиталось"])
    assert rep["паспорт"]["модель"] == "iPhone 12"
    assert any("так и не ответил" in x for x in rep["служебное"])
    прогнать(сбор.закрыть())


def test_a_silent_phone_is_not_asked_forever(тихо, скоро, monkeypatch, своя_петля):
    """Вытесненный ради места вопрос возвращается в очередь — но не по кругу без конца.

    Когда телефон молчит, а мест в парке меньше, чем вопросов, каждый новый вопрос вытесняет
    уже стоящий. Вытеснение нарочно не тратит попытку домена (телефон не виноват, что мест не
    хватило) — и без предела это ходило по кругу: ни один домен не сдавался, очередь не
    кончалась, рабочие жили всегда, и сбор без конца открывал телефону новые соединения. На
    этом же встала уборка `asyncio.run` в сборке Windows 19.11.2026: пока рабочие живы, их
    отмена поднимает новых, и снятие остатков не кончалось вовсе — шаг оборвался по времени.

    Сцена нарочно тесная: одно место в парке и два молчащих домена, чтобы вытеснение шло
    на каждом вопросе. Граница считается по правилам (попытки × вытеснения), а не по
    секундомеру: от скорости машины она не зависит."""
    monkeypatch.setattr(snapshot, "ПАРКОВОК", 1)
    два = БЕЗ_ДИСКА[:2]
    т = Телефон()
    соединить, выданы, журнал = _боковые(т, молчит=два)

    async def прогон():
        сбор = snapshot.СборДоменов(соединить, log=lambda *a: None)
        сбор.начать(два)
        await сбор.собрать(ждать=2.0)
        return сбор
    сбор = прогнать(прогон())

    предел = len(два) * (snapshot.ПОПЫТОК_ДОМЕНА + snapshot.ВЫТЕСНЕНИЙ_БЕЗ_ПОПЫТКИ)
    assert len(журнал) <= предел, (
        f"вопросов задано {len(журнал)}, больше {предел}: вытеснение ходит по кругу")
    assert сбор.сдались, "ни один домен не сдался — попытки не тратятся, спрашивать будем вечно"
    assert sorted(set(журнал)) == sorted(два), "спрошены не оба домена"
    # после закрытия не остаётся ни одной живой задачи — ни рабочего, ни вопроса в парке
    прогнать(сбор.закрыть())
    живые = [з for з in asyncio.all_tasks(своя_петля) if not з.done()]
    assert живые == [], f"после закрытия остались задачи: {живые}"
    assert all(с.закрыто for с in выданы), "соединения закрыты за собой"


def test_a_late_answer_is_folded_in_whenever_it_arrives(тихо, скоро):
    """Телефон додумал ответ позже — он попадает в слепок, и пометка «не ответил» снимается.
    Так касса добирает остаток и после того, как отчёт уже показан: телефон на кабеле."""
    async def прогон():
        т = Телефон()
        отпустить = asyncio.Event()
        соединить, выданы, журнал = _боковые(т, молчит=[ПОЗДНИЙ], отпустить=отпустить)
        сбор = snapshot.СборДоменов(соединить, log=lambda *a: None)
        snap = await snapshot.collect(т, т, память=False, соединить=соединить, сбор=сбор)
        сбор.итог(snap)
        assert ПОЗДНИЙ not in snap["domains"] and ПОЗДНИЙ in snap["quality"]["домены_без_ответа"]
        отпустить.set()                                  # телефон додумал
        пришли = await сбор.собрать(snap, ждать=1.0)
        сбор.итог(snap)
        await сбор.закрыть()
        return snap, пришли, выданы
    snap, пришли, выданы = прогнать(прогон())
    assert пришли == [ПОЗДНИЙ] and snap["domains"][ПОЗДНИЙ] == _слепок()["domains"][ПОЗДНИЙ]
    assert "домены_без_ответа" not in snap["quality"] and "ждём_домены" not in snap["quality"]
    assert all(с.закрыто for с in выданы), "соединения закрыты за собой"


def test_a_second_reading_keeps_what_was_already_collected(тихо, скоро):
    """Связь оборвалась, и слепок читается заново. Собранные домены при этом не выбрасываются:
    аппарат тот же, а спрашивать его дважды — лишние секунды на кабеле."""
    async def прогон():
        т = Телефон()
        соединить, выданы, журнал = _боковые(т)
        сбор = snapshot.СборДоменов(соединить, log=lambda *a: None)
        snap1 = await snapshot.collect(т, т, память=False, соединить=соединить, сбор=сбор)
        было = len(журнал)
        snap2 = await snapshot.collect(т, т, память=False, соединить=соединить, сбор=сбор)
        await сбор.закрыть()
        return snap1, snap2, было, len(журнал)
    snap1, snap2, было, стало = прогнать(прогон())
    assert было == len(БЕЗ_ДИСКА) and стало == было, "второе чтение спрашивало телефон заново"
    assert snap2["domains"] == snap1["domains"] and snap2["domains"]


def test_closing_the_collector_leaves_nothing_running(тихо, скоро):
    """После закрытия не остаётся ни открытого соединения, ни живой задачи: иначе прошлая
    проверка держит телефон, пока новая его уже читает, — и обе получают обрывы."""
    async def прогон():
        т = Телефон()
        соединить, выданы, журнал = _боковые(т, молчит=БЕЗ_ДИСКА)
        сбор = snapshot.СборДоменов(соединить, log=lambda *a: None)
        сбор.начать(БЕЗ_ДИСКА)
        await сбор.собрать(ждать=0.2)
        await сбор.закрыть()
        висят = [з for з in asyncio.all_tasks() if з is not asyncio.current_task() and not з.done()]
        return выданы, висят, сбор
    выданы, висят, сбор = прогнать(прогон())
    assert выданы and all(с.закрыто for с in выданы), "соединения не закрыты"
    assert висят == [], f"после закрытия остались задачи: {висят}"
    assert len(сбор) == 0 or сбор.осталось(), "закрытый сбор больше ничего не ждёт"


def test_a_dropped_answer_never_lands_on_another_question(тихо, скоро):
    """Брошенный ответ нельзя читать по тому же соединению: он придёт позже и будет принят за
    ответ на следующий вопрос (в pymobiledevice3 сверяется только имя запроса, «GetValue», а
    не домен). Поэтому соединение с обдумываемым вопросом больше ни для чего не используется."""
    т = Телефон()
    соединить, выданы, журнал = _боковые(т, молчит=[ЗАВИСАЕТ, ПОЗДНИЙ])
    snap, сбор = _собрать(т, соединить)
    for с in выданы:
        зависшие = [d for d in с.спрошено if d in (ЗАВИСАЕТ, ПОЗДНИЙ)]
        if зависшие:
            assert len(зависшие) == 1 and с.спрошено[-1] == зависшие[0], (
                f"по соединению с обдумываемым вопросом спросили ещё: {с.спрошено}")
    # и ни один ответ не встал на место другого
    полный = _слепок()["domains"]
    for домен, значение in snap["domains"].items():
        assert значение == полный[домен], домен
    прогнать(сбор.закрыть())


def test_without_a_second_connection_the_domains_are_read_on_the_main_one(тихо, скоро):
    """Второго соединения телефон не даёт вовсе — домены всё равно собираются, по общему
    соединению и с пределом. «Собрать сколько получилось» не годится: данные нужны все."""
    т = Телефон()
    соединить, выданы, журнал = _боковые(т, не_открывается_с=0)
    snap, сбор = _собрать(т, соединить)
    assert выданы == [] and журнал == []
    assert sorted(т.домены) == sorted(БЕЗ_ДИСКА), "по общему соединению спрошены не все домены"
    assert "ConnectionRefusedError" in snap["quality"]["боковое_соединение_нет"]
    assert snap["domains"][ПОЗДНИЙ] == _слепок()["domains"][ПОЗДНИЙ]
    assert any("второго соединения" in x for x in report_mod.build(snap)["служебное"])


def test_a_silent_domain_on_the_main_connection_restarts_the_reading(тихо, скоро):
    """Второго соединения нет, и телефон молчит на вопрос по общему. Продолжать по этому
    соединению нельзя — брошенный ответ попал бы в следующий вопрос. Поэтому `СвязьПропала`:
    касса перечитает телефон заново, с новым соединением (worker._прочитать_телефон)."""
    т = Телефон(молчит_о=[ЗАВИСАЕТ])
    соединить, выданы, журнал = _боковые(т, не_открывается_с=0)
    with pytest.raises(snapshot.СвязьПропала) as e:
        _собрать(т, соединить)
    assert ЗАВИСАЕТ in str(e.value) and snapshot.НЕ_ОТВЕТИЛ in str(e.value)


def test_a_silent_node_restarts_the_reading_instead_of_hanging(тихо, скоро):
    """Узел или паспорт, на который телефон не отвечает, раньше вешал проверку навсегда:
    своего предела у запроса в pymobiledevice3 нет вовсе, а «три попытки» ограничивают число
    отказов, а не время. Теперь — предел и чтение заново."""
    for молчит in ("root", "AppleSmartBattery", "IOService"):
        т = Телефон(молчит_о=[молчит])
        соединить, _выданы, _журнал = _боковые(т)
        with pytest.raises(snapshot.СвязьПропала) as e:
            _собрать(т, соединить)
        assert snapshot.НЕ_ОТВЕТИЛ in str(e.value), молчит


def test_one_bounded_question_on_its_own_connection(тихо, скоро):
    """`спросить_в_стороне` — один вопрос на своём соединении: ответ или причина словами, и
    соединение закрыто в любом случае. Так касса сверяет прошлую проверку с живым телефоном."""
    т = Телефон()

    async def прогон(молчит):
        соединить, выданы, _ж = _боковые(т, молчит=молчит)
        ответ, почему = await snapshot.спросить_в_стороне(соединить, домен=ПОЗДНИЙ, ждать=0.05)
        return ответ, почему, выданы
    ответ, почему, выданы = прогнать(прогон([]))
    assert ответ == _слепок()["domains"][ПОЗДНИЙ] and почему == "" and выданы[0].закрыто
    ответ, почему, выданы = прогнать(прогон([ПОЗДНИЙ]))
    assert ответ is None and почему.startswith(snapshot.НЕ_ОТВЕТИЛ) and выданы[0].закрыто

    async def не_соединить():
        raise ConnectionRefusedError("нет телефона")
    ответ, почему = прогнать(snapshot.спросить_в_стороне(не_соединить, домен=ПОЗДНИЙ))
    assert ответ is None and "ConnectionRefusedError" in почему


def test_the_doctor_reads_memory_on_its_own_connection_too(тихо, скоро):
    """Доктор читает память сам. С боковым соединением — в стороне и с пределом: ответ про
    память телефон считает когда как, до минут."""
    т = Телефон()
    соединить, выданы, _ж = _боковые(т)
    snap, _сбор = _собрать(т, соединить, память=True)
    assert ДИСК not in т.домены and snap["domains"][ДИСК]["TotalDiskCapacity"]
    assert snap["nand_summary"].get("записей") and report_mod.build(snap)["память"]["диск_гб"] == 64

    т = Телефон()
    соединить, выданы, _ж = _боковые(т, молчит=[ДИСК])
    snap, _сбор = _собрать(т, соединить, память=True)
    assert ДИСК not in snap["domains"] and snap["quality"]["память_не_дождались_с"] >= 0
    assert report_mod.build(snap)["память"]["объём_гб"] == 64, "объём — с контроллера"


# ---------------------------------------------------------------- подключение и диагностика

def test_connecting_and_opening_diagnostics_cannot_hang(monkeypatch):
    """Подключение и служба диагностики тоже должны иметь предел. Без него цикл ожидания
    зависал ВНУТРИ connect() и свой deadline соблюсти не мог: окно кассы оставалось в
    «подключаем телефон» навсегда, и до кнопки «Починить связь» дело не доходило."""
    from pintel_core.devicelink import connect as c
    monkeypatch.setattr(c, "ЖДАТЬ_ПОДКЛЮЧЕНИЕ", 0.05)
    monkeypatch.setattr(c, "ЖДАТЬ_ДИАГНОСТИКУ", 0.05)

    async def без_пауз(секунд):
        return None
    monkeypatch.setattr(c.asyncio, "sleep", без_пауз)

    async def список():
        return c.READY, "", [types.SimpleNamespace(serial="UDID")]

    async def молчит(*a, **k):
        await asyncio.Event().wait()
    monkeypatch.setattr(c, "list_usb", список)
    monkeypatch.setattr(c, "create_using_usbmux", молчит)
    # deadline — абсолютный момент, и нулю он равняться не может: нуль здесь значил бы «без
    # срока» (так в самом цикле: `if deadline and ...`)
    st = прогнать(c.wait_ready(poll=0, deadline=1.0))
    assert st.state == c.ERROR and "не ответил" in st.human

    class Диагностика:
        """Служба диагностики, которая не отвечает ни на подключение, ни на вопрос."""

        def __init__(self, ld, тихо_на):
            self.тихо_на, self.закрыта = тихо_на, False

        async def connect(self):
            if self.тихо_на == "connect":
                await asyncio.Event().wait()

        async def ioregistry(self, name=None, **k):
            if self.тихо_на == "ioregistry":
                await asyncio.Event().wait()
            return {"ok": 1}

        async def close(self):
            self.закрыта = True

    for тихо_на in ("connect", "ioregistry"):
        открытые = []

        def служба(ld, тихо_на=тихо_на):
            открытые.append(Диагностика(ld, тихо_на))
            return открытые[-1]
        monkeypatch.setattr(c, "DiagnosticsService", служба)
        with pytest.raises(RuntimeError) as e:
            прогнать(c.open_diagnostics(object(), attempts=2, delays=(0, 0)))
        assert "не ответила" in str(e.value), тихо_на
        assert открытые and all(д.закрыта for д in открытые), "служба не закрыта после предела"


def test_what_was_read_is_never_thrown_away_when_the_link_breaks(тихо, скоро):
    """Связь оборвалась на середине — прочитанное уезжает вместе с исключением.

    Прежде `collect` держал всё в локальных переменных и собирал слепок только в самом
    конце: обрыв на последнем узле обнулял попытку целиком, а после трёх попыток у кассы не
    оставалось ни слепка, ни отчёта, ни сделки — телефон считался непрочитанным вовсе."""
    # чем позже оборвалась связь, тем больше должно остаться — но паспорт и домены есть всегда
    полнота = []
    for после in (6, 14, 25):   # всего чтений по основному соединению — 30
        т = Телефон(оборвать_после=после)
        соединить, _выданы, _ж = _боковые(т)
        with pytest.raises(snapshot.СвязьПропала) as e:
            _собрать(т, соединить)
        частичный = getattr(e.value, "слепок", None)
        assert частичный, f"прочитанное не уехало с исключением (обрыв после {после})"
        assert (частичный["root"] or {}).get("SerialNumber"), "паспорт потерян"
        assert частичный["domains"], "домены потеряны — их читали на своих соединениях"
        rep = report_mod.build(частичный)
        assert rep["паспорт"]["модель"] == "iPhone 12", "из частичного слепка отчёт не собрался"
        полнота.append(len([v for v in (частичный["nodes"] or {}).values() if v])
                       + len([v for v in частичный["ioreg_planes"].values() if v]))
    assert полнота[-1] > полнота[0], f"позднее чтение должно дать больше данных: {полнота}"


def test_the_longest_thinking_question_is_the_one_we_keep(тихо, скоро, monkeypatch):
    """Мест в парковке меньше, чем задумчивых доменов. Вытесняем САМЫЙ СВЕЖИЙ вопрос, а не
    самый давний: давний ближе всех к ответу, ради него парковка и сделана.

    Про попытки: вытеснение не тратит их ПЕРВЫЕ `ВЫТЕСНЕНИЙ_БЕЗ_ПОПЫТКИ` раз — телефон не
    виноват, что мест не хватило. Совсем без счёта нельзя: когда телефон молчит обо всём,
    вытеснение ходит по кругу и очередь не кончается никогда (сборка Windows 19.11.2026
    встала на этом насмерть). Поэтому здесь проверяется не «ни один не сдался», а что первым
    сдаётся не тот, кто дольше всех думает."""
    monkeypatch.setattr(snapshot, "ПАРКОВОК", 2)
    молчат = ["com.apple.fmip", "com.apple.mobile.restriction", "com.apple.purplebuddy",
              "com.apple.international"]
    т = Телефон()
    соединить, выданы, журнал = _боковые(т, молчит=молчат)
    snap, сбор = _собрать(т, соединить)
    # первый задумавшийся домен всё ещё ждёт ответа на своём соединении
    первый = молчат[0]
    держат = [с for с in выданы if с.спрошено and с.спрошено[-1] == первый and not с.закрыто]
    assert держат, "самый давний вопрос вытеснили, хотя он ближе всех к ответу"
    assert first_asked_more_than_once(журнал, молчат[1:]), "вытесненные домены не переспросили"
    assert первый not in сбор.сдались, "сдались на самом давнем вопросе, а он ближе всех к ответу"
    прогнать(сбор.закрыть())


def first_asked_more_than_once(журнал, домены) -> bool:
    return any(журнал.count(d) > 1 for d in домены)


def test_closing_does_not_throw_away_an_answer_that_already_arrived(тихо, скоро):
    """Ответ, который телефон уже дал, оплачен ожиданием. Закрытие сбора складывает его в
    слепок, а не выбрасывает вместе с парковкой."""
    async def прогон():
        т = Телефон()
        отпустить = asyncio.Event()
        соединить, выданы, _ж = _боковые(т, молчит=[ПОЗДНИЙ], отпустить=отпустить)
        сбор = snapshot.СборДоменов(соединить, log=lambda *a: None)
        snap = await snapshot.collect(т, т, память=False, соединить=соединить, сбор=сбор)
        assert ПОЗДНИЙ not in snap["domains"]
        ждут = [з for з, _с, _н in сбор._парк.values()]
        assert ждут, "вопрос должен был остаться на своём соединении"
        отпустить.set()                              # телефон ответил...
        await asyncio.wait(ждут, timeout=1)
        await сбор.закрыть(snap)                     # ...и ровно в этот момент всё закрывают
        return snap, выданы
    snap, выданы = прогнать(прогон())
    assert snap["domains"].get(ПОЗДНИЙ) == _слепок()["domains"][ПОЗДНИЙ], "ответ выброшен при закрытии"
    assert all(с.закрыто for с in выданы)


def test_the_phone_says_what_it_is_even_before_trust(monkeypatch):
    """Как в 3uTools: пока клиент не нажал «Доверять», сотрудник всё равно видит, какой аппарат
    на кабеле. lockdown отдаёт модель, iOS и серийник до сопряжения."""
    from pintel_core.devicelink import connect as c

    class Доверия_нет:
        all_values = {"ProductType": "iPhone14,5", "ProductVersion": "18.7.8",
                      "BuildVersion": "22H123", "SerialNumber": "F2LW104QPN", "DeviceClass": "iPhone"}

        async def close(self):
            self.закрыт = True

    клиенты = []

    async def без_пары(serial=None, autopair=True, **k):
        assert autopair is False, "карточку до «Доверять» читаем без сопряжения"
        клиенты.append(Доверия_нет())
        return клиенты[-1]
    monkeypatch.setattr(c, "create_using_usbmux", без_пары)
    сведения = прогнать(c.сведения_без_доверия("UDID"))
    assert сведения["модель"] == "iPhone 13" and сведения["ios"] == "18.7.8"
    assert сведения["серийник"] == "F2LW104QPN" and сведения["код_модели"] == "iPhone14,5"
    assert getattr(клиенты[0], "закрыт", False), "соединение карточки не закрыли"
    st = c.LinkStatus(c.TRUST_PENDING, сведения=сведения)
    assert st.подпись_телефона == "iPhone 13 · iOS 18.7.8"
    assert "Доверять" in st.human and "iPhone 13" in st.human

    async def не_вышло(**k):
        raise ConnectionRefusedError("нет телефона")
    monkeypatch.setattr(c, "create_using_usbmux", не_вышло)
    assert прогнать(c.сведения_без_доверия("UDID")) == {}, "подсказка не должна ронять подключение"
