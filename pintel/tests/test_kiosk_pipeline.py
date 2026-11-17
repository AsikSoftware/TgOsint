# -*- coding: utf-8 -*-
"""Киоск без телефона: поток проверки на подменённом ядре. Проверяем порядок шагов,
`done` без истории, затем `history` когда клиент открыл раздел позже, и уход на сервер."""
import asyncio, json, os, tempfile, threading, time
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from pintel_kiosk import worker
from pintel_core.devicelink import snapshot

HERE = os.path.dirname(os.path.abspath(__file__))


class FakeStatus:
    state, human, serial, timings = "READY", "ок", "TESTSERIAL", {"t": 0.1}
    lockdown = object()


class FakeListener:
    """История появляется только после done: первый wait пуст, первый wait_change
    приносит запись, дальше изменений нет (воркер должен сам выйти из цикла)."""
    ITEMS = {"Display": {"деталь": "Экран", "код": 1025, "меняли": True, "бу": False, "дата": "2026-03-01"}}

    def __init__(self, ld, log=None, **kw):
        self.calls = 0; self.lines = 1; self.connects = 1; self.reconnects = 0; self.stopped = False
        self.meta = {"раздел_открыт": False, "формат": None, "строк_по_теме": 0}
        self.state = "waiting"
        self.items = {}
    async def start(self): return self
    async def wait(self, seconds, keep_going=None, on_tick=None, grace=2.0, unknown_quiet=8.0, settle=5.0):
        await asyncio.sleep(0.05)
        return {}, "", 0.1
    async def wait_change(self, seen, keep_going=None, grace=2.0):
        self.calls += 1
        await asyncio.sleep(0.05)
        self.items = dict(self.ITEMS)
        self.state, self.meta["формат"] = "found", "записи обслуживания (iOS 26)"
        return self.items, "raw", 0.2
    async def stop(self): self.stopped = True


class ФейкСоединение:
    """Отдельное соединение с телефоном под вопрос о памяти: отвечает сразу или через `ждать` с."""

    def __init__(self, диск, ждать=0.0):
        self.диск, self.ждать, self.спрошено, self.закрыто = диск, ждать, [], False

    async def get_value(self, domain=None, key=None):
        self.спрошено.append(domain)
        if self.ждать:
            await asyncio.sleep(self.ждать)
        return self.диск

    async def close(self):
        self.закрыто = True


def _без_диска(snap):
    """Слепок, каким его теперь отдаёт касса: про память в нём ещё не спрашивали."""
    копия = dict(snap)
    копия["domains"] = {k: v for k, v in (snap.get("domains") or {}).items() if k != "com.apple.disk_usage"}
    копия["quality"] = dict(snap.get("quality") or {})
    копия["nand_summary"] = {}
    return копия


class FakeClient:
    enabled = True
    local_sickw = False
    def local_number(self): return 99
    def __init__(self): self.calls = []
    def sickw(self, imei, services=None): self.calls.append(("sickw", imei)); return {"в_чёрном_списке": False, "цвет": "чёрный", "все_поля": {"Blacklist Status": "Clean"}}
    def price(self): return None
    def upload(self, payload): self.calls.append(("upload", payload["client_id"])); return {"id": 7, "номер": 3, "ссылка_отчёта": "http://x/r/1"}
    def update_evaluation(self, ev_id, report, snapshot_patch=None): self.calls.append(("update", ev_id, list(snapshot_patch or {}))); return {"ok": True}


@pytest.fixture
def fake_core(monkeypatch):
    snap = snapshot.loads(open(os.path.join(HERE, "fixtures_real", "iphone12_ios26_anon.snapshot.json"), encoding="utf-8").read())
    snap.pop("repair_history", None)
    async def wait_ready(on_status=None, deadline=None): return FakeStatus()
    async def open_diag(ld, attempts=6, delays=None): return object(), 1
    async def collect(ld, diag, log=None, **kw): return _без_диска(snap) if kw.get("память") is False else dict(snap)
    monkeypatch.setattr(worker.connect, "wait_ready", wait_ready)
    monkeypatch.setattr(worker.connect, "open_diagnostics", open_diag)
    monkeypatch.setattr(worker.snapshot, "collect", collect)
    # про память касса спрашивает сама, в конце и по отдельному соединению — здесь оно подставное
    async def второе(ld): return ФейкСоединение(snap["domains"].get("com.apple.disk_usage"))
    monkeypatch.setattr(worker.connect, "второе_соединение", второе)
    listeners = []
    def mk(ld, log=None, **kw):
        l = FakeListener(ld); listeners.append(l); return l
    monkeypatch.setattr(worker.repair_history, "Listener", mk)
    # подставной слушатель процент батареи не называет — ждать его в этих тестах нечего
    monkeypatch.setattr(worker, "ЖДАТЬ_БАТАРЕЮ", 0)
    # реестр РФС — без сети: оба IMEI верифицированы
    monkeypatch.setattr(worker.rfs, "проверить", lambda imeis, cache_dir=None, proxy=None, **kw: [
        {"imei": i, "verdict": "verified", "status_text": "Верифицирован", "deadline": None, "text": "ок", "ok": True}
        for i in imeis if i])
    return listeners


