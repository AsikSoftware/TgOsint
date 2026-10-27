# -*- coding: utf-8 -*-
"""Эталоны: сверка нашего вердикта с экраном телефона и библиотека эталонов.

Каждый файл в fixtures_real/эталоны/*.zip — живой аппарат с известной правдой.
Тест прогоняет его через отчёт и требует совпадения: так однажды разобранный
случай больше не сломается.
"""
import glob
import os

import pytest

from pintel_core import reference
from pintel_core.analysis import report as report_mod
from pintel_core.devicelink import snapshot
from pintel_core.external import sickw

HERE = os.path.dirname(os.path.abspath(__file__))
ETALONS = sorted(glob.glob(os.path.join(HERE, "fixtures_real", "эталоны", "*.zip")))


def _snap(name):
    return snapshot.loads(open(os.path.join(HERE, "fixtures_real", name), encoding="utf-8").read())


REAL = ("iphone12_ios26_anon.snapshot.json", "iphone17pro_anon.snapshot.json",
        "iphone12_FFXH33T20F0N.snapshot.json")


@pytest.mark.parametrize("name", REAL)
def test_pseudonymize_keeps_every_conclusion(name):
    """Обезличивание не имеет права изменить ни один вывод отчёта — на всех живых слепках."""
    snap = _snap(name)
    clean, done, why = reference.pseudonymize(snap, report_mod.build)
    assert done, why
    before, after = report_mod.build(snap), report_mod.build(clean)
    assert reference._conclusions(before) == reference._conclusions(after)
    assert after["паспорт"]["модель"] == before["паспорт"]["модель"]    # модель и iOS не трогаем
    assert after["паспорт"]["ios"] == before["паспорт"]["ios"]
    assert after["паспорт"]["регион"] == before["паспорт"]["регион"]
    for поле in ("серийник", "imei"):
        было, стало = before["паспорт"][поле], after["паспорт"][поле]
        if было and len(set(было)) > 2:          # в обезличенных слепках стоят заглушки из одного знака
            assert стало != было, поле
    if after["паспорт"]["imei"]:
        assert sickw.luhn_ok(after["паспорт"]["imei"])                  # контрольная цифра пересчитана


def test_pseudonymize_keeps_equal_serials_equal():
    """Сопряжение деталей сверяет серийники между узлами — равенство обязано сохраниться."""
    table = reference._substitution("соль")
    assert reference._sub_value("GVH122154X3LQHMA9", table) == reference._sub_value("GVH122154X3LQHMA9", table)
    assert reference._sub_value("GVH122154X3LQHMA9", table) != reference._sub_value("GVH122154X3LQHMA8", table)
    assert reference._sub_value("FXP11821H1BPFFK94", table).isalnum()


def test_compare_catches_the_demo_case():
    """iPhone 15 Pro с демо: телефон писал «сервисное обслуживание» и «неизвестно»,
    а мы показывали зелёное. Сверка обязана это назвать."""
    rep = {"детали_вердикт": {"итог": "родные", "apple_подтверждено": True,
                              "детали": [{"деталь": "Аккумулятор", "статус": "ok", "почему": "ок"},
                                         {"деталь": "Дисплей", "статус": "ok", "почему": "ок"}]},
           "apple_история": {"Display": {"деталь": "Дисплей", "меняли": False}},
           "apple_история_статус": "получена"}
    truth = reference.truth_template(детали={"Battery": "serviced", "Display": "unknown"}, раздел_открывали=True)
    bad = reference.compare(rep, truth)
    assert len(bad) == 3, bad
    assert any("Аккумулятор" in b and "Сервисное обслуживание" in b for b in bad)
    assert any("Дисплей" in b and "Неизвестная запасная часть" in b for b in bad)
    assert any("все детали родные" in b for b in bad)


def test_compare_silent_when_everything_matches():
    rep = {"детали_вердикт": {"итог": "родные", "apple_подтверждено": True,
                              "детали": [{"деталь": "Аккумулятор", "статус": "ok", "почему": "ок"},
                                         {"деталь": "Дисплей", "статус": "ok", "почему": "ок"}]},
           "apple_история": {"Display": {"деталь": "Дисплей", "меняли": False}},
           "apple_история_статус": "получена"}
    truth = reference.truth_template(детали={"Battery": "genuine", "Display": "genuine"}, раздел_открывали=True)
    assert reference.compare(rep, truth) == []


def test_states_are_apple_wording():
    """Варианты в опросе — официальные формулировки Apple, а не наши выдумки."""
    assert reference.STATES["unknown"] == "Неизвестная запасная часть"
    assert reference.STATES["unverified"] == "Непроверенная запасная часть"
    assert reference.STATES["used"] == "Запасная часть использовалась"
    assert reference.STATES["finish"] == "Завершение ремонта"
    assert set(reference.MUST_STOP) == {"unknown", "unverified"}        # обе — СТОП для выкупа


def test_compare_wants_raw_log_when_section_was_opened():
    """Клиент открыл раздел, а мы ничего не разобрали — это дыра, её надо назвать."""
    rep = {"детали_вердикт": {"итог": "кабель"}, "apple_история": None, "apple_история_статус": "формат не распознан"}
    bad = reference.compare(rep, reference.truth_template(детали={}, раздел_открывали=True))
    assert any("сырые строки" in b for b in bad)


def test_bundle_roundtrip(tmp_path):
    """Эталон хранит сырой журнал, и при загрузке он разбирается заново текущим кодом:
    так регрессия разбора ломает тест, а не прячется за сохранённым выводом."""
    snap = _snap("iphone12_ios26_anon.snapshot.json")
    rep = report_mod.build(snap)
    truth = reference.truth_template(детали={"Display": "unknown"}, кто="Данияр")
    raw = ("Oct 27 06:59:05 iPhone Preferences(CoreRepairKit)[1] <Notice>: systemhealth {\n"
           "    Battery = 1;\n    Display = \"-1\";\n    FaceID = 1;\n}\n")
    path = reference.save_bundle(str(tmp_path / reference.bundle_name(rep)), snap, rep, truth,
                                 raw=raw, mismatches=["Дисплей: расхождение"], dumps=snapshot.dumps)
    assert os.path.basename(path).startswith("эталон_iPhone-12_iOS26.6.1_")
    snap2, truth2 = reference.load_bundle(path, loads=snapshot.loads)
    assert truth2["детали"] == {"Display": "unknown"} and truth2["кто"] == "Данияр"
    hist = snap2["repair_history"]                        # журнал разобран заново
    assert hist["Display"]["неизвестная"] and not hist["Battery"]["меняли"]
    assert reference.compare(report_mod.build(snap2), truth2) == []


@pytest.mark.skipif(not ETALONS, reason="эталонов пока нет: соберите «pintel-doctor reference» на живых аппаратах")
@pytest.mark.parametrize("path", ETALONS, ids=[os.path.basename(p) for p in ETALONS])
def test_reference_matches_phone_screen(path):
    """Вердикт по эталону обязан совпадать с тем, что показывал экран телефона."""
    snap, truth = reference.load_bundle(path, loads=snapshot.loads)
    bad = reference.compare(report_mod.build(snap), truth)
    assert not bad, os.path.basename(path) + ":\n  " + "\n  ".join(bad)
