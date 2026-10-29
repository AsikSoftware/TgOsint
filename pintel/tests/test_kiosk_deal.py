# -*- coding: utf-8 -*-
"""Сделка в одном окне: начать → проверка идёт, поля заполняются → отправка → чек.

За окном работает сотрудник, поэтому всё в одном месте: пока читается телефон, он уже
записывает имя клиента. Ворота те же: оформляем только телефоны, у которых Apple не нашла
ни ремонта, ни замены; остальные не оформляем, но слепок с них сохраняется.

Сделку создаёт бот Оценки — в её базу с точки хода нет. Здесь проверяется своя половина:
экран и то, что уходит боту.
"""
import json
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
    w = kapp.KioskWindow({**kconfig.DEFAULTS, "point": "16/38", "_path": None,
                          "staff_name": "Асылбек"})
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
    return report_mod.build(snap)


def _чистый(окно):
    """Довести окно до состояния «телефон прочитан, аппарат чистый»."""
    окно.cfg.setdefault("ocenka_bot", "")
    окно.cfg["ocenka_bot"] = окно.cfg["ocenka_bot"] or "PintelOlxBot"
    окно.начать_сделку()
    окно.state = "scanning"
    окно.on_done({"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip"), "client_id": "x"})


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


def test_everything_happens_in_one_window(окно):
    """«Начать оценку» открывает рабочее окно, и больше экранов в сделке нет: проверка,
    поля клиента и медиа — на одном месте."""
    assert окно.state == "idle" and окно.stack.currentWidget() is окно.s_main
    окно.начать_сделку()
    assert окно.state == "work" and окно.stack.currentWidget() is окно.s_work
    assert окно.stack.count() == 2, "экранов должно быть ровно два: ожидание и работа"


def test_client_can_be_typed_while_the_phone_is_read(окно):
    """Главная экономия времени: имя пишут, пока идёт проверка. Но отправить до результата
    нельзя — сделку не из чего собрать."""
    окно.начать_сделку()
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("8 705 883 79 53")
    assert not окно.s_work.b_отправить.isEnabled()          # результата ещё нет
    окно.state = "scanning"
    окно.on_done({"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip"), "client_id": "x"})
    assert окно.s_work.b_отправить.isEnabled()
    assert окно.s_work.данные()["телефон"] == "+77058837953"


def test_clean_phone_fills_the_window(окно):
    """Чистый аппарат: шапка с моделью, цена подставлена, SIM её словарём, код для медиа."""
    _чистый(окно)
    assert окно.state == "work"
    assert "iPhone 14 Pro" in окно.s_work.аппарат.text()
    assert окно.s_work.данные()["sim"] in ("Стандарт", "Dual sim", "E-sim", "Прочее")
    assert окно.код_медиа and окно.s_work.код.text() == окно.код_медиа


def test_repaired_phone_is_not_processed_but_kept(окно):
    """Аппарат с заменой: отправку не даём и прямо говорим почему, слепок сохранён."""
    окно.начать_сделку()
    окно.state = "scanning"
    окно.on_done({"report": _отчёт("эталон_iPhone-15-Pro_iOS26.6.1.zip"), "client_id": "x"})
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    assert not окно.s_work.b_отправить.isEnabled()
    текст = окно.s_work.ошибка.text()
    # отказ обязан назвать КАНАЛ и саму деталь: оценщик сверяет это с экраном телефона,
    # и «по данным Apple» про наш же сигнал по кабелю сбивало его с толку
    assert "не оформляется" in текст and "лепок сохранён" in текст
    assert ("по данным Apple" in текст or "по кабелю" in текст) and "Экран" in текст


def test_send_needs_the_client(окно):
    """Без имени и телефона сделку не создать — кнопка должна быть недоступна, а не
    выдавать ошибку после нажатия. Цену не спрашиваем вовсе: её считает бот."""
    _чистый(окно)
    assert not окно.s_work.b_отправить.isEnabled()
    окно.s_work.имя.setText("Зама")
    assert not окно.s_work.b_отправить.isEnabled()
    окно.s_work.телефон.setText("12345")                    # не телефон
    assert not окно.s_work.b_отправить.isEnabled()
    окно.s_work.телефон.setText("8 705 883 79 53")
    assert окно.s_work.b_отправить.isEnabled()
    assert not hasattr(окно.s_work, "цена"), "поля цены в окне быть не должно"