def test_pipeline_done_then_late_history(fake_core):
    app = QCoreApplication.instance() or QCoreApplication([])
    client = FakeClient()
    p = worker.Pipeline({"apple_history_seconds": 1, "currency": "₸", "sickw": True}, client, None)
    events = []
    loop = QEventLoop()
    p.step.connect(lambda k, s, t: events.append(("step", k, s)))
    p.apple_prompt.connect(lambda on: events.append(("prompt", on)))
    p.done.connect(lambda r: events.append(("done", r["server"]["номер"], bool(r["report"].get("apple_история")))))
    p.history.connect(lambda r: (events.append(("history", list(r["report"]["apple_история"]))), loop.quit()))
    p.failed.connect(lambda t: (events.append(("failed", t)), loop.quit()))
    QTimer.singleShot(15000, loop.quit)
    p.start()
    loop.exec()
    p.wait(3000)
    kinds = [e[0] for e in events]
    assert "failed" not in kinds, events
    assert ("prompt", True) in events and events.index(("prompt", True)) < kinds.index("done")
    assert ("done", 3, False) in events
    assert ("history", ["Display"]) in events and kinds.index("history") > kinds.index("done")
    steps = [(k, s) for e, k, s in [x for x in events if x[0] == "step"]]
    assert ("connect", "done") in steps and ("passport", "done") in steps
    assert ("apple", "done") in steps              # журнал — бонус: шаг закрывается с кабеля
    assert steps[-1] == ("apple", "done")
    assert ("sickw", "done") in steps and ("upload", "done") in steps
    assert ("rfs", "done") in steps and steps.index(("rfs", "done")) < steps.index(("upload", "done"))
    assert [c[0] for c in client.calls] == ["sickw", "upload", "update"]
    done = [e for e in events if e[0] == "done"]
    assert done, events
    assert client.calls[-1][1] == 7 and "repair_history" in client.calls[-1][2]
    assert fake_core[0].stopped and fake_core[0].calls == 2        # второй wait_change без изменений — выход


def test_pipeline_waits_for_the_phones_own_battery_percent(fake_core, monkeypatch):
    """Телефон называет процент батареи раз в 20 секунд. Быстрая проверка заканчивалась
    раньше первой строки, и в отчёт шёл наш расчёт вместо числа с экрана телефона."""
    app = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(worker, "ЖДАТЬ_БАТАРЕЮ", 6)

    class Поздний(FakeListener):
        async def start(self):
            # строка powerd приходит уже после того, как кончилось ожидание истории Apple
            asyncio.get_running_loop().call_later(0.8, lambda: self.meta.__setitem__(
                "батарея_телефона", {"процент": 61, "циклы": 900, "состояние": 1, "свежая": True}))
            return self

    monkeypatch.setattr(worker.repair_history, "Listener", lambda ld, log=None, **kw: Поздний(ld))
    p = worker.Pipeline({"apple_history_seconds": 1, "currency": "₸", "sickw": False}, FakeClient(), None)
    итог, шаги = [], []
    loop = QEventLoop()
    p.step.connect(lambda k, s, t: шаги.append((k, s, t)))
    p.done.connect(lambda r: (итог.append(r), loop.quit()))
    p.failed.connect(lambda t: (итог.append(t), loop.quit()))
    QTimer.singleShot(15000, loop.quit)
    p.start()
    loop.exec()
    p.cancel.set()
    p.wait(3000)
    assert итог and isinstance(итог[0], dict), итог
    бат = итог[0]["report"]["батарея"]
    assert бат["здоровье_%"] == 61 and бат["здоровье_основание"] == "сказал сам телефон", бат
    батарея = [ш for ш in шаги if ш[0] == "battery"]
    assert ("battery", "run", "ждём число от телефона") in батарея
    assert батарея[-1] == ("battery", "done", "61 %"), батарея


def test_pipeline_does_not_hold_the_client_when_the_phone_stays_silent(fake_core, monkeypatch):
    """Телефон своё число не назвал — ждём не дольше предела и отдаём наш расчёт."""
    app = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(worker, "ЖДАТЬ_БАТАРЕЮ", 1)
    p = worker.Pipeline({"apple_history_seconds": 1, "currency": "₸", "sickw": False}, FakeClient(), None)
    итог = []
    loop = QEventLoop()
    p.done.connect(lambda r: (итог.append(r), loop.quit()))
    p.failed.connect(lambda t: (итог.append(t), loop.quit()))
    QTimer.singleShot(15000, loop.quit)
    начало = time.monotonic()
    p.start()
    loop.exec()
    прошло = time.monotonic() - начало
    p.cancel.set()
    p.wait(3000)
    assert итог and isinstance(итог[0], dict), итог
    бат = итог[0]["report"]["батарея"]
    assert бат["здоровье_%"] is not None and бат["здоровье_основание"] != "сказал сам телефон", бат
    assert прошло < 6, прошло


