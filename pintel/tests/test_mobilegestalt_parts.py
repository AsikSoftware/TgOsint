# -*- coding: utf-8 -*-
"""Канал MobileGestalt (diagnostics → туннель CoreDevice) и единый вердикт по деталям.
Главное: вердикт по деталям есть на любом iOS без действий клиента."""
import asyncio
import pytest

from pintel_core.devicelink import mobilegestalt as mg
from pintel_core.analysis import parts


class FakeDiag:
    def __init__(self, mode):
        self.mode = mode          # "ok" | "deprecated" | "error"

    async def mobilegestalt(self, keys):
        if self.mode == "deprecated":
            from pymobiledevice3.exceptions import DeprecationError
            raise DeprecationError("MobileGestalt deprecated on iOS 17.4+")
        if self.mode == "error":
            raise RuntimeError("boom")
        return {"Status": "Success", "FDRSealingStatus": True, "IsServicePart": False,
                "DeviceEnclosureColor": 1, "BatterySerialNumber": "ABC"}


def test_diagnostics_channel_old_ios():
    r = asyncio.run(mg.read(FakeDiag("ok"), serial="UDID"))
    assert r["канал"] == "diagnostics"
    assert r["значения"]["FDRSealingStatus"] is True and "Status" not in r["значения"]


def test_deprecated_falls_back_to_tunnel(monkeypatch):
    called = {}
    async def fake_tunnel(serial, keys, timeout):
        called["serial"] = serial
        return {"FDRSealingStatus": True, "DeviceEnclosureColor": 9}, None, {"model": "x"}
    monkeypatch.setattr(mg, "_via_coredevice", fake_tunnel)
    r = asyncio.run(mg.read(FakeDiag("deprecated"), serial="UDID17"))
    assert r["канал"] == "coredevice" and called["serial"] == "UDID17"
    assert r["значения"]["DeviceEnclosureColor"] == 9 and r["device_info"] == {"model": "x"}


def test_tunnel_failure_is_not_fatal(monkeypatch):
    async def fail(serial, keys, timeout):
        return {}, "NoDeviceConnectedError: нет", None
    monkeypatch.setattr(mg, "_via_coredevice", fail)
    r = asyncio.run(mg.read(FakeDiag("deprecated"), serial="x"))
    assert r["канал"] == "нет" and "туннель" in r["ошибка"]


def test_seal_summary():
    assert mg.seal_summary({"FDRSealingStatus": True, "IsServicePart": False})["печать_цела"] is True
    assert mg.seal_summary({"IsServicePart": 1})["сервисная_деталь"] is True
    assert mg.seal_summary({})["печать_цела"] is None


def test_parts_verdict_from_cable_only_no_log():
    """Экран, Face ID, батарея подтверждены приводкой, но без Apple зелёного нет: «кабель».
    У модели без раздела «Детали и обслуживание» кабель — единственный источник: «родные»."""
    sig = {"Face ID ↔ плата": {"ок": True, "почему": "сошлась"},
           "Экран: калибровка": {"ок": True, "почему": "ок"},
           "Основная камера": {"ок": True, "почему": "есть"}}
    v = parts.verdict({}, sig, {}, {"есть_данные": True, "подделка": []}, {"печать_цела": True})
    assert v["итог"] == "кабель" and v["каналы"]["кабель"] and not v["каналы"]["журнал"]
    assert not v["apple_подтверждено"] and "Apple" in v["почему"]
    v2 = parts.verdict({}, sig, {}, {"есть_данные": True, "подделка": []}, {"печать_цела": True}, apple_supported=False)
    assert v2["итог"] == "родные"
    # записи iOS 26 с нулями без сверки — тоже не подтверждение (демо iPhone 15 Pro)
    hist = {"Display": {"деталь": "Экран", "меняли": False, "бу": False, "дата": ""}}
    assert parts.verdict({}, sig, hist, {}, {}, {"формат": "записи обслуживания (iOS 26)"})["итог"] == "кабель"
    assert parts.verdict({}, sig, hist, {}, {}, {"формат": "записи обслуживания (iOS 26)", "дельта": []})["итог"] == "родные"


def test_parts_verdict_fake_face_id_is_replacement():
    sig = {"Face ID ↔ плата": {"ок": False, "почему": "чужой модуль"}}
    v = parts.verdict({}, sig, {}, {}, {})
    assert v["итог"] == "замена"
    assert any(d["статус"] == "bad" and d["деталь"] == "Face ID" for d in v["детали"])


def test_parts_verdict_seal_broken_without_any_signal():
    v = parts.verdict({}, {}, {}, {}, {"печать_цела": False})
    assert v["итог"] == "замена" and any("печать" in d["почему"] for d in v["детали"])


def test_parts_verdict_service_part_is_repair():
    v = parts.verdict({}, {"Экран: калибровка": {"ок": True, "почему": "ок"}}, {}, {}, {"сервисная_деталь": True})
    assert v["итог"] == "ремонт"


def test_parts_verdict_log_enriches_with_date_and_used():
    sig = {"Экран: калибровка": {"ок": True, "почему": "ок"}}
    hist = {"Display": {"деталь": "Экран", "меняли": True, "бу": True, "дата": "2026-03-01"}}
    v = parts.verdict({}, sig, hist, {}, {})
    disp = [d for d in v["детали"] if d["деталь"] == "Экран"][0]
    assert disp["статус"] == "used" and "2026-03-01" in disp["почему"] and v["итог"] == "ремонт"


def test_parts_verdict_empty_is_incomplete():
    assert parts.verdict({}, {}, {}, {}, {})["итог"] == "неполно"


def test_broken_tunnel_is_named_not_hidden():
    """Канал пропал — проверка обязана это назвать. На живом iPhone 14 Pro в сборке не
    оказалось wintun.dll, туннель не поднялся, и по кабелю молча терялись цвет корпуса и
    серийники модулей: отчёт выглядел целым. Теперь это строка в «не прочиталось»."""
    import os
    from pintel_core.analysis import report as report_mod
    from pintel_core.devicelink import snapshot
    here = os.path.dirname(os.path.abspath(__file__))
    snap = snapshot.loads(open(os.path.join(here, "fixtures_real", "iphone12_ios26_anon.snapshot.json"),
                               encoding="utf-8").read())
    snap["mobilegestalt"] = {"недоступен": "туннель: нет CoreDevice: Failed to load dynlib "
                                           "'...\\\\pytun_pmd3\\\\wintun\\\\bin\\\\amd64\\\\wintun.dll'", "_канал": "нет"}
    было = report_mod.build(snap)["итог"]["вердикт"]
    rep = report_mod.build(snap)
    assert rep["служебное"] and "wintun.dll" in rep["служебное"][0], rep["служебное"]
    # и при этом вердикт по самому аппарату не портится: это неисправность нашей сборки
    assert rep["итог"]["вердикт"] == было
    assert not any("MobileGestalt" in x for x in rep["не_прочиталось"])

    snap["mobilegestalt"] = {"недоступен": "DeprecationError: deprecated on iOS 17.4 and later"}
    assert any("17.4" in x for x in report_mod.build(snap)["служебное"])
