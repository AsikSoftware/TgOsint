# -*- coding: utf-8 -*-
"""Матрица совместимости на реальных телефонах: каждая правка обязана держать ВСЕ
известные форматы и модели сразу, а не «одно починили — другое отвалилось».

Журналы (обезличены): iOS 18.7.8 iPhone 13 и iPhone 12, iOS 26.6 iPhone 12 и iPhone 17 Pro.
Слепки: iPhone 12 (iOS 18 и 26), iPhone 13, iPhone 14 Pro, iPhone 17 Pro + 228 паспортов."""
import asyncio, glob, json, os
import pytest

from pintel_core.devicelink import mdm, repair_history as rh, snapshot
from pintel_core.analysis import capabilities, report as report_mod

HERE = os.path.dirname(os.path.abspath(__file__))
SYSLOG = os.path.join(HERE, "fixtures_real", "syslog")


class Replay:
    """Подменная служба журнала: отдаёт строки реального телефона, потом молчит."""
    lines = []

    def __init__(self, ld):
        pass

    async def connect(self):
        pass

    async def watch(self):
        for l in Replay.lines:
            await asyncio.sleep(0)
            yield l
        while True:
            await asyncio.sleep(0.05)

    async def close(self):
        pass


def replay(name, monkeypatch, seconds=3.0):
    data = json.load(open(os.path.join(SYSLOG, name + ".json"), encoding="utf-8"))
    Replay.lines = data["lines"]
    monkeypatch.setattr(rh, "SyslogService", Replay)

    async def run():
        lst = rh.Listener(None)
        await lst.start()
        items, raw, waited = await lst.wait(seconds, grace=0.2, unknown_quiet=0.5)
        await lst.stop()
        return items, lst.state, dict(lst.meta), data["meta"]
    return asyncio.run(run())


@pytest.mark.parametrize("name,state,fmt,changed", [
    ("ios18_iphone13_seal_clean", "found", "сверка", set()),
    ("ios26_iphone12_records", "found", "записи", set()),
    ("ios26_iphone17pro_records", "found", "записи", set()),
    ("ios18_iphone12_opened_truncated", "opened_unknown", "не распознан", None),
])
def test_history_every_known_format(name, state, fmt, changed, monkeypatch):
    items, st, meta, m = replay(name, monkeypatch)
    assert st == state, (name, st, meta)
    assert (meta.get("формат") or "").startswith(fmt), meta.get("формат")
    assert meta["раздел_открыт"] is True
    if changed is not None:
        assert {k for k, v in items.items() if v["меняли"]} == changed
        assert {"Battery", "Display", "Camera", "FaceID"} <= set(items)


def test_history_seal_with_repair_records_is_not_all_original():
    meta = {"дельта": [], "unsealed": [], "rchl_байт": 512}
    items = rh.synthesize(meta)
    assert "RepairRecords" in items and not any(k in items for k in ("Battery", "Display"))
    meta = {"дельта": ["Display"], "unsealed": ["Battery"], "rchl_байт": 0}
    items = rh.synthesize(meta)
    assert items["Display"]["неизвестная"] and items["Battery"]["неизвестная"] and not items["Camera"]["меняли"]


@pytest.mark.parametrize("pt,ios,ok", [
    ("iPhone10,3", "16.7", False), ("iPhone11,8", "15.1", False), ("iPhone11,8", "15.2", True),
    ("iPhone12,8", "17.5", True), ("iPhone13,2", "18.7.8", True), ("iPhone18,1", "26.6", True), ("iPad13,1", "18", False),
])
def test_history_supported_matrix(pt, ios, ok):
    assert rh.supported(pt, ios)[0] is ok


@pytest.mark.parametrize("pt,face", [("iPhone10,3", True), ("iPhone10,4", False), ("iPhone12,8", False),
                                    ("iPhone14,6", False), ("iPhone14,5", True), ("iPhone17,5", True), ("iPhone18,4", True)])
def test_face_id_capability(pt, face):
    assert capabilities.has_face_id(pt) is face


def _snap(name):
    return snapshot.loads(open(os.path.join(HERE, "fixtures_real", name), encoding="utf-8").read())


def test_touch_id_model_is_not_incomplete_because_of_face_id():
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    snap["root"]["ProductType"] = "iPhone14,6"                  # SE 3: Touch ID
    snap["nodes"]["camera"].pop("SavageSNUM", None)
    snap["nodes"]["camera"].pop("FrontIRCameraSerialNumber", None)
    snap["repair_history"] = rh.synthesize({"дельта": [], "rchl_байт": 0})
    rep = report_mod.build(snap)
    assert "Face ID ↔ плата" not in rep["сигналы"] and "FaceID" not in rep["apple_история"]
    assert rep["итог"]["вердикт"] != "ПРОВЕРКА НЕПОЛНАЯ", rep["итог"]


