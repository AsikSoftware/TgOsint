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
    """История появляется только во второй wait (после done)."""
    def __init__(self, ld, log=None, **kw):
        self.calls = 0; self.lines = 1; self.connects = 1; self.reconnects = 0; self.stopped = False
    async def start(self): return self
    async def wait(self, seconds, keep_going=None, on_tick=None, grace=2.0):
        self.calls += 1
        if self.calls == 1:
            await asyncio.sleep(0.05)
            return {}, "", 0.1
        items = {"Display": {"деталь": "Экран", "код": 1025, "меняли": True, "бу": False, "дата": "2026-03-01"}}
        return items, "raw", 0.2
    async def stop(self): self.stopped = True


class FakeClient:
    enabled = True
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
    assert ("connect", "done") in steps and ("passport", "done") in steps and ("apple", "warn") in steps
    assert steps[-1] == ("apple", "done")
    assert ("sickw", "done") in steps and ("upload", "done") in steps
    assert [c[0] for c in client.calls] == ["sickw", "upload", "update"]
    assert client.calls[-1][1] == 7 and "repair_history" in client.calls[-1][2]
    assert fake_core[0].stopped