def test_pipeline_skips_history_wait_on_unsupported_model(fake_core, monkeypatch):
    """iPhone X: истории Apple нет — шаг закрывается сразу, клиента не держим."""
    app = QCoreApplication.instance() or QCoreApplication([])
    snap = snapshot.loads(open(os.path.join(HERE, "fixtures_real", "iphone12_ios26_anon.snapshot.json"), encoding="utf-8").read())
    snap.pop("repair_history", None)
    snap["root"]["ProductType"] = "iPhone10,6"
    async def collect(ld, diag, log=None, **kw): return dict(snap)
    monkeypatch.setattr(worker.snapshot, "collect", collect)
    client = FakeClient()
    p = worker.Pipeline({"apple_history_seconds": 30, "currency": "₸", "sickw": False}, client, None)
    events, loop = [], QEventLoop()
    p.step.connect(lambda k, s, t: events.append((k, s, t)))
    p.done.connect(lambda r: (events.append(("DONE", r["report"]["apple_история_статус"], "")), loop.quit()))
    p.failed.connect(lambda t: (events.append(("FAILED", t, "")), loop.quit()))
    QTimer.singleShot(10000, loop.quit)
    import time as _t
    t0 = _t.monotonic()
    p.start(); loop.exec(); p.wait(3000)
    assert _t.monotonic() - t0 < 8, "ждали историю у модели без истории"
    assert ("DONE", "не поддерживается", "") in events
    assert any(k == "apple" and s == "done" and "iPhone X" in t for k, s, t in events)


