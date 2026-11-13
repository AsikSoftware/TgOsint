# -*- coding: utf-8 -*-
"""Самопроверка собранной программы обязана знать обо всём, чем ядро ходит к телефону.

Сборка doctor-85 ушла на точки без чтения отчётов о сбоях: модуль не загрузился в exe, а
тесты, которые гоняют исходники, этого видеть не могли. Теперь exe проверяет себя сам до
релиза — но только по списку. Этот тест следит, чтобы новый импорт не забыли в него дописать."""
import os
import re

from pintel_core import selfcheck

КОРЕНЬ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pintel_core")


def _импорты_ядра():
    """Модули pymobiledevice3, которые импортирует ядро (кроме диагноста — он не касса)."""
    найдено = set()
    for dp, _, fn in os.walk(КОРЕНЬ):
        for f in fn:
            if not f.endswith(".py") or f in ("selfcheck.py", "doctor.py"):
                continue
            текст = open(os.path.join(dp, f), encoding="utf-8").read()
            найдено |= set(re.findall(r"^\s*from (pymobiledevice3\.[\w.]+) import", текст, re.M))
            найдено |= {"pymobiledevice3." + m for m in
                        re.findall(r"^\s*from pymobiledevice3 import (\w+)\s*$", текст, re.M)}
    return найдено


def test_selfcheck_covers_every_cable_import():
    в_списке = {модуль for модуль, _ in selfcheck.МОДУЛИ}
    забыто = _импорты_ядра() - в_списке
    assert not забыто, f"допишите в selfcheck.МОДУЛИ: {sorted(забыто)}"
    assert "pymobiledevice3.services.crash_reports" in в_списке      # с него всё и началось


def test_selfcheck_passes_on_sources_and_reports_a_broken_module(tmp_path, monkeypatch):
    assert selfcheck.проверить() == []
    итог = tmp_path / "selftest.txt"
    assert selfcheck.main(str(итог)) == 0 and "не загрузилось: 0" in итог.read_text(encoding="utf-8")

    monkeypatch.setattr(selfcheck, "МОДУЛИ", selfcheck.МОДУЛИ + (("pintel_нет_такого_модуля", None),
                                                                 ("pintel_core.colours", "нет_такого_имени")))
    assert selfcheck.main(str(итог)) == 1
    текст = итог.read_text(encoding="utf-8")
    assert "НЕ ЗАГРУЗИЛСЯ pintel_нет_такого_модуля" in текст and "нет нет_такого_имени" in текст


def test_entry_point_runs_the_selfcheck_before_qt():
    """Самопроверка идёт до импорта окна: на сборочной машине у exe нет экрана, и проверять
    надо модули связи, а не Qt."""
    текст = open(os.path.join(КОРЕНЬ, "..", "kiosk_main.py"), encoding="utf-8").read()
    assert текст.index('"--selftest"') < текст.index("from pintel_kiosk.app import main")
