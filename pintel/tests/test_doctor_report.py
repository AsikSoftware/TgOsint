# -*- coding: utf-8 -*-
"""Печать отчёта доктора — тот самый текст, который читает оценщик и которым CI
проверяет exe («pintel-doctor report»).

Тест появился после сборки, упавшей на `NameError` в этой функции: все 312 тестов были
зелёными, потому что печать отчёта не вызывал ни один из них. Любая строка здесь
обращается к десяткам ключей отчёта, и промах в имени — обычная поломка, а не
экзотика. Поэтому печать прогоняется на ВСЕХ живых эталонах: если ключ переехал,
падает тест, а не сборка.
"""
import glob
import os

import pytest

from pintel_core import doctor, reference
from pintel_core.analysis import report as report_mod
from pintel_core.devicelink import snapshot

HERE = os.path.dirname(os.path.abspath(__file__))
ETALONS = sorted(glob.glob(os.path.join(HERE, "fixtures_real", "эталоны", "*.zip")))


@pytest.mark.skipif(not ETALONS, reason="эталонов пока нет")
@pytest.mark.parametrize("path", ETALONS, ids=[os.path.basename(p) for p in ETALONS])
def test_report_prints_for_every_real_phone(path):
    """На каждом живом аппарате отчёт обязан напечататься целиком и без исключений."""
    snap, _ = reference.load_bundle(path, loads=snapshot.loads)
    текст = doctor.fmt_report(report_mod.build(snap))
    assert "ИТОГ" in текст and "Джейлбрейк" in текст
    assert "None" not in текст, "в тексте для оценщика не должно быть «None»:\n" + текст


def test_tunnel_diagnostics_are_printed():
    """Диагностика туннеля живёт в слепке, а печатает её доктор — у него на руках только
    отчёт. Значит отчёт обязан её переносить, иначе строка молча пропадёт (или, как было,
    уронит печать обращением к несуществующему слепку)."""
    snap, _ = reference.load_bundle(ETALONS[0], loads=snapshot.loads)
    snap = dict(snap)
    snap["mobilegestalt"] = dict(snap.get("mobilegestalt") or {},
                                 _диагностика={"служб": 7, "coredevice": "нет", "список": ["a", "b"]})
    rep = report_mod.build(snap)
    assert rep["mobilegestalt_диагностика"] == {"служб": 7, "coredevice": "нет", "список": ["a", "b"]}
    строка = [с for с in doctor.fmt_report(rep).splitlines() if "Туннель CoreDevice" in с]
    assert len(строка) == 1 and "служб=7" in строка[0] and "coredevice=нет" in строка[0]
    assert "список" not in строка[0]                     # перечень служб в отчёт не тащим


def test_report_survives_an_empty_snapshot():
    """Пустой слепок (телефон отключили на полпути) печатается, а не падает."""
    текст = doctor.fmt_report(report_mod.build({}))
    assert "ИТОГ" in текст