class ФейкHTTP:
    """Подменный httpx.Client: записывает запросы и отдаёт заготовленные ответы."""
    запросы = []
    ответы = {}

    def __init__(self, base_url="", timeout=None, headers=None):
        self.headers = dict(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def request(self, method, path, **kw):
        import httpx
        ФейкHTTP.запросы.append({"метод": method, "путь": path, "токен": self.headers.get("X-Kiosk-Token"),
                                 "машина": self.headers.get("X-Kiosk-Machine"),
                                 "тело": kw.get("json"), "файлы": kw.get("files")})
        код, тело = ФейкHTTP.ответы.get(path, (200, {"ок": True}))
        if callable(тело):
            тело = тело(len([x for x in ФейкHTTP.запросы if x["путь"] == path]))
        if callable(код):
            код = код(len([x for x in ФейкHTTP.запросы if x["путь"] == path]))
        return httpx.Response(код, json=тело)

    def post(self, path, json=None, **kw):
        return self.request("POST", path, json=json, **kw)


def test_the_point_token_is_the_only_thing_a_human_types(monkeypatch, tmp_path):
    """На точке не настраивают ничего, кроме токена: адрес зашит в сборку, остальное
    приходит с сервера. Машина называет себя отдельным заголовком — так видно, сколько
    компьютеров на точке, а второй киоск не требует второго токена."""
    from pintel_kiosk import client as kclient
    from pintel_kiosk import config as kconfig
    for sub in ("queue", "cache"):
        os.makedirs(tmp_path / sub, exist_ok=True)
    monkeypatch.setattr(kclient, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(kclient.httpx, "Client", ФейкHTTP)
    ФейкHTTP.запросы, ФейкHTTP.ответы = [], {"/api/kiosk/sickw": (200, {"в_чёрном_списке": False})}

    без_токена = kclient.Client({**kconfig.УМОЛЧАНИЯ, "server": kconfig.СЕРВЕР, "token": ""})
    assert not без_токена.enabled
    with pytest.raises(kclient.ServerError) as e:
        без_токена.sickw("490154203237518")
    assert "токен" in str(e.value)

    c = kclient.Client({**kconfig.УМОЛЧАНИЯ, "server": kconfig.СЕРВЕР, "token": "pk_точка"})
    assert c.enabled and c.base == kconfig.СЕРВЕР
    assert c.sickw("490154203237518")["в_чёрном_списке"] is False
    запрос = ФейкHTTP.запросы[-1]
    assert запрос["токен"] == "pk_точка" and запрос["машина"]
    # токен сменили в меню администратора — дальше ходим с новым
    c.сменить_токен("pk_другая")
    c.sickw("490154203237518")
    assert ФейкHTTP.запросы[-1]["токен"] == "pk_другая"


def test_the_log_and_the_bundles_go_to_the_server(monkeypatch, tmp_path):
    """Журнал и эталоны раньше лежали только на точке: прочитать их можно было, лишь
    приехав туда. Что уже ушло, помним — обрыв связи не должен терять эталон."""
    from pintel_kiosk import client as kclient
    from pintel_kiosk import config as kconfig
    for sub in ("queue", "cache", "эталоны"):
        os.makedirs(tmp_path / sub, exist_ok=True)
    monkeypatch.setattr(kclient, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(kclient.httpx, "Client", ФейкHTTP)
    ФейкHTTP.запросы, ФейкHTTP.ответы = [], {"/api/kiosk/logs": (200, {"принято": 2}),
                                             "/api/kiosk/reference": (200, {"принят": True})}
    c = kclient.Client({**kconfig.УМОЛЧАНИЯ, "server": kconfig.СЕРВЕР, "token": "pk_точка"})

    assert c.отправить_логи(["первая", "вторая"]) == 2
    assert c.отправить_логи([]) == 0 and len([x for x in ФейкHTTP.запросы
                                              if x["путь"] == "/api/kiosk/logs"]) == 1

    папка, отметка = tmp_path / "эталоны", tmp_path / "cache" / "ушло.json"
    (папка / "эталон_iPhone-12_iOS26.5_20261102_100000.zip").write_bytes(b"PK\x03\x04" + "эталон".encode())
    итог = c.отправить_эталоны(str(папка), str(отметка))
    assert итог == {"ушло": 1, "осталось": 0, "ошибка": ""}
    assert c.отправить_эталоны(str(папка), str(отметка))["ушло"] == 0, "второй раз не шлём"


def test_pipeline_saves_reference_for_every_phone(fake_core):
    """Эталон собирается сам с КАЖДОГО телефона: на нём учится разбор журнала Apple.
    В файле — обезличенный слепок, сырой журнал и наш вердикт; выводы отчёта от
    обезличивания не меняются, иначе эталон не пишется вовсе."""
    import glob, zipfile
    from pintel_kiosk.config import data_dir

    папка = os.path.join(data_dir(), "эталоны")
    os.makedirs(папка, exist_ok=True)
    for p in glob.glob(os.path.join(папка, "*.zip")):
        os.remove(p)

    app = QCoreApplication.instance() or QCoreApplication([])
    p = worker.Pipeline({"apple_history_seconds": 1, "currency": "₸", "sickw": True}, FakeClient(), None)
    итог, loop = {}, QEventLoop()
    p.done.connect(lambda r: итог.update(r))
    p.history.connect(lambda r: (итог.update(r), loop.quit()))     # вердикт пришёл позже — эталон перезапишется
    p.failed.connect(lambda t: (итог.update({"failed": t}), loop.quit()))
    QTimer.singleShot(15000, loop.quit)
    p.start()
    loop.exec()
    p.wait(3000)

    assert "failed" not in итог, итог
    files = glob.glob(os.path.join(папка, "эталон_*.zip"))
    assert files, os.listdir(папка)
    z = zipfile.ZipFile(files[0])
    assert set(z.namelist()) >= {"snapshot.json", "report.json", "правда.json", "apple_raw.txt", "расхождения.txt"}
    rep = json.loads(z.read("report.json").decode("utf-8"))
    assert len(files) == 1, files                                  # один прогон — один файл, а не два
    assert rep["итог"]["вердикт"] == итог["report"]["итог"]["вердикт"]     # выводы те же
    assert list(rep["apple_история"]) == ["Display"]                # поздняя история попала в эталон
    assert json.loads(z.read("правда.json").decode("utf-8"))["кто"] == "автосбор"


# ---------------------------------------------------------------- прошлая проверка

class ФейкЗамок:
    """Подменный lockdown: отдаёт только то, что читается мгновенно — корень и домен fmip."""

    def __init__(self, root, fmip=None):
        self.root, self.fmip, self.чтений = root, fmip or {}, 0

    async def get_value(self, domain=None):
        self.чтений += 1
        return dict(self.fmip) if domain == "com.apple.fmip" else dict(self.root)


def _положить_прошлую(tmp_path, snap, rep, когда=None):
    """Прошлая проверка на диске — ровно там и так, как её складывает сам киоск."""
    from datetime import datetime as dt
    когда = когда or dt.now()
    серийник = rep["паспорт"]["udid"]
    папка = os.path.join(str(tmp_path), "out", f"{когда:%Y%m%d_%H%M%S}_{серийник[:12]}")
    os.makedirs(папка, exist_ok=True)
    with open(os.path.join(папка, "report.json"), "w", encoding="utf-8") as f:
        f.write(snapshot.dumps(rep))
    with open(os.path.join(папка, "snapshot.json"), "w", encoding="utf-8") as f:
        f.write(snapshot.dumps(snap))
    return папка


def _прошлая_обстановка(fake_core, monkeypatch, tmp_path):
    """Телефон, который проверяли минуту назад: отчёт на диске, тот же аппарат на кабеле."""
    from pintel_core.analysis import report as report_mod
    snap = snapshot.loads(open(os.path.join(HERE, "fixtures_real",
                                            "iphone12_ios26_anon.snapshot.json"), encoding="utf-8").read())
    rep = report_mod.build(snap)
    папка = _положить_прошлую(tmp_path, snap, rep)
    monkeypatch.setattr(worker, "data_dir", lambda: str(tmp_path))
    замок = ФейкЗамок(snap["root"], (snap.get("domains") or {}).get("com.apple.fmip"))

    class Статус:
        state, human, timings = "READY", "ок", {"t": 0.1}
        serial = rep["паспорт"]["udid"]
        lockdown = замок

    async def wait_ready(on_status=None, deadline=None):
        return Статус()

    monkeypatch.setattr(worker.connect, "wait_ready", wait_ready)
    читали = []

    async def collect(ld, diag, log=None, **kw):
        читали.append(1)
        return dict(snap)

    monkeypatch.setattr(worker.snapshot, "collect", collect)
    return папка, читали, замок


def _прогнать(p, таймаут=15000):
    """Прогнать поток и вернуть (события, результаты done)."""
    события, итоги, loop = [], [], QEventLoop()
    p.step.connect(lambda k, s, t: события.append((k, s, t)))
    p.прошлая.connect(lambda о: события.append(("прошлая", о.get("сверка"), о.get("словами"))))
    p.done.connect(lambda r: (итоги.append(r), loop.quit()))
    p.failed.connect(lambda t: (события.append(("failed", t, "")), loop.quit()))
    QTimer.singleShot(таймаут, loop.quit)
    p.start()
    loop.exec()
    p.wait(3000)
    return события, итоги


def test_a_phone_checked_minutes_ago_is_not_read_again(fake_core, monkeypatch, tmp_path):
    """Тот же телефон принесли второй раз — берём готовый отчёт, а не читаем минуты заново.

    Так выглядит обычный день: сделку отменили, программа перезапустилась, клиент ушёл
    подумать и вернулся. Слепок, ожидание раздела Apple, база IMEI и реестр — это минуты, и
    второй раз они дают тот же ответ. Сотрудник идёт сразу к тесту и медиа."""
    QCoreApplication.instance() or QCoreApplication([])
    папка, читали, замок = _прошлая_обстановка(fake_core, monkeypatch, tmp_path)
    client = FakeClient()
    p = worker.Pipeline({"apple_history_seconds": 30}, client, None)
    события, итоги = _прогнать(p)

    assert итоги, события
    assert not читали, "телефон перечитали заново, хотя проверка свежая"
    отметка = итоги[0]["report"]["повторная_проверка"]
    assert отметка["сверка"] == "сошлась" and отметка["возраст_мин"] == 0
    assert итоги[0]["повторная"] is True and итоги[0]["out"] == папка
    assert замок.чтений >= 1, "прошлый отчёт взяли, не сверив с живым телефоном"
    # оценка этого визита всё равно уехала на сервер: к ней цепляются тест и чек
    assert [c[0] for c in client.calls] == ["upload"]
    шаги = [(k, s) for k, s, _ in события if k != "прошлая"]
    assert ("passport", "done") in шаги and ("upload", "done") in шаги
    assert ("прошлая", "сошлась", отметка["словами"]) in события
    assert any(k == "passport" and "прошлая" in t for k, _, t in события)


def test_the_employee_can_insist_on_a_full_read(fake_core, monkeypatch, tmp_path):
    """Кнопка «Проверить телефон заново» сильнее свежего отчёта: сказали читать — читаем.

    Сотрудник видит телефон, а программа — только файл на диске. Если он не верит прошлой
    проверке, последнее слово за ним."""
    QCoreApplication.instance() or QCoreApplication([])
    _папка, читали, _замок = _прошлая_обстановка(fake_core, monkeypatch, tmp_path)
    p = worker.Pipeline({"apple_history_seconds": 1}, FakeClient(), None, заново=True)
    события, итоги = _прогнать(p)
    assert итоги and читали, события
    assert "повторная_проверка" not in итоги[0]["report"]


def test_a_changed_phone_is_read_again_even_if_the_report_is_fresh(fake_core, monkeypatch, tmp_path):
    """На кабеле другой серийник — значит это другой аппарат, и отчёт из папки не наш."""
    QCoreApplication.instance() or QCoreApplication([])
    _папка, читали, замок = _прошлая_обстановка(fake_core, monkeypatch, tmp_path)
    замок.root = {**замок.root, "SerialNumber": "ЧУЖОЙ00000"}
    p = worker.Pipeline({"apple_history_seconds": 1}, FakeClient(), None)
    события, итоги = _прогнать(p)
    assert итоги and читали, события
    assert "повторная_проверка" not in итоги[0]["report"]


# ---------------------------------------------------------------- шаг «Модель и память» не зависает

def _слепок_из_файла():
    return snapshot.loads(open(os.path.join(HERE, "fixtures_real", "iphone12_ios26_anon.snapshot.json"),
                               encoding="utf-8").read())


def test_the_phone_is_asked_about_memory_once_at_the_very_end(fake_core, monkeypatch):
    """Про память телефон отвечает когда как (бывало по три минуты), и пока он считает, его
    журнал завален чужими строками. Поэтому касса спрашивает один раз, в самом конце и по
    отдельному соединению: объём к тому времени уже известен с контроллера, а ответ нужен
    только для сверки. Сам слепок про память не спрашивает вовсе."""
    QCoreApplication.instance() or QCoreApplication([])
    snap = _слепок_из_файла()
    вызовы, соединения = [], []

    async def collect(ld, diag, log=None, **kw):
        вызовы.append(kw)
        return _без_диска(snap)

    async def второе(ld):
        соединения.append(ФейкСоединение(snap["domains"]["com.apple.disk_usage"]))
        return соединения[-1]
    monkeypatch.setattr(worker.snapshot, "collect", collect)
    monkeypatch.setattr(worker.connect, "второе_соединение", второе)
    p = worker.Pipeline({"apple_history_seconds": 1, "currency": "₸", "sickw": False}, FakeClient(), None)
    события, итоги = _прогнать(p)
    assert итоги and not [с for с in события if с[0] == "failed"], события
    assert вызовы and вызовы[0].get("память") is False, "слепок не должен спрашивать про память"
    assert len(соединения) == 1 and соединения[0].спрошено == ["com.apple.disk_usage"], "спросили один раз"
    assert соединения[0].закрыто, "отдельное соединение закрыто"
    rep = итоги[0]["report"]
    assert rep["память"]["объём_гб"] == 64 and rep["память"]["диск_гб"] == 64
    # объём был на экране сразу после слепка — с контроллера, ещё до вопроса про память
    assert [т for к, с, т in события if к == "passport" and с == "done"][0].endswith("64 ГБ")
    p.cancel.set()
    p.wait(3000)


def test_a_phone_slow_to_answer_about_memory_does_not_hold_the_check(fake_core, monkeypatch):
    """Телефон считает ответ про память дольше, чем касса готова ждать. Проверка идёт дальше:
    объём — с контроллера NVMe, в отчёте служебной строкой сказано, что с диском он не сверен.
    Автоцену это не отменяет: в «не прочиталось» такая проверка не попадает."""
    QCoreApplication.instance() or QCoreApplication([])
    snap = _слепок_из_файла()

    async def второе(ld):
        return ФейкСоединение(snap["domains"]["com.apple.disk_usage"], ждать=30)
    monkeypatch.setattr(worker.connect, "второе_соединение", второе)
    monkeypatch.setattr(worker, "ЖДАТЬ_ПАМЯТЬ", 0.3)
    p = worker.Pipeline({"apple_history_seconds": 1, "currency": "₸", "sickw": False}, FakeClient(), None)
    начало = time.monotonic()
    события, итоги = _прогнать(p)
    assert итоги and time.monotonic() - начало < 8, "проверка ждала телефон"
    rep = итоги[0]["report"]
    assert rep["память"]["объём_гб"] == 64 and rep["память"]["диск_гб"] is None
    assert any("не ответил про память" in x for x in rep["служебное"]), rep["служебное"]
    assert not any("память" in str(x).lower() for x in rep["не_прочиталось"]), rep["не_прочиталось"]
    p.cancel.set()
    p.wait(3000)


def test_a_dropped_link_restarts_the_reading_instead_of_hanging(fake_core, monkeypatch):
    """Связь по кабелю оборвалась посреди чтения. Касса не стучится в мёртвое соединение
    (раньше — 1,5–3,5 минуты и отчёт с «? ГБ»), а ждёт телефон и читает заново; сотрудник
    видит это словами на шаге."""
    QCoreApplication.instance() or QCoreApplication([])
    snap = _слепок_из_файла()
    чтения = []

    async def collect(ld, diag, log=None, **kw):
        чтения.append(1)
        if len(чтения) == 1:
            raise snapshot.СвязьПропала("ioreg:IOService: ConnectionTerminatedError")
        return _без_диска(snap)
    monkeypatch.setattr(worker.snapshot, "collect", collect)
    p = worker.Pipeline({"apple_history_seconds": 1, "currency": "₸", "sickw": False}, FakeClient(), None)
    события, итоги = _прогнать(p)
    assert итоги and len(чтения) == 2, события
    подписи = [т for к, с, т in события if к == "passport" and с == "run"]
    assert any("связь пропала" in т for т in подписи) and any("читаем заново" in т for т in подписи), подписи
    assert итоги[0]["report"]["память"]["объём_гб"] == 64
    p.cancel.set()
    p.wait(3000)


def test_a_link_that_keeps_dropping_is_named_and_the_check_stops(fake_core, monkeypatch):
    """Связь рвётся раз за разом — после третьей попытки касса говорит это словами: менять
    кабель или порт. Полупустого результата при этом нет."""
    QCoreApplication.instance() or QCoreApplication([])
    чтения = []

    async def collect(ld, diag, log=None, **kw):
        чтения.append(1)
        raise snapshot.СвязьПропала("com.apple.mobile.battery: DeviceNotFoundError")
    monkeypatch.setattr(worker.snapshot, "collect", collect)
    p = worker.Pipeline({"apple_history_seconds": 1, "currency": "₸", "sickw": False}, FakeClient(), None)
    события, итоги = _прогнать(p)
    assert not итоги and len(чтения) == worker.ЧТЕНИЙ == 3
    отказы = [т for к, т, _ in события if к == "failed"]
    assert отказы and "кабель" in отказы[0] and "порт" in отказы[0], события
    assert not [с for с in события if с[0] == "passport" and с[1] == "done"]


def test_a_cancelled_reading_draws_nothing_and_gives_no_result(fake_core, monkeypatch):
    """Чтение отменили (телефон отключили, окно начало новую проверку). Старое чтение обязано
    замолчать: раньше оно дочитывало до конца и рисовало свои шаги и свой результат поверх
    новой проверки."""
    QCoreApplication.instance() or QCoreApplication([])
    snap = _слепок_из_файла()
    p = worker.Pipeline({"apple_history_seconds": 1, "currency": "₸", "sickw": False}, FakeClient(), None)

    async def collect(ld, diag, log=None, **kw):
        p.cancel.set()                       # отмена приходит, пока идёт слепок
        if not kw["жив"]():
            raise snapshot.Остановлено("чтение отменено")
        return _без_диска(snap)
    monkeypatch.setattr(worker.snapshot, "collect", collect)
    события, итоги = _прогнать(p, таймаут=2500)
    assert not итоги and not [с for с in события if с[0] == "failed"], события
    assert not [с for с in события if с[0] == "passport" and с[1] == "done"], события
    assert not [с for с in события if с[0] in ("battery", "locks", "apple", "upload")], события


def test_an_answer_the_phone_thought_up_late_reaches_the_report_and_the_deal(fake_core, monkeypatch):
    """Телефон додумал ответ уже после того, как отчёт показан, — и ответ не выбрасывается.

    Пока сотрудник снимает фото и видео, телефон лежит на кабеле: там есть минуты. Касса
    дособирает остаток, перезаписывает слепок, отчёт и эталон и досылает оценку на сервер —
    тем же путём, которым догоняет поздний вердикт Apple."""
    QCoreApplication.instance() or QCoreApplication([])
    snap = _слепок_из_файла()
    ДОМЕН = "com.apple.mobile.battery"
    monkeypatch.setattr(worker.snapshot, "ЖДАТЬ_ДОМЕН", 0.05)
    monkeypatch.setattr(worker.snapshot, "ЖДАТЬ_ОСТАТОК", 0.1)
    monkeypatch.setattr(worker, "ЖДАТЬ_ПАМЯТЬ", 0.5)
    отпустить = threading.Event()
    соединения = []

    class Думает:
        """Боковое соединение: про память отвечает сразу, а про домен — когда разрешат."""

        def __init__(self):
            self.спрошено, self.закрыто = [], False

        async def get_value(self, domain=None, key=None):
            self.спрошено.append(domain)
            if domain == ДОМЕН:
                while not отпустить.is_set():
                    await asyncio.sleep(0.02)
            return snap["domains"].get(domain)

        async def close(self):
            self.закрыто = True

    async def второе(ld):
        соединения.append(Думает())
        return соединения[-1]

    async def collect(ld, diag, log=None, **kw):
        сбор = kw["сбор"]
        assert сбор is not None, "касса обязана дать слепку сборщик доменов"
        сбор.начать([ДОМЕН])
        await сбор.собрать(ждать=0.05)                 # не дождались — вопрос остаётся в работе
        усечённый = _без_диска(snap)
        усечённый["domains"].pop(ДОМЕН, None)
        await сбор.собрать(усечённый)
        return усечённый

    monkeypatch.setattr(worker.snapshot, "collect", collect)
    monkeypatch.setattr(worker.connect, "второе_соединение", второе)
    client = FakeClient()
    p = worker.Pipeline({"apple_history_seconds": 1, "currency": "₸", "sickw": False}, client, None,
                        заново=True)
    поздние = []
    p.history.connect(lambda r: поздние.append(r))
    события, итоги = _прогнать(p)
    assert итоги and not [с for с in события if с[0] == "failed"], события
    слепок = snapshot.loads(open(os.path.join(итоги[0]["out"], "snapshot.json"), encoding="utf-8").read())
    assert ДОМЕН not in слепок["domains"], "вопрос должен был остаться в работе"
    assert ДОМЕН in (слепок["quality"].get("домены_без_ответа") or {})

    отпустить.set()                                   # телефон додумал
    ждём = QEventLoop()
    p.history.connect(lambda r: ждём.quit())
    QTimer.singleShot(6000, ждём.quit)
    ждём.exec()

    слепок = snapshot.loads(open(os.path.join(итоги[0]["out"], "snapshot.json"), encoding="utf-8").read())
    assert слепок["domains"].get(ДОМЕН) == snap["domains"][ДОМЕН], "поздний ответ не дошёл до слепка"
    assert "домены_без_ответа" not in слепок["quality"], "пометка «не ответил» не снята"
    assert поздние and поздние[-1]["report"], "экран кассы о позднем ответе не узнал"
    assert [c for c in client.calls if c[0] == "update"], "оценку на сервере не дописали"
    p.cancel.set()
    p.wait(3000)
    assert all(с.закрыто for с in соединения), "боковые соединения не закрыты"


def test_the_collector_is_not_restarted_when_the_reading_restarts(fake_core, monkeypatch):
    """Связь оборвалась, и слепок читается заново. Сборщик доменов при этом ТОТ ЖЕ: собранное
    не выбрасывается, а вопросы, которые телефон ещё обдумывает, остаются в работе."""
    QCoreApplication.instance() or QCoreApplication([])
    snap = _слепок_из_файла()
    сборщики, чтения = [], []

    async def collect(ld, diag, log=None, **kw):
        сборщики.append(kw.get("сбор"))
        чтения.append(1)
        if len(чтения) == 1:
            raise snapshot.СвязьПропала("ioreg:IOService: ConnectionTerminatedError")
        return _без_диска(snap)

    monkeypatch.setattr(worker.snapshot, "collect", collect)
    p = worker.Pipeline({"apple_history_seconds": 1, "currency": "₸", "sickw": False}, FakeClient(), None,
                        заново=True)
    события, итоги = _прогнать(p)
    assert итоги and len(сборщики) == 2, события
    assert сборщики[0] is not None and сборщики[0] is сборщики[1], "сборщик пересоздали на второй попытке"
    p.cancel.set()
    p.wait(3000)


def test_the_reading_step_always_ends_with_an_answer_or_a_refusal(fake_core, monkeypatch):
    """Шаг «Модель и память» обязан кончаться — ответом или отказом словами, но не висеть.

    Проверяем худший случай: связь рвётся на каждой попытке. Касса перечитывает телефон, но
    не бесконечно: на всё чтение отведено ЖДАТЬ_ЧТЕНИЕ_ВСЕГО, и дальше сотрудник получает
    понятную причину, а не крутящийся шаг."""
    QCoreApplication.instance() or QCoreApplication([])
    чтения = []

    async def collect(ld, diag, log=None, **kw):
        чтения.append(1)
        raise snapshot.СвязьПропала("ioreg:IOService: телефон не ответил за 10 с")

    async def ждём_телефон(self):
        return object()

    monkeypatch.setattr(worker.snapshot, "collect", collect)
    monkeypatch.setattr(worker.Pipeline, "_дождаться_телефона", ждём_телефон)
    p = worker.Pipeline({"apple_history_seconds": 1, "currency": "₸", "sickw": False}, FakeClient(), None,
                        заново=True)
    беды, loop = [], QEventLoop()
    p.failed.connect(lambda t: (беды.append(t), loop.quit()))
    p.done.connect(lambda r: loop.quit())
    QTimer.singleShot(20000, loop.quit)
    начало = time.monotonic()
    p.start()
    loop.exec()
    p.wait(3000)
    assert беды and "кабель" in беды[0], беды
    assert len(чтения) == worker.ЧТЕНИЙ, "перечитываний должно быть ровно столько, сколько отведено"
    assert time.monotonic() - начало < 20, "шаг не кончился за отведённое время"

    # и когда время вышло, четвёртую попытку не начинают вовсе
    monkeypatch.setattr(worker, "ЖДАТЬ_ЧТЕНИЕ_ВСЕГО", -1.0)
    чтения.clear()
    p2 = worker.Pipeline({"apple_history_seconds": 1, "currency": "₸", "sickw": False}, FakeClient(), None,
                         заново=True)
    беды2, loop2 = [], QEventLoop()
    p2.failed.connect(lambda t: (беды2.append(t), loop2.quit()))
    QTimer.singleShot(20000, loop2.quit)
    p2.start()
    loop2.exec()
    p2.wait(3000)
    assert len(чтения) == 1 and беды2 and "не читается" in беды2[0], (чтения, беды2)
