# -*- coding: utf-8 -*-
"""Эталон «не хуже 3uTools»: живой слепок iPhone 12 (FFXH33T20F0N) против
отчёта 3uTools о проверке того же телефона (2026-10-23)."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pintel_core.devicelink import snapshot
from pintel_core.analysis import report, serials
from pintel_core.external import sickw

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "fixtures_real", "iphone12_FFXH33T20F0N.snapshot.json")


def _rep():
    snap = snapshot.loads(open(SNAP, encoding="utf-8").read())
    snap["sickw"] = json.load(open(os.path.join(HERE, "fixtures_real", "sickw_357140400643287_61.json"), encoding="utf-8"))
    return report.build(snap)


def test_part_dates_match_3utools():
    assert serials.part_date("FG92027038HQ68CAT", 2020) == "2022-01-09"   # батарея
    assert serials.part_date("FG120270379PRVVAJ", 2020) == "2022-01-09"   # плата
    assert serials.part_date("DNL15271CEAMFGR99", 2020) == "2021-12-26"   # основная камера
    assert serials.part_date("DNM152414MGN0DNAD", 2020) == "2021-12-23"   # фронтальная
    assert serials.part_date("GVH14011L5ULQHMAU", 2020) == "2021-09-27"   # экран (LG)
    assert serials.device_production("FFXH33T20F0N", "iPhone13,2") == {"год": 2022, "неделя": 3, "полугодие": 1}
    assert serials.device_production("HMXYGW7HH7", "iPhone16,1") is None  # случайный серийник 2021+


def test_report_matches_3utools():
    r = _rep()
    p, b, s, l = r["паспорт"], r["батарея"], r["память"], r["правовой"]
    assert p["модель"] == "iPhone 12" and p["номер_модели"] == "MGJ53RM/A" and p["регион"] == "Россия/СНГ (RM)"
    assert p["серийник"] == "FFXH33T20F0N" and p["серийник_платы"] == "FG120270379PRVVAJ"
    assert p["bluetooth_mac"] == "34:fe:77:8b:e9:36" and p["cellular_mac"] == "34:fe:77:9b:f9:1c"
    assert p["wifi_mac"] == "34:fe:77:8d:0e:8e" and p["sim"] == "SIM не вставлена" and p["esim"]
    assert p["выпуск"] == "2022, неделя 3" and p["цвет"] == "Black"
    assert b["здоровье_%"] == 80 and b["циклы"] == 1690 and b["серийник"] == "FG92027038HQ68CAT"
    assert s["объём_гб"] == 64 and s["nand_производитель"] == "Toshiba" and s["nand_тип"] == "TLC"
    assert s["объём_сошёлся"] is True and s["свободно_гб"] == 39.1
    assert r["nand"]["разбор_верен"] and r["nand"]["прошивка_совпала_с_nvme"] is True
    assert l["найти_iphone"] == "включён" and l["активация"] == "Activated" and not l["mdm"]
    parts = {d["деталь"]: d for d in r["детали"]}
    assert parts["Основная камера"]["серийник"] == "DNL15271CEAMFGR99" and parts["Основная камера"]["дата"] == "2021-12-26"
    assert parts["Фронтальная камера"]["серийник"] == "DNM152414MGN0DNAD"
    assert parts["Экран (панель)"]["серийник"].startswith("GVH14011L5ULQHMAU") and parts["Экран (панель)"]["производитель"] == "LG"
    assert all(v["ок"] is not False for v in r["сигналы"].values())
    assert r["итог"]["вердикт"] == "ХОРОШИЙ", r["итог"]          # 1690 циклов — внимание, не стоп
    assert not r["не_прочиталось"], r["не_прочиталось"]


def test_sickw_service61_honest():
    raw = json.load(open(os.path.join(HERE, "fixtures_real", "sickw_357140400643287_61.json"), encoding="utf-8"))
    n = sickw.normalize(raw["все_поля"])
    assert n["цвет"] == "Black" and n["объём_гб"] == 64 and n["sim_lock"] == "разблокирован"
    assert n["дата_покупки"] == "2022-07-05" and "2023-07-04" in n["гарантия"]
    assert n["чёрный_список"] is None and n["icloud"] is None   # услуга 61 этого не отдаёт
