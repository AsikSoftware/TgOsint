# -*- coding: utf-8 -*-
"""Поток сделки в приложении: начать → клиент → проверка → оценка → чек.

Приложение работает без нашего сервера, поэтому путь сделки целиком здесь, и ворота
тоже здесь: оформляем только телефоны, у которых Apple не нашла ни ремонта, ни замены.
Остальные не оформляем, но слепок с них сохраняется — на них учится разбор.

Сделку создаёт бот Оценки: в её базу с точки хода нет. Приложение отдаёт ему посылку
через Telegram, поэтому здесь проверяется только своя половина — экраны и то, что уходит.
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


def test_evaluation_requires_a_price(окно):
    """Без цены сделку не о чем показывать клиенту. Видео приложение не проверяет: оно
    его не видит — медиа принимает бот, он и не создаст сделку без видео."""
    окно.s_eval.показать(_отчёт("эталон_iPhone-14-Pro_iOS26.5.zip"), 250000)
    отправлено = []
    окно.s_eval.отправить.connect(отправлено.append)
    окно.s_eval.цена.clear()
    окно.s_eval._отправить()
    assert not отправлено and "цена" in окно.s_eval.ошибка.text()
    окно.s_eval.цена.setText("250000")
    окно.s_eval._отправить()
    assert отправлено, окно.s_eval.ошибка.text()
    assert отправлено[0]["цена"] == 250000 and отправлено[0]["sim"] == "Dual sim"


def test_media_link_carries_a_ready_command(окно):
    """Ссылка открывает бота Оценки с готовой командой и кодом: сотруднику остаётся
    только прислать видео и фото."""
    from pintel_core.external import ocenka_media
    ссылка = ocenka_media.ссылка("pintel_ocenka_bot", "7KQ2M4")
    assert ссылка == "https://t.me/pintel_ocenka_bot?start=p7KQ2M4"
    assert ocenka_media.ссылка("@Бот", "A1") == "https://t.me/Бот?start=pA1"
    окно.s_eval.показать_код("7KQ2M4", ссылка)
    assert окно.s_eval.код.text() == "7KQ2M4" and ссылка in окно.s_eval.ссылка.text()


def test_media_without_config_says_so(окно):
    """Не задан бот — сотрудник читает причину, а не смотрит на пустой QR."""
    окно.новый_код_медиа()
    assert "ocenka_bot" in окно.s_eval.медиа.text() and окно.код_медиа == ""


def test_media_code_is_made_on_the_point(окно):
    """Код придумываем на месте: в базу Оценки с точки хода нет, строку по этому коду
    заведёт сам бот, когда сотрудник откроет ссылку."""
    окно.cfg["ocenka_bot"] = "PintelOlxBot"
    окно.новый_код_медиа()
    assert окно.код_медиа and окно.s_eval.код.text() == окно.код_медиа
    assert f"?start=p{окно.код_медиа}" in окно.s_eval.ссылка.text()


def test_export_without_bot_settings_says_so_instead_of_silence(окно):
    """Не заданы токен и чат — сотрудник должен это прочитать, а не нажимать впустую."""
    окно.last = {"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip")}
    окно.клиент = {"имя": "Зама", "телефон": "+77058837953"}
    окно.отправить_в_оценку({"цена": 1, "sim": "Стандарт", "коробка": True, "шнур": True,
                             "комментарий": ""})
    assert "ocenka_bot_token" in окно.s_eval.ошибка.text()


def test_export_sends_the_payload_to_the_bot(окно, monkeypatch):
    """Что уходит боту: посылка с кодом, ценой и клиентом — и ничего про медиа."""
    import httpx
    окно.cfg.update({"ocenka_bot": "PintelOlxBot", "ocenka_bot_token": "123:ABC",
                     "ocenka_chat_id": "-1001", "ocenka_shop_litera": "16/38"})
    окно.last = {"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip")}
    окно.клиент = {"имя": "Зама", "телефон": "+77058837953"}
    окно.новый_код_медиа()
    ушло = {}

    def фейк(url, data=None, files=None, timeout=None):
        ушло.update(url=url, data=data, files=files)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    monkeypatch.setattr(httpx, "post", фейк)
    окно.отправить_в_оценку({"цена": 250000, "sim": "Dual sim", "коробка": True, "шнур": False,
                             "комментарий": "скол"})
    окно.tasks[-1].wait(5000)                      # отправка идёт в отдельном потоке
    assert ушло, "посылка не ушла"
    посылка = json.loads(ушло["files"]["document"][1].decode("utf-8"))
    assert посылка["код"] == окно.код_медиа and посылка["литера"] == "16/38"
    assert посылка["сделка"]["model"] == "iPhone 14 Pro"
    assert посылка["сделка"]["price_grade_auto"] == 250000
    assert посылка["клиент"]["телефон"] == "+77058837953"
    assert "Киоск 16/38" in посылка["сделка"]["comment_ocenka"]


def test_receipt_is_written_and_named_by_deal(окно, tmp_path, monkeypatch):
    """Чек складывается файлом — его печатает сотрудник из окна просмотра. Номер в нём наш,
    кодовый: номер сделки Оценка присваивает при подтверждении, и обратного канала нет."""
    monkeypatch.setattr(kapp, "data_dir", lambda: str(tmp_path))
    os.makedirs(tmp_path / "out", exist_ok=True)
    окно.last = {"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip")}
    окно.сделка = {"номер": "7KQ4M", "цена": 250000, "валюта": "₸", "клиент": "Зама",
                   "телефон": "+77058837953", "сотрудник": "Асылбек", "точка": "16/38",
                   "коробка": True, "шнур": False}
    monkeypatch.setattr(kapp.os, "startfile", lambda p: None, raising=False)
    окно.напечатать_чек()
    файл = tmp_path / "out" / "чек_7KQ4M.html"
    assert файл.is_file()
    текст = файл.read_text(encoding="utf-8")
    assert "250 000 ₸" in текст and "iPhone 14 Pro" in текст and "Зама" in текст
