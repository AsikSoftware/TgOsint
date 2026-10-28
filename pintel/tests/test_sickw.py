# -*- coding: utf-8 -*-
"""Sickw: разбор крашеного HTML, несколько служб, кэш с сырым ответом, влияние на вердикт."""
import json, os

import pytest
from pintel_core.external import sickw
from pintel_core.devicelink import snapshot
from pintel_core.analysis import report as report_mod

HERE = os.path.dirname(os.path.abspath(__file__))
IMEI = "490154203237518"            # учебный IMEI, проходит Luhn

HTML_61 = ('Model: iPhone 12 64GB Black [A2403] [iPhone13,2]<br>'
           'Locked Carrier: 10 - Unlock.<br>'
           'Find My iPhone: <font color="red">ON</font><br>'
           'Blacklist Status: <font color="green">CLEAN</font><br>')
HTML_54 = '<p><b>WW Blacklist Status:</b></p><p><span style="color:red">BLACKLISTED</span></p>'


def test_parse_keeps_coloured_values():
    f = sickw.parse_result(HTML_61)
    assert f["Find My iPhone"] == "ON" and f["Blacklist Status"] == "CLEAN"
    assert f["Locked Carrier"] == "10 - Unlock."


def test_parse_label_and_value_in_separate_blocks():
    assert sickw.parse_result(HTML_54) == {"WW Blacklist Status": "BLACKLISTED"}
    assert sickw.parse_result({"FMI": "OFF", "x": None}) == {"FMI": "OFF"}


def test_flags():
    assert sickw.fmi_flag("ON") is True and sickw.fmi_flag("OFF") is False
    assert sickw.fmi_flag("Unknown") is None and sickw.fmi_flag("") is None
    assert sickw.blacklist_flag("CLEAN") is False
    assert sickw.blacklist_flag("Not Blacklisted") is False
    assert sickw.blacklist_flag("BLACKLISTED (Lost/Stolen)") is True
    assert sickw.blacklist_flag("") is None


def test_normalize_strictest_wins():
    n = sickw.normalize({"Blacklist Status": "CLEAN", "GSMA Blacklist Status": "BLACKLISTED",
                         "Find My iPhone": "OFF", "iCloud Lock": "ON"})
    assert n["в_чёрном_списке"] is True and n["чёрный_список"] == "BLACKLISTED"
    assert n["fmi_включён"] is True and n["icloud"] == "ON"


def test_service61_fixture_stays_honest():
    raw = json.load(open(os.path.join(HERE, "fixtures_real", "sickw_357140400643287_61.json"), encoding="utf-8"))
    n = sickw.normalize(raw["все_поля"])
    assert n["в_чёрном_списке"] is None and n["fmi_включён"] is None
    assert n["sim_lock"] == "разблокирован" and n["цвет"] == "чёрный"


def test_lookup_many_merges_caches_and_survives_one_bad_service(monkeypatch, tmp_path):
    calls = []

    def fake_get(params, timeout=60):
        calls.append(dict(params))
        s = int(params["service"])
        if s == 61:
            return {"status": "success", "result": HTML_61}
        if s == 54:
            return {"status": "success", "result": HTML_54}
        return {"status": "error", "result": "Wrong service ID"}

    monkeypatch.setattr(sickw, "_get", fake_get)
    r = sickw.lookup_many(IMEI, "k", services=[61, 54, 99], cache_dir=str(tmp_path))
    assert r["службы"] == [61, 54] and list(r["ошибки_служб"]) == ["99"]
    assert r["fmi_включён"] is True
    assert r["в_чёрном_списке"] is True and r["чёрный_список"] == "BLACKLISTED"   # 54 строже 61
    assert r["sim_lock"] == "разблокирован" and r["из_кэша"] is False
    assert len(calls) == 3
    assert (tmp_path / f"{IMEI}_61.json").exists() and not (tmp_path / f"{IMEI}_99.json").exists()
    cached = json.load(open(tmp_path / f"{IMEI}_61.json", encoding="utf-8"))
    assert cached["сырой_ответ"] == HTML_61

    r2 = sickw.lookup_many(IMEI, "k", services=[61, 54], cache_dir=str(tmp_path))
    assert len(calls) == 3 and r2["из_кэша"] is True and r2["fmi_включён"] is True

    # кэш старого формата (без сырого ответа) — перечитываем с сервера, один раз
    cached.pop("сырой_ответ")
    json.dump(cached, open(tmp_path / f"{IMEI}_61.json", "w", encoding="utf-8"))
    sickw.lookup(IMEI, "k", cache_dir=str(tmp_path), service=61)
    assert len(calls) == 4

    # --fresh: кэш не читаем
    sickw.lookup_many(IMEI, "k", services=[61], cache_dir=str(tmp_path), use_cache=False)
    assert len(calls) == 5


def test_lookup_many_all_failed_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(sickw, "_get", lambda p, timeout=60: {"status": "error", "result": "Invalid API key"})
    try:
        sickw.lookup_many(IMEI, "bad", services=[61], cache_dir=str(tmp_path))
    except RuntimeError as e:
        assert "Invalid API key" in str(e)
    else:
        raise AssertionError("ожидали исключение")
    assert not list(tmp_path.iterdir())


def _real_snapshot():
    p = os.path.join(HERE, "fixtures_real", "iphone12_FFXH33T20F0N.snapshot.json")
    return snapshot.loads(open(p, encoding="utf-8").read())


def test_report_blacklisted_is_stop():
    snap = _real_snapshot()
    snap["sickw"] = sickw.normalize({"Model": "iPhone 12 64GB Black", "Blacklist Status": "BLACKLISTED"})
    rep = report_mod.build(snap)
    assert rep["итог"]["вердикт"] == "ПРОБЛЕМНЫЙ"
    assert any("чёрном списке" in x for x in rep["стоп"])


def test_report_fmi_from_sickw_only_is_todo_not_stop():
    snap = _real_snapshot()
    before = report_mod.build(snap)
    snap["sickw"] = sickw.normalize({"Model": "iPhone 12 64GB Black", "Find My iPhone": "ON",
                                     "Blacklist Status": "CLEAN"})
    rep = report_mod.build(snap)
    assert rep["итог"]["вердикт"] == before["итог"]["вердикт"]
    assert not any("чёрном списке" in x for x in rep["стоп"])


@pytest.mark.parametrize("model,цвет", [
    ("iPhone 14 Pro A2891", None),                      # в сделке 7093 сюда уехало «Pro A2891»
    ("iPhone 14 Pro Space Black 256GB", "чёрный космос"),
    ("iPhone 15 Pro Max Natural Titanium", "натуральный титан"),
    ("iPhone SE Red", "красный"),
    ("iPhone 13 mini Midnight", "тёмная ночь"),
    ("iPhone 11 Purple", "фиолетовый"),
])
def test_colour_does_not_keep_model_variant(model, цвет):
    """Цвет вырезался регуляркой «от начала строки», и она срезала только «iPhone 14 » —
    вариант модели оставался в цвете. В карточке Оценки это выглядело как «Цвет: Pro A2891»,
    а у Pro Max и SE — «Pro Max Natural Titanium» и «Se Red»."""
    assert sickw.normalize({"Model": model}).get("цвет") == цвет
