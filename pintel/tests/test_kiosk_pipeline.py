# -*- coding: utf-8 -*-
"""Киоск без телефона: поток проверки на подменённом ядре. Проверяем порядок шагов,
`done` без истории, затем `history` когда клиент открыл раздел позже, и уход на сервер."""
import asyncio, json, os, tempfile
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


class FakeClient:
    enabled = True
    local_sickw = False
    def local_number(self): return 99
    def __init__(self): self.calls = []
    def sickw(self, imei): self.calls.append(("sickw", imei)); return {"в_чёрном_списке": False, "цвет": "чёрный", "все_поля": {"Blacklist Status": "Clean"}}
    def price(self): return None
    def upload(self, payload): self.calls.append(("upload", payload["client_id"])); return {"id": 7, "номер": 3, "ссылка_отчёта": "http://x/r/1"}
    def update_evaluation(self, ev_id, report, snapshot_patch=None): self.calls.append(("update", ev_id, list(snapshot_patch or {}))); return {"ok": True}


@pytest.fixture
def fake_core(monkeypatch):
    snap = snapshot.loads(open(os.path.join(HERE, "fixtures_real", "iphone12_ios26_anon.snapshot.json"), encoding="utf-8").read())
    snap.pop("repair_history", None)
    async def wait_ready(on_status=None, deadline=None): return FakeStatus()
    async def open_diag(ld): return object(), 1
    async def collect(ld, diag, log=None): return json.loads(json.dumps(snap, default=str)) if False else dict(snap)
    monkeypatch.setattr(worker.connect, "wait_ready", wait_ready)
    monkeypatch.setattr(worker.connect, "open_diagnostics", open_diag)
    monkeypatch.setattr(worker.snapshot, "collect", collect)
    listeners = []
    def mk(ld, log=None, **kw):
        l = FakeListener(ld); listeners.append(l); return l
    monkeypatch.setattr(worker.repair_history, "Listener", mk)
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
    assert [c[0] for c in client.calls] == ["sickw", "upload", "update"]
    assert client.calls[-1][1] == 7 and "repair_history" in client.calls[-1][2]
    assert fake_core[0].stopped and fake_core[0].calls == 2        # второй wait_change без изменений — выход


def test_pipeline_skips_history_wait_on_unsupported_model(fake_core, monkeypatch):
    """iPhone X: истории Apple нет — шаг закрывается сразу, клиента не держим."""
    app = QCoreApplication.instance() or QCoreApplication([])
    snap = snapshot.loads(open(os.path.join(HERE, "fixtures_real", "iphone12_ios26_anon.snapshot.json"), encoding="utf-8").read())
    snap.pop("repair_history", None)
    snap["root"]["ProductType"] = "iPhone10,6"
    async def collect(ld, diag, log=None): return dict(snap)
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


def test_client_standalone_sickw_price_and_numbers(monkeypatch, tmp_path):
    from pintel_kiosk import client as kclient
    from pintel_core.external import sickw as sk
    monkeypatch.setattr(kclient, "data_dir", lambda: str(tmp_path))
    for sub in ("queue", "cache"):
        os.makedirs(tmp_path / sub, exist_ok=True)
    monkeypatch.setattr(kclient, "app_dir", lambda: str(tmp_path))
    json.dump({"база": {"iPhone13,2": {"64": 80000}}, "сетка_износа": {}}, open(tmp_path / "cache" / "price_grid.json", "w"))
    c = kclient.Client({"server": "", "token": "", "sickw_key": "KEY", "sickw_services": [61]})
    assert not c.enabled and c.local_sickw and c.standalone_ready
    monkeypatch.setattr(sk, "_get", lambda params, timeout=60: {"status": "success",
                        "result": 'Model: iPhone 12 64GB Black<br>Blacklist Status: <font color="green">Clean</font><br>iCloud Lock: <font color="red">ON</font><br>'})
    r = c.sickw("490154203237518")
    assert r["в_чёрном_списке"] is False and r["fmi_включён"] is True
    assert c.price()["база"]["iPhone13,2"]["64"] == 80000
    assert [c.local_number(), c.local_number()] == [1, 2]
    assert c.upload({"client_id": "x1", "report": {}}) is None and c.queued() == 1
