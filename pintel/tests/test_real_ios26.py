# -*- coding: utf-8 -*-
"""Два живых аппарата на iOS 26 (обезличенные слепки v3): iPhone 12 и iPhone 17 Pro.
Главные вопросы: читается ли IORegistry на iOS 26, что делать без AIDBus/Rosaline на
USB-C-аппарате, разбор GSX-описания Sickw."""
import json, os
from pintel_core.devicelink import snapshot
from pintel_core.external import sickw
from pintel_core.analysis import report as report_mod

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    snap = snapshot.loads(open(os.path.join(HERE, "fixtures_real", f"{name}.snapshot.json"), encoding="utf-8").read())
    sk = json.load(open(os.path.join(HERE, "fixtures_real", f"{name}.sickw.json"), encoding="utf-8"))
    snap["sickw"] = sickw.normalize(sickw.parse_result(sk["сырой_ответ"]))
    snap["sickw"]["службы"] = [61]
    return snap


def test_iphone12_ios26_reads_like_ios18():
    snap = load("iphone12_ios26_anon")
    assert snap["snapshot_version"] == 3 and len(snap["node_names"]) > 700
    rep = report_mod.build(snap)
    p, b, m = rep["паспорт"], rep["батарея"], rep["память"]
    assert p["модель"] == "iPhone 12" and p["ios"] == "26.6.1" and p["регион"] == "Россия/СНГ (RM)"
    assert p["sim"] == "SIM не вставлена" and p["esim"] is False
    assert p["цвет"] == "фиолетовый"
    assert b["здоровье_%"] == 78 and b["циклы"] == 2096 and b["заводская_мАч"] == 2798
    assert m["объём_гб"] == 64 and "Hynix" in str(m.get("nand_производитель")) and m["объём_сошёлся"]
    assert rep["nand"]["прошивка"] == "561.100.7" and rep["nand"]["прошивка_совпала_с_nvme"] is True
    sig = rep["сигналы"]
    for k in ("Face ID ↔ плата", "Taptic ↔ плата", "Экран: калибровка", "Экран: стекло ↔ панель",
              "Датчик приближения", "Тачскрин"):
        assert sig[k]["ок"] is True, (k, sig[k])
    assert rep["правовой"]["mdm"] is False and rep["правовой"]["найти_iphone"] == "включён"
    assert len(rep["apple_история"]) == 5 and not any(v["меняли"] for v in rep["apple_история"].values())
    # записи с нулями без сверки с печатью — не подтверждение Apple: зелёного нет, сотрудник сверяет раздел
    assert rep["детали_вердикт"]["итог"] == "кабель" and rep["итог"]["вердикт"] == "ПРОВЕРКА НЕПОЛНАЯ", rep["итог"]
    snap["repair_history_meta"] = {"формат": "записи обслуживания (iOS 26)", "дельта": []}   # сверка прочитана
    rep = report_mod.build(snap)
    assert rep["детали_вердикт"]["итог"] == "родные" and rep["итог"]["вердикт"] == "ХОРОШИЙ", rep["итог"]
    sk = rep["sickw"]
    assert sk["в_чёрном_списке"] is False and sk["fmi_включён"] is True and sk["sim_lock"] == "разблокирован"
    assert sk["гарантия"] == "Out Of Warranty" and sk["гарантия_до"] == "2023-02-01"
    parts = {d["деталь"]: d for d in rep["детали"]}
    assert parts["Экран (панель)"]["производитель"] == "LG" and parts["Аккумулятор"]["дата"] == "2021-08-11"
    assert parts["Материнская плата"].get("фабрика") is None           # непроверенные «фабрики» убраны


