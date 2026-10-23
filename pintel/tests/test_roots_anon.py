# -*- coding: utf-8 -*-
"""228 реальных паспортов (lockdown root) разных моделей и iOS 15–27, обезличенные:
серийники/IMEI/ICCID заменены на X той же длины. Регрессия парсера паспорта."""
import json, os, collections
from pintel_core.analysis import passport

HERE = os.path.dirname(os.path.abspath(__file__))
ROWS = json.load(open(os.path.join(HERE, "fixtures_real", "roots_anon.json"), encoding="utf-8"))
ALLOWED_UNKNOWN_REGIONS = {"AF/A"}        # код не найден ни в одном открытом списке


def test_all_roots_build():
    assert len(ROWS) >= 200
    unknown_regions = collections.Counter()
    for r in ROWS:
        p = passport.build(r)
        if r["ProductType"].startswith("iPhone"):              # справочник моделей — только iPhone
            assert "не в справочнике" not in p["модель"], r["ProductType"]
        assert p["sim"], r
        assert p["регион"], r
        if p["регион"].startswith("не распознан"):
            unknown_regions[r["RegionInfo"]] += 1
        assert p["код_региона"] == r["RegionInfo"].split("/")[0]
    assert set(unknown_regions) <= ALLOWED_UNKNOWN_REGIONS, unknown_regions


def test_region_names_for_frequent_codes():
    by = {r["RegionInfo"]: passport.build(r)["регион"] for r in ROWS}
    assert by["RK/A"] == "Казахстан (RK)" and by["RM/A"] == "Россия/СНГ (RM)"
    assert by["LL/A"] == "США (LL)" and by["J/A"] == "Япония (J)" and by["HN/A"] == "Индия (HN)"
    assert by["VC/A"] == "Канада (VC)" and by["LZ/A"].startswith("Чили")


def test_sim_and_esim_cases():
    def pick(**cond):
        for r in ROWS:
            if all(r.get(k) == v for k, v in cond.items()):
                return r
        raise AssertionError(f"нет строки {cond}")
    # eSIM-only (американские/японские модели): лотка нет, профиль в первом слоте
    r = pick(SIMTrayStatus="kCTSIMSupportSIMTrayAbsent", SIM1IsEmbedded=True)
    p = passport.build(r)
    assert p["sim"] == "лотка нет (eSIM-only)" and p["esim_only"] and p["esim"] is True
    # физическая SIM в лотке + первый слот eSIM с профилем (RK/A iPhone 13 Pro)
    r = pick(SIMTrayStatus="kCTSIMSupportSIMTrayInsertedWithSIM", SIM1IsEmbedded=True, SIM2IsEmbedded=False)
    p = passport.build(r)
    assert p["sim"] == "в лотке SIM-карта" and p["sim_в_лотке"] and p["esim"] is True
    # пустой лоток, без eSIM-данных
    r = next(x for x in ROWS if x.get("SIMTrayStatus") == "kCTSIMSupportSIMTrayInsertedNoSIM"
             and "SIM1IsEmbedded" not in x and "SIM2IsEmbedded" not in x)
    p = passport.build(r)
    assert p["sim"] == "SIM не вставлена" and p["esim"] is False and not p["sim_в_лотке"]
