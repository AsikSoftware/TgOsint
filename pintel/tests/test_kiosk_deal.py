# -*- coding: utf-8 -*-
"""Поток сделки в приложении: начать → клиент → проверка → оценка → чек.

Приложение работает без нашего сервера, поэтому путь сделки целиком здесь, и ворота
тоже здесь: оформляем только телефоны, у которых Apple не нашла ни ремонта, ни замены.
Остальные не оформляем, но слепок с них сохраняется — на них учится разбор.
"""
import os
import tempfile

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())

from PySide6.QtWidgets import QApplication            # noqa: E402

from pintel_core import reference                      # noqa: E402
from pintel_core.analysis import report as report_mod  # noqa: E402
from pintel_core.devicelink import snapshot            # noqa: E402
from pintel_kiosk import app as kapp                   # noqa: E402
from pintel_kiosk import config as kconfig             # noqa: E402
from pintel_kiosk import ui_deal                       # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.fixture
def окно(monkeypatch):
    """Окно без фоновых потоков: USB и сеть в тесте не нужны."""
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(kapp.Poller, "run", lambda self: None)
    monkeypatch.setattr(kapp.NetThread, "run", lambda self: None)
    w = kapp.KioskWindow({**kconfig.DEFAULTS, "point": "16/38", "_path": None, "сотрудник": "Асылбек"})
    yield w
    # потоки гасим ДО закрытия окна: QThread, разрушенный на ходу, роняет весь прогон
    for поток in (w.poller, w.net):
        поток.stop()
        поток.wait(2000)
    w.close()
    w.deleteLater()


def _отчёт(архив):
    snap, _ = reference.load_bundle(os.path.join(HERE, "fixtures_real", "эталоны", архив),
                                    loads=snapshot.loads)
    rep = report_mod.build(snap)
    rep["цена"] = {"валюта": "₸", "цена": 250000, "основание": "тест", "нехватка": []}
    return rep


@pytest.mark.parametrize("вход,ждём", [
    ("8 705 883 79 53", "+77058837953"),
    ("+7 705 883 79 53", "+77058837953"),
    ("7058837953", "+77058837953"),
    ("87058837953", "+77058837953"),
    ("12345", ""),
    ("", ""),
])
def test_phone_is_normalised_before_the_deal(вход, ждём):
    """Телефон клиента уходит в Оценку как есть и по нему ищется клиент — формат должен
    быть один, как бы сотрудник его ни набрал."""
    assert ui_deal.нормальный_телефон(вход) == ждём


def test_flow_starts_with_a_button_and_asks_for_the_client(окно):
    """Первое окно — «Начать оценку», второе — имя и телефон. Без них проверка не идёт:
    сделку в Оценку всё равно не создать, а телефон клиента держать у кассы незачем."""
    assert окно.state == "idle" and окно.stack.currentWidget() is окно.s_main
    окно.начать_сделку()
    assert окно.stack.currentWidget() is окно.s_client
    assert not окно.s_client.b_дальше.isEnabled()           # пустая форма дальше не пускает
    окно.s_client.имя.setText("Зама")
    окно.s_client.телефон.setText("8 705 883 79 53")
    assert окно.s_client.b_дальше.isEnabled()
    окно.s_client._дальше()
    assert окно.клиент == {"имя": "Зама", "телефон": "+77058837953"}
    assert окно.stack.currentWidget() is окно.s_scan


def test_clean_phone_goes_to_the_evaluation_window(окно):
    """Чистый аппарат: сразу окно оценки, цена подставлена, сводка заполнена."""
    окно.клиент = {"имя": "Зама", "телефон": "+77058837953"}
    окно.state = "scanning"
    окно.on_done({"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip"), "client_id": "x"})
    assert окно.state == "eval" and окно.stack.currentWidget() is окно.s_eval
    assert окно.s_eval.данные()["цена"] == 250000
    assert "iPhone 14 Pro" in окно.s_eval.сводка.text()


def test_repaired_phone_is_not_processed_but_kept(окно):
    """Аппарат с заменой: сделку не оформляем и прямо говорим почему, слепок сохранён."""
    окно.клиент = {"имя": "Зама", "телефон": "+77058837953"}
    окно.state = "scanning"
    окно.on_done({"report": _отчёт("эталон_iPhone-15-Pro_iOS26.6.1.zip"), "client_id": "x"})
    assert окно.state == "result" and окно.stack.currentWidget() is окно.s_result
    assert "не оформляется" in окно.s_result.note.text()
    assert "деталь меняли" in окно.s_result.note.text() and "лепок сохранён" in окно.s_result.note.text()


def test_evaluation_requires_video_and_price(окно):
    """Без видео Оценка не откроет сделку, без цены её не о чем показывать клиенту —
    обе проверки должны сработать до отправки, а не после."""
    окно.s_eval.показать(_отчёт("эталон_iPhone-14-Pro_iOS26.5.zip"), 250000)
    отправлено = []
    окно.s_eval.отправить.connect(отправлено.append)
    окно.s_eval._отправить()
    assert not отправлено and "видео" in окно.s_eval.ошибка.text()
    окно.s_eval.видео = "C:/видео.mp4"
    окно.s_eval.цена.clear()
    окно.s_eval._отправить()
    assert not отправлено and "цена" in окно.s_eval.ошибка.text()
    окно.s_eval.цена.setText("250000")
    окно.s_eval._отправить()
    assert отправлено and отправлено[0]["видео_путь"] == "C:/видео.mp4"


def test_export_without_db_says_so_instead_of_silence(окно):
    """Не настроен адрес Оценки — сотрудник должен это прочитать, а не нажимать впустую."""
    окно.last = {"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip")}
    окно.клиент = {"имя": "Зама", "телефон": "+77058837953"}
    окно.отправить_в_оценку({"видео_путь": "v.mp4", "фото_пути": [], "цена": 1, "sim": "Стандарт",
                             "коробка": True, "шнур": True, "комментарий": ""})
    assert "ocenka_db_url" in окно.s_eval.ошибка.text()


def test_receipt_is_written_and_named_by_deal(окно, tmp_path, monkeypatch):
    """Чек складывается файлом — его печатает сотрудник из окна просмотра."""
    monkeypatch.setattr(kapp, "data_dir", lambda: str(tmp_path))
    os.makedirs(tmp_path / "out", exist_ok=True)
    окно.last = {"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip")}
    окно.сделка = {"номер": 7093, "цена": 250000, "валюта": "₸", "клиент": "Зама",
                   "телефон": "+77058837953", "сотрудник": "Асылбек", "точка": "16/38",
                   "коробка": True, "шнур": False}
    monkeypatch.setattr(kapp.os, "startfile", lambda p: None, raising=False)
    окно.напечатать_чек()
    файл = tmp_path / "out" / "чек_7093.html"
    assert файл.is_file()
    текст = файл.read_text(encoding="utf-8")
    assert "250 000 ₸" in текст and "iPhone 14 Pro" in текст and "Зама" in текст
