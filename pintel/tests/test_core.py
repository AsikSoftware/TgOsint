# -*- coding: utf-8 -*-
import os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from pintel_core.devicelink import nand
from pintel_core.analysis import battery, storage, report
from pintel_core.external import pricing
from fixtures import INVENTORIES, load_snapshot


def test_nand_zero_record_in_middle_is_not_end():
    blob = b""
    blob += struct.pack("<II", 0x031, 1) + struct.pack("<Q", 7)
    blob += struct.pack("<II", 0, 0)                       # «конец», который не конец
    blob += struct.pack("<II", 0x039, 1) + struct.pack("<Q", 1700000000)
    fw = b"2010.1.4\x00\x00\x00\x00\x00\x00\x00\x00"
    blob += struct.pack("<II", 0x2a8, 2) + fw
    recs, rest = nand.parse(blob)
    assert rest == 0 and recs[0x039] == [1700000000] and 0 in recs
    s = nand.summarize(blob, "2010.1.4")
    assert s["разбор_верен"] and s["прошивка"] == "2010.1.4" and s["прошивка_совпала_с_nvme"] is True


def test_battery_nested_batterydata_new_ios():
    node = {"BatteryData": {"DesignCapacity": 4441, "NominalChargeCapacity": 4147, "CycleCount": 312},
            "Serial": b"F8Y33\x00", "MaxCapacity": 100}
    b = battery.analyze(node)
    assert b["здоровье_%"] == 93 and b["циклы"] == 312 and b["серийник"] == "F8Y33"
    assert not b["подделка"]
    fake = battery.analyze({"DesignCapacity": 2798, "NominalChargeCapacity": 3100, "CycleCount": 5})
    assert fake["подделка"], fake


def test_storage_marketed_and_fill():
    d = {"TotalDiskCapacity": 255987556352, "TotalDataCapacity": 250000000000,
         "TotalDataAvailable": 102000000000}
    nv = {"Controller Characteristics": {"capacity": 255987556352}, "Model Number": "APPLE SSD AP0256Z",
          "Firmware Revision": "2010.1.4"}
    s = storage.analyze(d, nv)
    assert s["объём_гб"] == 256 and s["nvme_модель_гб"] == 256 and s["объём_сошёлся"] is True
    assert s["занято_гб"] == 148.0 and s["свободно_гб"] == 102.0 and s["занято_%"] == 59
    assert storage.analyze({"TotalDiskCapacity": 64000000000})["объём_гб"] == 64


def test_pricing_wear_grid():
    grid = {"база": {"iPhone18,2": {"256": 510000}},
            "сетка_износа": {"iPhone18,2": {"256": {"неизвестно": None, "0-74": None, "75-79": None,
                                                     "80-85": None, "86-90": None, "91-95": 470000,
                                                     "96-99": 490000, "100": 510000, "100новый": 510000}}}}
    assert pricing.estimate(grid, "iPhone18,2", 256, 93, 150)["цена"] == 470000
    assert pricing.estimate(grid, "iPhone18,2", 256, 100, 12)["цена"] == 510000
    e = pricing.estimate(grid, "iPhone18,2", 256, 70, 900)
    assert e["цена"] is None and "не задаёт" in e["нехватка"][0]
    e = pricing.estimate(grid, "iPhone18,2", 256, None, None)
    assert e["цена"] is None


def test_reports_on_real_inventories():
    assert len(INVENTORIES) >= 6, "нет архивных слепков"
    for path in INVENTORIES:
        snap = load_snapshot(path)
        rep = report.build(snap)
        p, b, s = rep["паспорт"], rep["батарея"], rep["память"]
        assert rep["итог"]["вердикт"] in ("ИДЕАЛ", "ХОРОШИЙ", "ПРОБЛЕМНЫЙ", "ПРОВЕРКА НЕПОЛНАЯ")
        if not snap["root"]:
            # неполный архивный слепок: отчёт не падает и честно говорит «неполная»
            assert rep["итог"]["вердикт"] == "ПРОВЕРКА НЕПОЛНАЯ", (path, rep["итог"])
            print(f"{os.path.basename(path)[:26]} неполный слепок → {rep['итог']['вердикт']}")
            continue
        assert p["код_модели"].startswith("iPhone"), path
        assert "не в справочнике" not in p["модель"], p["модель"]
        assert b["есть_данные"] and 40 <= b["здоровье_%"] <= 100, (path, b)
        assert s["объём_гб"] in storage.STEPS, (path, s)
        print(f"{os.path.basename(path)[:26]} {p['модель']:<16} iOS {p['ios']:<7} "
              f"бат {b['здоровье_%']}% {b['циклы']}ц  {s['объём_гб']}ГБ своб {s['свободно_гб']}  "
              f"→ {rep['итог']['вердикт']}: {rep['итог']['почему'][:70]}")