def test_iphone17pro_usb_c():
    snap = load("iphone17pro_anon")
    rep = report_mod.build(snap)
    p, b, m, leg = rep["паспорт"], rep["батарея"], rep["память"], rep["правовой"]
    assert p["модель"] == "iPhone 17 Pro" and p["регион"] == "Бахрейн/Кувейт (AH)"
    assert p["sim"] == "лотка нет (eSIM-only)" and p["esim_only"] and p["esim"] is True
    assert p["цвет"] == "оранжевый" and p["выпуск"] is None
    assert b["здоровье_%"] == 100 and b["циклы"] == 162 and not b["подделка"]
    assert m["объём_гб"] == 256 and "Sandisk" in str(m.get("nand_производитель"))
    assert rep["nand"]["прошивка"] == "2973.120.4" and rep["nand"]["прошивка_совпала_с_nvme"] is True
    # нет AIDBus (USB-C) → MDM честно не определился, а не «нет»
    assert leg["mdm"] is None
    assert any("MDM" in x for x in rep["сделать"])
    # криптопривязка Face ID по кабелю не читается, но история Apple говорит «не меняли»
    sig = rep["сигналы"]
    assert sig["Face ID ↔ плата"]["ок"] is True and sig["Face ID ↔ плата"].get("источник") == "Apple"
    assert sig["Taptic ↔ плата"]["ок"] is True and sig["Телефото"]["ок"] is True
    assert sig["Датчик приближения"]["ок"] is None                      # у 17 Pro свой драйвер, данных пока нет
    assert len(rep["apple_история"]) == 7 and "BackGlass" in rep["apple_история"]
    # записи iOS 26 с нулями, сверки с печатью в слепке нет → зелёного не даём, сотрудник сверяет раздел
    assert rep["детали_вердикт"]["итог"] == "кабель" and rep["итог"]["вердикт"] == "ПРОВЕРКА НЕПОЛНАЯ", rep["итог"]
    assert not any("Face ID" in x for x in rep["не_прочиталось"])
    sk = rep["sickw"]
    assert sk["гарантия"] == "Limited Warranty" and sk["fmi_включён"] is False and sk["в_чёрном_списке"] is False
    assert sk["подменный"] is False and sk["восстановленный"] is False and sk["регион_gsx"] == "NAJP"
    parts = {d["деталь"]: d for d in rep["детали"]}
    assert parts["Телефото камера"]["серийник"].startswith("F0W") and parts["Taptic Engine"]["серийник"].startswith("GH9")
    assert "Модуль Nova (назначение уточняется)" in parts


def test_sickw_gsx_description_and_flags():
    g = sickw.parse_gsx_description("IPHONE 17 PRO,NAJP,256GB,ORN")
    assert g == {"модель": "iPhone 17 Pro", "объём_гб": 256, "цвет_код": "ORN", "регион_gsx": "NAJP"}
    assert sickw.parse_gsx_description("IPHONE 12,ROW,64GB,PURPLE")["цвет_код"] == "PURPLE"
    assert sickw.parse_gsx_description("") == {}
    n = sickw.normalize({"Model Description": "IPHONE 17 PRO,NAJP,1TB,DST", "Loaner Device": "Yes",
                         "Demo Unit": "No", "Sim-Lock Status": "Locked", "Locked Carrier": "AT&T"})
    assert n["цвет"] == "пустынный титан" and n["объём_гб"] == 1024 and n["модель_строка"] == "iPhone 17 Pro"
    assert n["подменный"] is True and n["демо"] is False and n["восстановленный"] is None
    assert n["sim_lock"].startswith("заблокирован под оператора: AT&T")
    assert sickw.colour_ru("Black") == "чёрный" and sickw.colour_ru("Mauve") == "Mauve"


def test_report_loaner_is_stop_and_used_part_is_stop():
    snap = load("iphone17pro_anon")
    snap["sickw"]["все_поля"]["Loaner Device"] = "Yes"          # разбор пересчитывается из полей
    rep = report_mod.build(snap)
    assert rep["итог"]["вердикт"] == "ПРОБЛЕМНЫЙ" and any("Loaner" in x for x in rep["стоп"])
    snap = load("iphone12_ios26_anon")
    snap["repair_history"]["Display"]["меняли"] = True
    snap["repair_history"]["Display"]["бу"] = True
    rep = report_mod.build(snap)
    assert any("Экран меняли, установлена б/у деталь" in x for x in rep["стоп"])
    snap["repair_history"]["Display"]["бу"] = False
    rep = report_mod.build(snap)
    assert any("Экран меняли (новая деталь" in x for x in rep["внимание"]) and rep["итог"]["вердикт"] != "ПРОБЛЕМНЫЙ"
