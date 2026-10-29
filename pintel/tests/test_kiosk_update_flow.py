# -*- coding: utf-8 -*-
"""Обязательное обновление при запуске — и его единственное исключение.

Работать на точке на старой сборке нельзя: исправленная ошибка иначе неделями живёт на
части точек, потому что следить за версиями оценщику некогда. Но и запирать точку, когда
обновиться не вышло, нельзя: пропал интернет или прилёг GitHub — встанет выкуп везде
сразу, а это дороже старой сборки.
"""
import os
import tempfile

import pytest

pytest.importorskip("PySide6")                        # лёгкий job CI ставит Qt не везде
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())

from PySide6.QtWidgets import QApplication            # noqa: E402

from pintel_kiosk import app as kapp                  # noqa: E402
from pintel_kiosk import config as kconfig            # noqa: E402


@pytest.fixture
def окно(monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(kapp.Poller, "run", lambda self: None)
    monkeypatch.setattr(kapp.NetThread, "run", lambda self: None)
    w = kapp.KioskWindow({**kconfig.DEFAULTS, "point": "16/38", "_path": None})
    yield w
    for поток in (w.poller, w.net):
        поток.stop()
        поток.wait(2000)
    w.close()
    w.deleteLater()


def test_found_update_installs_itself(окно, monkeypatch):
    """Нашлась новая сборка — ставим сразу, не спрашивая и не ожидая нажатия."""
    ставили = []
    monkeypatch.setattr(окно, "обновиться", lambda: ставили.append(True))
    окно._обновление_найдено({"есть": True, "тег": "doctor-50", "url": "u"})
    assert ставили == [True] and окно.обновление_ставится is True


def test_no_deal_is_started_while_updating(окно, monkeypatch):
    """Пока идёт подмена, сделку начинать нельзя: через секунду программа закроется, и
    начатая оценка пропадёт вместе с ней."""
    monkeypatch.setattr(окно, "обновиться", lambda: None)
    окно._обновление_найдено({"есть": True, "тег": "doctor-50", "url": "u"})
    окно.начать_сделку()
    assert окно.state == "idle" and окно.stack.currentWidget() is not окно.s_work


def test_a_failed_update_does_not_lock_the_point(окно, monkeypatch):
    """GitHub недоступен — точка продолжает работать на текущей версии.

    Это важнее свежести: встанет выкуп на всех точках разом."""
    monkeypatch.setattr(окно, "обновиться", lambda: None)
    окно._обновление_найдено({"есть": True, "тег": "doctor-50", "url": "u"})
    окно._обновление_сорвалось("нет связи: ConnectError")

    assert окно.обновление_ставится is False
    окно.начать_сделку()
    assert окно.state == "work" and окно.stack.currentWidget() is окно.s_work


def test_nothing_new_means_nothing_happens(окно, monkeypatch):
    """Обновления нет — экран ожидания не трогаем и сделку не блокируем."""
    monkeypatch.setattr(окно, "обновиться", lambda: pytest.fail("ставить нечего"))
    окно._обновление_найдено({"есть": False, "почему": "уже последняя"})
    assert окно.обновление_ставится is False
    окно.начать_сделку()
    assert окно.state == "work"