def test_media_code_is_made_on_the_point(окно):
    """Код придумываем на месте: в базу Оценки с точки хода нет, строку по нему заведёт
    сам бот, когда сотрудник откроет ссылку."""
    окно.cfg["ocenka_bot"] = "PintelOlxBot"
    окно.новый_код_медиа()
    assert окно.код_медиа and окно.s_work.код.text() == окно.код_медиа
    assert f"?start=p{окно.код_медиа}" in окно.s_work.ссылка.text()


def test_media_without_config_says_so(окно):
    """Не задан бот — сотрудник читает причину, а не смотрит на пустой QR."""
    окно.новый_код_медиа()
    assert "ocenka_bot" in окно.s_work.медиа.text() and окно.код_медиа == ""


def test_export_without_bot_settings_says_so_instead_of_silence(окно):
    """Не заданы токен и чат — сотрудник должен это прочитать, а не нажимать впустую."""
    окно.last = {"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip")}
    окно.отправить_в_оценку({"имя": "Зама", "телефон": "+77058837953",
                             "sim": "Стандарт", "коробка": True, "шнур": True, "комментарий": ""})
    assert "ocenka_bot_token" in окно.s_work.ошибка.text()


def test_export_sends_the_payload_to_the_bot(окно, monkeypatch):
    """Что уходит боту: посылка с кодом, ценой и клиентом — и ничего про медиа."""
    import httpx
    окно.cfg.update({"ocenka_bot": "PintelOlxBot", "ocenka_bot_token": "123:ABC",
                     "ocenka_chat_id": "-1001"})
    _чистый(окно)
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    ушло = {}

    def фейк(url, data=None, files=None, timeout=None):
        ушло.update(url=url, data=data, files=files)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    monkeypatch.setattr(httpx, "post", фейк)
    окно.s_work._отправить()
    окно.tasks[-1].wait(5000)                      # отправка идёт в отдельном потоке
    assert ушло, "посылка не ушла: " + окно.s_work.ошибка.text()
    посылка = json.loads(ушло["files"]["document"][1].decode("utf-8"))
    assert посылка["код"] == окно.код_медиа
    assert посылка["сделка"]["model"] == "iPhone 14 Pro"
    # цены в посылке нет вовсе: её считает Оценка по своему прайсу
    assert "price_grade_auto" not in посылка["сделка"]
    assert посылка["клиент"]["телефон"] == "+77058837953"
    assert "Киоск 16/38" in посылка["сделка"]["comment_ocenka"]


def test_sent_deal_shows_the_code_and_opens_printing(окно):
    """Номер сделки присваивает Оценка при подтверждении, обратного канала нет — на экране
    и в чеке наш код. Печать до отправки недоступна: печатать нечего."""
    _чистый(окно)
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    assert not окно.s_work.b_печать.isEnabled()
    окно.сделка_ушла({"код": окно.код_медиа, "message_id": 42})
    assert окно.s_work.номер.text() == окно.код_медиа
    assert окно.s_work.b_печать.isEnabled() and not окно.s_work.b_отправить.isEnabled()
    assert окно.сделка["клиент"] == "Зама" and окно.сделка["сотрудник"] == "Асылбек"


def test_receipt_is_written_and_named_by_deal(окно, tmp_path, monkeypatch):
    """Чек складывается файлом — его печатает сотрудник из окна просмотра."""
    monkeypatch.setattr(kapp, "data_dir", lambda: str(tmp_path))
    os.makedirs(tmp_path / "out", exist_ok=True)
    окно.last = {"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip")}
    окно.сделка = {"номер": "7KQ4M", "клиент": "Зама",
                   "телефон": "+77058837953", "сотрудник": "Асылбек", "точка": "16/38",
                   "коробка": True, "шнур": False}
    monkeypatch.setattr(kapp.os, "startfile", lambda p: None, raising=False)
    окно.напечатать_чек()
    файл = tmp_path / "out" / "чек_7KQ4M.html"
    assert файл.is_file()
    текст = файл.read_text(encoding="utf-8")
    assert "iPhone 14 Pro" in текст and "Зама" in текст
    assert "₸" not in текст, "цены на чеке быть не должно — её называет Оценка"
