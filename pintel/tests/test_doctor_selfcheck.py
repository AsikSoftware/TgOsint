# -*- coding: utf-8 -*-
"""Проверка окружения доктора: она обязана сама ловить поломки сборки.

Поломка с wintun.dll жила незаметно именно потому, что проверять было нечего: туннель
не поднимался, данные по кабелю молча терялись, а узнали мы об этом только по журналу
живого аппарата.
"""
from pintel_core import doctor


def test_tunnel_channel_is_checked():
    """Канал либо «есть», либо названа причина — третьего (молчания) быть не должно."""
    состояние = doctor.канал_туннеля()
    assert состояние == "есть" or состояние.startswith("НЕТ — "), состояние


def test_selfcheck_prints_tunnel_state(capsys):
    doctor.cmd_selfcheck(doctor._A(), {"_path": None, "sickw": {}})
    напечатано = capsys.readouterr().out
    assert "туннель CoreDevice" in напечатано


def test_missing_wintun_is_named(monkeypatch):
    """На Windows без wintun.dll проверка обязана сказать это прямо, с путём."""
    monkeypatch.setattr(doctor.os, "name", "nt")
    monkeypatch.setattr(doctor.os.path, "isfile", lambda p: False)
    состояние = doctor.канал_туннеля()
    assert состояние.startswith("НЕТ — ") and ("wintun.dll" in состояние or "pytun_pmd3" in состояние), состояние