def test_node_absent_from_map_is_not_a_read_failure():
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    snap["nodes"]["AppleHapticsSupportArcEEPROM"] = None
    snap["quality"]["нет_в_карте"] = ["AppleHapticsSupportArcEEPROM"]
    snap["repair_history_meta"] = {"формат": "записи обслуживания (iOS 26)", "дельта": []}   # Apple подтвердила
    rep = report_mod.build(snap)
    assert "Taptic ↔ плата" not in rep["сигналы"] and rep["итог"]["вердикт"] != "ПРОВЕРКА НЕПОЛНАЯ"


def test_history_status_in_report():
    # полный кабель, но Apple не прочиталась: зелёного нет — «кабель», проверка неполная,
    # сотрудник сверяет раздел на телефоне (кабель не видит пересаженный оригинальный экран)
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    snap.pop("repair_history", None)
    snap["repair_history_meta"] = {"раздел_открыт": True, "формат": "не распознан"}
    rep = report_mod.build(snap)
    assert rep["apple_история_статус"] == "формат не распознан"
    assert rep["детали_вердикт"]["итог"] == "кабель" and rep["итог"]["вердикт"] == "ПРОВЕРКА НЕПОЛНАЯ"
    assert any("не подтверждена Apple" in x for x in rep["не_прочиталось"])
    assert not any("этот формат iOS" in x for x in rep["сделать"])      # не дёргаем клиента зря
    # модель без истории — честный статус, вердикт деталей всё равно с кабеля
    snap["root"]["ProductType"], snap["root"]["ProductVersion"] = "iPhone10,6", "16.7.10"
    snap["repair_history_meta"] = {}
    rep = report_mod.build(snap)
    assert rep["apple_история_статус"] == "не поддерживается" and rep["детали_вердикт"]["итог"] == "родные"


@pytest.mark.parametrize("probe,expect", [
    ({"прочитано": True, "cloud": {"IsSupervised": True, "OrganizationName": "ACME"}, "профили": []}, True),
    ({"прочитано": True, "cloud": {"ConfigurationURL": "https://mdm.acme/enroll", "IsMandatory": True}, "профили": []}, True),
    ({"прочитано": True, "cloud": {}, "профили": [{"id": "com.acme.mdm", "имя": "Device Management", "активен": True}]}, True),
    ({"прочитано": True, "cloud": {}, "профили": [{"id": "com.vpn.profile", "имя": "VPN", "активен": True}]}, False),
    ({"прочитано": True, "cloud": {}, "профили": []}, False),
    ({"прочитано": False, "ошибка": "timeout"}, None),
])
def test_mdm_verdict_matrix(probe, expect):
    assert mdm.verdict(probe)[0] is expect


def test_mdm_from_profiles_service_overrides_missing_usb_c_node():
    snap = _snap("iphone17pro_anon.snapshot.json")                # USB‑C: узла AIDBus нет
    snap["mdm"] = {"прочитано": True, "cloud": {}, "профили": []}
    rep = report_mod.build(snap)
    assert rep["правовой"]["mdm"] is False and rep["правовой"]["mdm_источник"].startswith("служба профилей")
    assert not any("MDM по кабелю не определился" in x for x in rep["сделать"])
    snap["mdm"] = {"прочитано": True, "cloud": {"IsSupervised": True, "OrganizationName": "Корп"}, "профили": []}
    rep = report_mod.build(snap)
    assert rep["правовой"]["mdm"] is True and rep["итог"]["вердикт"] == "ПРОБЛЕМНЫЙ"


@pytest.mark.parametrize("fixture", ["iphone12_FFXH33T20F0N.snapshot.json", "iphone12_ios26_anon.snapshot.json",
                                     "iphone17pro_anon.snapshot.json"])
def test_every_real_snapshot_builds_full_report(fixture):
    rep = report_mod.build(_snap(fixture))
    assert rep["паспорт"]["модель"] and rep["батарея"]["здоровье_%"] and rep["память"]["объём_гб"]
    assert rep["итог"]["вердикт"] in ("ИДЕАЛ", "ХОРОШИЙ", "ПРОВЕРКА НЕПОЛНАЯ", "ПРОБЛЕМНЫЙ")
    assert rep["apple_история_статус"] in ("получена", "не открыт", "формат не распознан", "не поддерживается")


@pytest.mark.parametrize("pt,back", [("iPhone15,2", False),    # 14 Pro — заднее стекло Apple не ведёт
                                     ("iPhone15,3", False),    # 14 Pro Max
                                     ("iPhone15,4", True),     # iPhone 15
                                     ("iPhone16,1", True),     # 15 Pro — на эталоне BackGlass = 1
                                     ("iPhone17,1", True),     # 16 Pro
                                     ("iPhone12,1", False)])   # iPhone 11 — только батарея и экран
def test_back_glass_tracked_only_since_iphone_15(pt, back):
    """Заднее стекло Apple ведёт с 15-й серии. Нумерация моделей это не разделяет:
    iPhone 14 Pro — это iPhone15,2, а iPhone 15 — iPhone15,4."""
    assert ("BackGlass" in capabilities.apple_tracked_parts(pt)) is back
