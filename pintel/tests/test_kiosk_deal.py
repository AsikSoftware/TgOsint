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
    w = kapp.KioskWindow({**kconfig.УМОЛЧАНИЯ, "server": kconfig.СЕРВЕР, "token": "pk_тест",
                          "point": "16/38", "staff_name": "Асылбек"})
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


АНКЕТА = {"состояние": "норма", "имя": "", "телефон": "", "imei": []}


def _тест_прошёл(окно, **ответы):
    """Тест на телефоне клиента вернулся с результатом. Без него сделку не отправить —
    отдельный шлюз, он проверяется своими тестами ниже."""
    from pintel_core import phonetest
    данные = {k: phonetest.ОК for k in phonetest.КЛЮЧИ}
    данные.update(ответы)
    окно._тест_с_телефона(данные)


def _медиа_собраны(окно):
    """Фото и видео дошли до бота. Касса узнаёт об этом от сервера (он читает базу Оценки) —
    без них кнопка «Отправить в Оценку» не нажимается, и это отдельный шлюз со своим
    тестом."""
    окно.s_work.set_медиа({"известно": True, "начали": True, "фото": 3, "видео": True,
                           "готово": True})


def _через_бота(окно, monkeypatch):
    """Сервер посылку не принял — касса уходит запасным путём, карточкой в Telegram.

    Главный путь теперь другой: посылка идёт на наш сервер, он кладёт её в таблицу обмена,
    и сделку создаёт сам бот. Но запасной обязан работать — им живут точки, у которых
    сервера под рукой нет, — и тесты карточки смотрят именно на него.
    """
    monkeypatch.setattr(окно.client, "отправить_посылку",
                        lambda код, посылка: {"принято": False, "почему": "в тесте сервера нет"})


def _через_сервер(окно, monkeypatch):
    """Главный путь: ловим посылку, которую касса отдаёт серверу. → куда она попала."""
    поймано = {}

    def принять(код, посылка):
        поймано.update(код=код, посылка=посылка)
        return {"принято": True}

    monkeypatch.setattr(окно.client, "отправить_посылку", принять)
    return поймано


def _руками_отмечено(окно, **ответы):
    """Проверки руками отмечены на экране кассы — ещё один шлюз со своим тестом ниже."""
    from pintel_core.external import ocenka_media
    окно.s_work.ручная = {k: ответы.get(k, True) for k in ocenka_media.КЛЮЧИ}
    окно.s_work._нарисовать_ручную()
    окно.s_work._проверить()


def _чистый_без_теста(окно):
    """То же, но без теста на телефоне: он — отдельный шлюз, и его проверяют свои тесты."""
    окно.cfg.setdefault("ocenka_bot", "")
    окно.cfg["ocenka_bot"] = окно.cfg["ocenka_bot"] or "PintelOlxBot"
    окно.начать_сделку()
    окно.анкета_готова(АНКЕТА)
    окно.state = "scanning"
    окно.on_done({"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip"), "client_id": "x"})
    _руками_отмечено(окно)
    _медиа_собраны(окно)


def _чистый(окно):
    """Довести окно до состояния «телефон прочитан, аппарат чистый»: анкета заполнена
    («б/у в нормальном состоянии»), проверка прошла."""
    окно.cfg.setdefault("ocenka_bot", "")
    окно.cfg["ocenka_bot"] = окно.cfg["ocenka_bot"] or "PintelOlxBot"
    окно.начать_сделку()
    окно.анкета_готова(АНКЕТА)
    окно.state = "scanning"
    окно.on_done({"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip"), "client_id": "x"})
    _тест_прошёл(окно)
    _руками_отмечено(окно)
    _медиа_собраны(окно)


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


def test_deal_starts_with_the_intake_then_one_window(окно):
    """«Начать оценку» открывает анкету — состояние и клиент до кабеля, как у продавца в
    боте. Дальше одно рабочее окно: проверка, поля клиента и медиа на одном месте."""
    assert окно.state == "idle" and окно.stack.currentWidget() is окно.s_main
    окно.начать_сделку()
    assert окно.state == "intake" and окно.stack.currentWidget() is окно.s_start
    окно.анкета_готова({**АНКЕТА, "имя": "Зама", "телефон": "+77058837953"})
    assert окно.state == "work" and окно.stack.currentWidget() is окно.s_work
    assert окно.stack.count() == 5, "ожидание, анкета, работа плюс токен и меню администратора"


def test_client_is_taken_before_the_phone_is_read(окно):
    """Имя и телефон записаны до кабеля и уже стоят в окне сделки. Отправить до результата
    всё равно нельзя — сделку не из чего собрать."""
    окно.начать_сделку()
    окно.анкета_готова({**АНКЕТА, "имя": "Зама", "телефон": "+77058837953"})
    assert окно.s_work.имя.text() == "Зама" and окно.s_work.данные()["телефон"] == "+77058837953"
    assert not окно.s_work.b_отправить.isEnabled()          # результата ещё нет
    assert "в нормальном состоянии" in окно.s_work.состояние.text()
    окно.state = "scanning"
    окно.on_done({"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip"), "client_id": "x"})
    assert not окно.s_work.b_отправить.isEnabled()          # теста на телефоне ещё не было
    _тест_прошёл(окно)
    assert not окно.s_work.b_отправить.isEnabled()          # и фото с видео ещё не дошли
    _медиа_собраны(окно)
    assert not окно.s_work.b_отправить.isEnabled()          # проверок руками ещё нет
    _руками_отмечено(окно)
    assert окно.s_work.b_отправить.isEnabled()
    assert окно.статус_сделки == "Не был в ремонте" and окно.переклассификация is None


def test_clean_phone_fills_the_window(окно):
    """Чистый аппарат: шапка с моделью, цена подставлена, SIM её словарём, код для медиа."""
    _чистый(окно)
    assert окно.state == "work"
    assert "iPhone 14 Pro" in окно.s_work.аппарат.text()
    assert окно.s_work.данные()["sim"] == "Стандарт" and окно.s_work.лоток.isChecked()
    # лоток — галочка рядом с коробкой и шнуром; сняли — в Оценку уйдёт «E-sim»
    окно.s_work.лоток.setChecked(False)
    assert окно.s_work.данные()["sim"] == "E-sim"
    окно.s_work.лоток.setChecked(True)
    assert окно.код_медиа and окно.s_work.код.text() == окно.код_медиа


def test_a_long_warning_wraps_instead_of_being_cut(окно):
    """Длинную строку «Внимание» край карточки обрезал на полуслове (снимок с точки
    12.11.2026: «Apple: аккумулятор требует обслуживания (износ, деталь р»)."""
    from PySide6.QtWidgets import QLabel

    rep = _отчёт("эталон_iPhone-12_iOS18.7.8.zip")
    длинная = "Apple: аккумулятор требует обслуживания (износ, деталь при этом оригинальная)"
    rep["внимание"] = ["износ батареи: здоровье 79%", длинная]
    окно.cfg["ocenka_bot"] = "PintelOlxBot"
    окно.начать_сделку()
    окно.анкета_готова(АНКЕТА)
    окно.state = "scanning"
    окно.on_done({"report": rep, "client_id": "x"})
    сетка = окно.s_work.итоги
    подписи = {w.text(): w for w in (сетка.itemAt(i).widget() for i in range(сетка.count()))
               if isinstance(w, QLabel)}
    assert подписи[длинная].wordWrap(), "длинная строка переносится"
    assert not подписи["износ батареи: здоровье 79%"].wordWrap(), "короткие стоят как стояли"


def test_repaired_phone_is_reclassified_not_refused(окно):
    """«Б/у в нормальном состоянии», а кабель нашёл замену: сделка не отказ, а «Телефон был
    в ремонте» — уйдёт админу на ручную оценку вместо автоцены. На плашке — на что и почему,
    с КАНАЛОМ и деталью: оценщик сверяет это с экраном телефона."""
    окно.cfg["ocenka_bot"] = "PintelOlxBot"
    окно.начать_сделку()
    окно.анкета_готова({**АНКЕТА, "имя": "Зама", "телефон": "+77058837953"})
    окно.state = "scanning"
    окно.on_done({"report": _отчёт("эталон_iPhone-15-Pro_iOS26.6.1.zip"), "client_id": "x"})
    _тест_прошёл(окно)
    _руками_отмечено(окно)
    _медиа_собраны(окно)
    assert окно.s_work.b_отправить.isEnabled() and окно.код_медиа
    assert окно.статус_сделки == "Ранее был в ремонте"
    # на экране — новое состояние и ничего больше; причина уходит оценщику, а не в плашку
    текст = окно.s_work.состояние.text()
    assert "был в ремонте" in текст and "изменено" not in текст and "Экран" not in текст
    причина = окно.переклассификация
    assert ("по данным Apple" in причина or "по кабелю" in причина) and "Экран" in причина


def test_repair_chosen_by_hand_is_not_argued_with(окно):
    """Сотрудник выбрал «был в ремонте» — чистый по кабелю аппарат это не отменяет."""
    окно.начать_сделку()
    окно.анкета_готова({**АНКЕТА, "состояние": "ремонт", "имя": "Зама", "телефон": "+77058837953"})
    окно.state = "scanning"
    окно.on_done({"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip"), "client_id": "x"})
    assert окно.статус_сделки == "Ранее был в ремонте" and окно.переклассификация is None
    assert "изменено" not in окно.s_work.состояние.text()


def test_phone_plugged_during_the_intake_waits(окно):
    """Телефон подключили раньше анкеты — читать его рано: сначала состояние и клиент."""
    from pintel_core.devicelink.connect import READY
    окно.начать_сделку()
    запуски = []
    окно.start_check = lambda: запуски.append(1)
    окно.on_tick(READY, "", 1)
    assert not запуски and окно.state == "intake"
    окно.анкета_готова({**АНКЕТА, "имя": "Зама", "телефон": "+77058837953"})
    assert запуски == [1]                                       # анкета заполнена — читаем


def test_sealed_phone_goes_by_imei_without_the_cable(окно, monkeypatch):
    """Запечатанный: IMEI с коробки → база IMEI (служба для запечатанных) → реестр РФС →
    сделка. Кабель не трогаем, коробка и шнур на месте, состояние — «Прочее»."""
    from PySide6.QtWidgets import QApplication
    from pintel_core.devicelink.connect import READY
    from pintel_kiosk import worker
    окно.cfg.update({"ocenka_bot": "PintelOlxBot"})
    службы = []

    def sickw(imei, services=None):
        службы.append(list(services or []))
        return {"модель": "iPhone 15 Pro", "объём_гб": 256, "цвет": "натуральный титан",
                "активация": "Not Activated", "активирован": False, "в_чёрном_списке": False,
                "все_поля": {}}

    окно.client.sickw = sickw
    monkeypatch.setattr(worker.rfs, "проверить", lambda imeis, cache_dir=None, proxy=None, **kw: [
        {"imei": i, "verdict": "verified", "status_text": "Верифицирован", "deadline": None, "text": "ок", "ok": True}
        for i in imeis])
    окно.начать_сделку()
    окно.анкета_готова({"состояние": "новый", "имя": "Зама", "телефон": "+77058837953",
                        "imei": ["350585886690250", "350585881725184"]})
    assert окно.sealed is not None and окно.sealed.wait(5000)
    for _ in range(20):                                         # сигналы из потока — через очередь
        QApplication.processEvents()
        if окно.last:
            break
    assert окно.last and окно.last.get("запечатанный")
    assert службы == [[147]]                                     # не 61: другая служба
    assert "Запечатанный" in окно.s_work.аппарат.text() and "iPhone 15 Pro" in окно.s_work.аппарат.text()
    # окно в тесте не показано, поэтому isVisible() ложен у всех — смотрим, кого спрятали явно
    assert окно.s_work.шаги["connect"].isHidden() and not окно.s_work.шаги["rfs"].isHidden()
    assert окно.статус_сделки == "Прочее" and окно.код_медиа
    d = окно.s_work.данные()
    assert d["коробка"] and d["шнур"] and d["sim"] == "Стандарт"
    assert "SIM-лоток" in окно.s_work.sim_подпись.text() and not окно.s_work.sim_подпись.isHidden(), \
        "у запечатанного лоток по кабелю не узнать — экран просит отметить"
    запуски = []
    окно.start_check = lambda: запуски.append(1)
    окно.on_tick(READY, "", 1)
    assert not запуски, "запечатанный кабелем не читается"


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
    assert f"?start=p{окно.код_медиа}" in окно.s_work.адрес_бота       # он в QR, на экране его нет


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

    _через_бота(окно, monkeypatch)
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
    # состояние — её кнопка, выбранная до диагностики; чистый аппарат её не меняет → автоцена
    assert посылка["состояние"] == "📱 Б/у телефон в нормальном состоянии"
    assert посылка["сделка"]["phone_status"] == "Не был в ремонте" and "переклассификация" not in посылка
    assert посылка["сделка"]["comment_ocenka"].startswith("Состояние: 📱")


def test_sealed_export_sends_her_new_phone_fields(окно, monkeypatch):
    """Запечатанный уходит в Оценку как её «Запечатанный (новый)»: Прочее, батарея новая,
    модель и объём из базы IMEI."""
    import httpx
    from pintel_core.analysis import sealed
    окно.cfg.update({"ocenka_bot": "PintelOlxBot", "ocenka_bot_token": "123:ABC",
                     "ocenka_chat_id": "-1001"})
    окно.начать_сделку()
    окно.анкета = {"состояние": "новый", "имя": "Зама", "телефон": "+77058837953",
                   "imei": ["350585886690250"]}
    окно.state = "work"
    окно.s_work.режим(True, ["350585886690250"])
    rep = sealed.build({"модель": "iPhone 15 Pro", "объём_гб": 256, "цвет": "натуральный титан",
                        "в_чёрном_списке": False, "активация": "Not Activated"}, ["350585886690250"],
                       [{"imei": "350585886690250", "verdict": "verified", "ok": True}])
    окно.on_sealed_done({"report": rep, "client_id": "box-1", "запечатанный": True,
                         "server": {"номер": 1, "локально": True}})
    _медиа_собраны(окно)
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    ушло = {}

    def фейк(url, data=None, files=None, timeout=None):
        ушло.update(url=url, data=data, files=files)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    _через_бота(окно, monkeypatch)
    monkeypatch.setattr(httpx, "post", фейк)
    окно.s_work._отправить()
    окно.tasks[-1].wait(5000)
    assert ушло, "посылка не ушла: " + окно.s_work.ошибка.text()
    посылка = json.loads(ушло["files"]["document"][1].decode("utf-8"))
    сд = посылка["сделка"]
    assert сд["model"] == "iPhone 15 Pro" and сд["ddr"] == 256 and сд["color"] == "NATURAL"
    assert сд["phone_status"] == "Прочее" and сд["akb"] == "100 (0-30)" and сд["box"] and сд["cord"]
    assert посылка["состояние"] == "📦 Запечатанный (новый)"
    assert "коробку не вскрывали" in посылка["тест_пропущен"], \
        "теста на телефоне у запечатанного быть не может, но пропуск обязан быть записан"
    assert посылка["рфс"][0]["статус"] == "верифицирован"
    assert "Запечатанный" in ушло["data"]["caption"] and "РФС 350585886690250: верифицирован" in ушло["data"]["caption"]


def test_sent_deal_shows_the_code_and_opens_printing(окно):
    """Номер сделки присваивает Оценка при подтверждении, обратного канала нет — на экране
    и в чеке наш код."""
    _чистый(окно)
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
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


# ---------------------------------------------------------------- тест на телефоне клиента

def test_the_deal_waits_for_the_phone_test(окно):
    """Кабель не нажмёт на экран, не послушает динамик и не посмотрит в камеру. Поэтому
    сделку нельзя отправить, пока телефон клиента не прогнал тест по QR с этого экрана, и
    сотрудник читает, чего именно не хватает, а не гадает, почему кнопка серая."""
    from pintel_core import phonetest
    окно.cfg["ocenka_bot"] = "PintelOlxBot"
    _чистый_без_теста(окно)
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    assert not окно.s_work.b_отправить.isEnabled()
    мешает = окно.s_work.почему_нельзя()
    assert "тест на телефоне" in мешает.lower() and "Сенсор" in мешает
    # пришла половина теста — всё ещё нельзя: «не проверили» это не «в порядке»
    окно._тест_с_телефона({"sensor": phonetest.ОК, "screen": phonetest.ПРОПУСК})
    assert not окно.s_work.b_отправить.isEnabled()
    assert "Динамик" in окно.s_work.почему_нельзя()
    _тест_прошёл(окно)
    assert окно.s_work.b_отправить.isEnabled() and окно.s_work.почему_нельзя() == ""


def test_a_failed_phone_test_is_seen_and_goes_into_the_deal(окно, monkeypatch):
    """Глухой динамик и чёрная камера видны только так. Результат виден сотруднику сразу и
    уходит в сделку: по нему бот снимает автоцену и пишет причину оценщику."""
    import httpx
    from pintel_core import phonetest
    окно.cfg.update({"ocenka_bot": "PintelOlxBot", "ocenka_bot_token": "123:ABC",
                     "ocenka_chat_id": "-1001"})
    _чистый_без_теста(окно)
    _тест_прошёл(окно, speaker=phonetest.ПЛОХО, camera_back=phonetest.ПЛОХО)
    assert "Динамик" in окно.s_work.ошибка.text() and "Камера сзади" in окно.s_work.ошибка.text()
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    ушло = {}
    _через_бота(окно, monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda url, data=None, files=None, timeout=None:
                        (ушло.update(files=files),
                         httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}))[1])
    окно.s_work._отправить()
    окно.tasks[-1].wait(5000)
    посылка = json.loads(ушло["files"]["document"][1].decode("utf-8"))
    assert посылка["тест_телефона"]["speaker"] == "fail"
    assert посылка["тест_телефона"]["sensor"] == "ok"
    # и в карточке, которую оценщик подтверждает в Telegram, это написано словами
    assert "НЕ ПРОШЛИ: Динамик" in посылка["сделка"]["comment_ocenka"]


def test_the_phone_test_can_be_skipped_but_it_is_written_down(окно, monkeypatch):
    """Телефона нет в нашем Wi-Fi — точка не должна встать. Пропуск возможен, но он записан
    вместе с тем, кто его сделал, и стоит автоцены: сделку смотрит человек."""
    import httpx
    окно.cfg.update({"ocenka_bot": "PintelOlxBot", "ocenka_bot_token": "123:ABC",
                     "ocenka_chat_id": "-1001"})
    _чистый_без_теста(окно)
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    assert not окно.s_work.b_отправить.isEnabled()          # теста не было
    окно.тест_не_будет()
    assert окно.s_work.b_отправить.isEnabled()              # пропуск отмечен — работать можно
    ушло = {}
    _через_бота(окно, monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda url, data=None, files=None, timeout=None:
                        (ушло.update(files=files),
                         httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}))[1])
    окно.s_work._отправить()
    окно.tasks[-1].wait(5000)
    посылка = json.loads(ушло["files"]["document"][1].decode("utf-8"))
    assert "тест_телефона" not in посылка
    assert "Асылбек" in посылка["тест_пропущен"]                 # кто отметил — из настроек точки
    assert "Тест на телефоне пропущен" in посылка["сделка"]["comment_ocenka"]


def test_every_deal_gets_its_own_one_time_link(окно):
    """Код теста свой на каждую сделку, и прошлая ссылка перестаёт работать: в сети точки
    стоят и другие телефоны, подбросить результат в чужую сделку они не должны."""
    окно.начать_сделку()
    первый = окно.код_теста
    assert первый
    окно.начать_сделку()
    assert окно.код_теста and окно.код_теста != первый
    окно.go_home()
    assert окно.код_теста == ""                                  # сделка закрыта — ссылки нет


def test_the_test_goes_through_our_domain_when_the_server_is_there(окно, monkeypatch):
    """С сервером ссылку на тест даёт домен: там HTTPS, и телефон пускает страницу к
    микрофону (по локальной сети Safari этого не разрешает). Результат ложится в базу, и
    касса забирает его опросом — сам он к ней не придёт."""
    from pintel_core import phonetest
    from pintel_kiosk.client import ServerError
    окно.client.enabled = True
    monkeypatch.setattr(окно.client, "открыть_тест",
                        lambda токен, ev_id=None: f"https://kiosk.pintelkz.com/t/{токен}")
    monkeypatch.setattr(окно.client, "результат_теста", lambda токен: {})
    окно.новый_код_теста()
    assert len(окно.код_теста) == 16
    for поток in окно.tasks:                              # домен спрашивается в отдельном потоке:
        поток.wait(5000)                                  # сделка начинается с нажатия, окно ждать не может
    for _ in range(50):
        QApplication.processEvents()
    assert окно.тест_через_сервер
    assert "kiosk.pintelkz.com" in окно.s_work.тест_ссылка.text()
    assert окно.тест_опрос.isActive()
    окно.state = "work"                                   # опрос идёт, только пока идёт сделка

    # телефон ещё не ответил — опрос ничего не меняет
    окно._спросить_тест()
    окно.tasks[-1].wait(5000)
    assert not окно.s_work._тест_закрыт()
    monkeypatch.setattr(окно.client, "результат_теста",
                        lambda токен: {k: phonetest.ОК for k in phonetest.КЛЮЧИ})
    окно._тест_спрашиваем = False
    окно._спросить_тест()
    окно.tasks[-1].wait(5000)
    for _ in range(50):                                   # сигнал приходит в поток окна
        QApplication.processEvents()
    assert окно.s_work._тест_закрыт() and not окно.тест_опрос.isActive()

    # сервер не ответил — остаётся мини-сервер в киоске, шаг не отменяется
    def падает(токен, ev_id=None):
        raise ServerError("нет связи с сервером")

    monkeypatch.setattr(окно.client, "открыть_тест", падает)
    окно.новый_код_теста()
    for поток in окно.tasks:
        поток.wait(5000)
    for _ in range(50):
        QApplication.processEvents()
    assert окно.тест_через_сервер is False and not окно.тест_опрос.isActive()


def test_the_receipt_carries_a_link_to_itself(окно, monkeypatch):
    """Чек на бумаге несёт QR на тот же чек на домене: бумага теряется, ссылка остаётся.
    И тот же чек дописывается в сохранённую оценку — иначе в общей базе аппарат остался бы
    без того, чем кончилась сделка."""
    import httpx
    from pintel_core import receipt
    окно.cfg.update({"ocenka_bot": "PintelOlxBot", "ocenka_bot_token": "123:ABC",
                     "ocenka_chat_id": "-1001"})
    _чистый(окно)
    окно.client.enabled = True
    окно.last["server"] = {"id": 77, "номер": 5, "ссылка_чека": "https://kiosk.pintelkz.com/check/abc"}
    дослано = {}
    monkeypatch.setattr(окно.client, "update_evaluation",
                        lambda ev_id, report, snapshot_patch=None: дослано.update(id=ev_id, report=report))
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    _через_бота(окно, monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda url, data=None, files=None, timeout=None:
                        httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}))
    окно.s_work._отправить()
    окно.tasks[-1].wait(5000)
    for _ in range(50):
        QApplication.processEvents()
    assert окно.сделка["ссылка"] == "https://kiosk.pintelkz.com/check/abc"
    бумага = receipt.html(окно.сделка, окно.last["report"])
    assert "<svg" in бумага and "check/abc" in бумага
    for поток in окно.tasks:
        поток.wait(5000)
    assert дослано.get("id") == 77 and дослано["report"]["чек"]["клиент"] == "Зама"


# ---------------------------------------------------------------- токен точки и меню администратора

@pytest.fixture
def окно_без_токена(monkeypatch, tmp_path):
    """Первый запуск на новой точке: токена нет, настроек с сервера тоже."""
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(kapp.Poller, "run", lambda self: None)
    monkeypatch.setattr(kapp.NetThread, "run", lambda self: None)
    monkeypatch.setattr(kapp.config, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(kconfig, "data_dir", lambda: str(tmp_path))
    w = kapp.KioskWindow({**kconfig.УМОЛЧАНИЯ, "server": kconfig.СЕРВЕР, "token": ""})
    yield w
    for поток in (w.poller, w.net):
        поток.stop()
        поток.wait(2000)
    w.close()
    w.deleteLater()


def test_the_first_launch_asks_for_the_point_token(окно_без_токена, monkeypatch):
    """На точке не настраивают ничего, кроме токена, и спрашивают его здесь, а не в файле.
    Токен проверяется сразу: сказать «не подошёл» надо у стойки, а не молчанием на первом
    же аппарате."""
    окно = окно_без_токена
    assert окно.stack.currentWidget() is окно.s_token
    окно.открыть_меню()
    assert окно.stack.currentWidget() is окно.s_token, "пока нет токена, меню не открываем"

    # на первом экране выбирают точку из списка: это магазины Оценки с теми же id
    окно.s_token.показать_точки([{"id": 14, "название": "16/38 Pintel", "литера": "U"},
                                 {"id": 19, "название": "Апорт", "литера": "Z"}])
    assert len(окно.s_token.кнопки) == 2
    окно.s_token._выбрать({"id": 19, "название": "Апорт"})

    ответ = {"точка": "Апорт", "точка_id": 19,
             "настройки": {"point": "Апорт", "staff_name": "Асылбек", "ocenka_bot": "PintelOlxBot"}}
    monkeypatch.setattr(окно.client, "config", lambda: ответ)
    окно.s_token.поле.setText("pk_новый_токен")
    окно.s_token._принять()
    for поток in окно.tasks:
        поток.wait(5000)
    for _ in range(50):
        QApplication.processEvents()

    assert окно.client.token == "pk_новый_токен" and окно.client.enabled
    assert kconfig.токен() == "pk_новый_токен", "токен переживёт перезапуск и обновление"
    assert kconfig.точка_id() == 19, "id точки = id магазина в Оценке, он поедет в сделку"
    assert окно.stack.currentWidget() is окно.s_main
    # надпись в углу — ровно то, что в базе, а не то, что кто-то вписал в файл
    assert "Апорт" in окно.s_main.point_label.text()
    assert окно.cfg["ocenka_bot"] == "PintelOlxBot"      # настройки пришли с сервера и сохранены
    assert kconfig.load()["point"] == "Апорт"


def test_a_wrong_token_says_so_instead_of_silence(окно_без_токена, monkeypatch):
    """Опечатались в токене — об этом говорят на экране сразу."""
    окно = окно_без_токена
    from pintel_kiosk.client import ServerError

    def падает():
        raise ServerError("сервер ответил 401: Нет токена точки")

    monkeypatch.setattr(окно.client, "config", падает)
    окно.s_token._выбрать({"id": 19, "название": "Апорт"})
    окно.новый_токен(19, "pk_чужой")
    for поток in окно.tasks:
        поток.wait(5000)
    for _ in range(50):
        QApplication.processEvents()
    assert окно.stack.currentWidget() is окно.s_token
    assert "Не подошёл" in окно.s_token.ошибка.text()


def test_the_admin_menu_is_hidden_behind_a_key_combination(окно, monkeypatch):
    """Меню администратора не видно с экрана: у стойки стоит клиент. Открывается
    сочетанием клавиш, и в нём же меняют токен, когда точку перевыпустили."""
    окно.открыть_меню()
    assert окно.stack.currentWidget() is окно.s_admin
    подписи = окно._сведения()
    assert подписи["Сервер"] == окно.client.base and подписи["Токен"].endswith("…")
    окно.закрыть_меню()
    assert окно.stack.currentWidget() is окно.s_main


def test_the_deal_carries_the_shop_id_of_ocenka(окно, monkeypatch):
    """Точка у нас — это магазин Оценки с тем же id, и программа кладёт его прямо в посылку.
    Поэтому в боте точку больше не спрашивают: он берёт готовый shop_id."""
    import httpx
    окно.cfg.update({"ocenka_bot": "PintelOlxBot", "ocenka_bot_token": "123:ABC",
                     "ocenka_chat_id": "-1001", "point_id": 14, "point": "16/38 Pintel"})
    _чистый(окно)
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    ушло = {}
    _через_бота(окно, monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda url, data=None, files=None, timeout=None:
                        (ушло.update(files=files),
                         httpx.Response(200, json={"ok": True, "result": {"message_id": 1}}))[1])
    окно.s_work._отправить()
    окно.tasks[-1].wait(5000)
    посылка = json.loads(ушло["files"]["document"][1].decode("utf-8"))
    assert посылка["shop_id"] == 14 and посылка["точка"] == "16/38 Pintel"


# ---------------------------------------------------------------- фото и видео в боте

def test_the_deal_waits_for_the_photos_and_the_video(окно):
    """Порядок сделки: проверка кабелем → тест на телефоне → проверки руками → фото и видео
    в боте → отправка. Пока медиа не собраны, «Отправить в Оценку» не нажимается.

    Раньше карточка уходила в рабочую группу и без них, а отказ прилетал от бота минутой
    позже — с телефоном клиента в руках это значит собирать сделку заново."""
    _чистый_без_теста(окно)
    окно.s_work.set_медиа({})                      # сбрасываем: медиа ещё не спрашивали
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    _тест_прошёл(окно)
    assert not окно.s_work.b_отправить.isEnabled()
    assert "Сканируйте QR" in окно.s_work.почему_нельзя()

    # сотрудник открыл ссылку и прислал два фото из трёх
    окно.s_work.set_медиа({"известно": True, "начали": True, "фото": 2, "видео": False,
                           "готово": False})
    assert not окно.s_work.b_отправить.isEnabled()
    мешает = окно.s_work.почему_нельзя()
    assert "фото: 2 из 3" in мешает and "видео" in мешает

    _медиа_собраны(окно)
    assert окно.s_work.b_отправить.isEnabled() and окно.s_work.почему_нельзя() == ""


def test_if_the_kiosk_cannot_see_the_bot_it_says_so_and_does_not_stop_the_point(окно):
    """Сервер не смог посмотреть в базу Оценки — это «не вижу», а не «медиа нет». Держать
    из-за своей же слепоты точку нельзя: бот всё равно не создаст сделку без видео. Но на
    экране это написано прямо, а не выглядит как «всё в порядке»."""
    _чистый_без_теста(окно)
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    _тест_прошёл(окно)
    окно.s_work.set_медиа({"известно": False, "почему": "касса не видит базу Оценки"})
    assert окно.s_work.b_отправить.isEnabled()
    подписи = " ".join(окно.s_work.медиа_список.itemAt(i).widget().text()
                       for i in range(окно.s_work.медиа_список.count()))
    assert "не видит" in подписи and "без них бот сделку не создаст" in подписи


def test_without_a_server_the_point_still_works(окно):
    """Касса без связи с сервером спросить про медиа некого. Это не повод остановить
    точку: сделку бот всё равно не создаст без видео, а сотрудник у стойки должен
    работать. На экране при этом написано, что мы не видим бота."""
    _чистый_без_теста(окно)
    окно.client.enabled = False
    окно.новый_код_медиа()                        # новый код завёлся уже без связи
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    _тест_прошёл(окно)
    assert окно.s_work.b_отправить.isEnabled()
    assert окно.s_work.медиа_состояние.get("известно") is False


# ---------------------------------------------------------------- проверки руками

def _подписи(список):
    return " ".join(список.itemAt(i).widget().text() for i in range(список.count())
                    if список.itemAt(i).widget() is not None)


def test_the_manual_checks_are_marked_on_the_screen_not_in_the_bot(окно):
    """Кнопки, вибрацию, SIM и следы воды отмечает сотрудник — на экране кассы.

    Раньше их спрашивал бот восемью кнопками в Telegram. Телефон клиента лежит на столе у
    кассы, а не рядом с чатом: переключать кнопки в переписке, держа аппарат в руке, — шаг
    на ровном месте, на котором ещё и ошибались. Теперь это карточка справа, и без всех
    отметок сделка не уходит."""
    from pintel_core.external import ocenka_media
    _чистый_без_теста(окно)
    окно.s_work.ручная = {}                        # сбрасываем: ничего ещё не отмечено
    окно.s_work._нарисовать_ручную()
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    _тест_прошёл(окно)
    # на экране ровно наши пункты — и каждый с подсказкой, чем его проверить
    assert set(окно.s_work.пункты_ряды) == set(ocenka_media.КЛЮЧИ)
    assert not окно.s_work.b_отправить.isEnabled()
    мешает = окно.s_work.почему_нельзя()
    assert "Отметьте проверки руками" in мешает and "Кнопки" in мешает
    # отмечаем по одному: нажатие по ряду — ⬜ → ✅
    for ключ in ocenka_media.КЛЮЧИ[:-1]:
        окно.s_work.пункты_ряды[ключ].нажали.emit(ключ)
    assert not окно.s_work.b_отправить.isEnabled(), "последний пункт ещё не отмечен"
    assert "осталось 1" in _подписи(окно.s_work.медиа_список).lower()
    окно.s_work.пункты_ряды[ocenka_media.КЛЮЧИ[-1]].нажали.emit(ocenka_media.КЛЮЧИ[-1])
    assert окно.s_work.b_отправить.isEnabled() and окно.s_work.почему_нельзя() == ""
    assert окно.s_work.данные()["ручная"] == {k: True for k in ocenka_media.КЛЮЧИ}
    # второе нажатие — «не работает», третье снимает отметку: пропустить шаг нечем
    окно.s_work.пункты_ряды["glue"].нажали.emit("glue")
    assert окно.s_work.данные()["ручная"]["glue"] is False
    assert "НЕ работает" in окно.s_work.ручная_итог.text() and "Герметик" in окно.s_work.ручная_итог.text()
    assert окно.s_work.b_отправить.isEnabled()     # поломка не отказ: её оценит человек
    окно.s_work.пункты_ряды["glue"].нажали.emit("glue")
    assert "glue" not in окно.s_work.данные()["ручная"]
    assert not окно.s_work.b_отправить.isEnabled()


def test_the_marks_go_to_the_bot_with_the_deal(окно, monkeypatch):
    """Отметки уезжают в посылке: бот кладёт их в карточку и по ним снимает автоцену."""
    import httpx
    from pintel_core.external import ocenka_media
    окно.cfg.update({"ocenka_bot": "PintelOlxBot", "ocenka_bot_token": "123:ABC",
                     "ocenka_chat_id": "-1001"})
    _чистый(окно)
    _руками_отмечено(окно, glue=False)            # следы воды в лотке — кабель их не видит
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    ушло = {}
    _через_бота(окно, monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda url, data=None, files=None, timeout=None: (
        ушло.update(files=files) or httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})))
    окно.s_work._отправить()
    окно.tasks[-1].wait(5000)
    assert ушло, "посылка не ушла: " + окно.s_work.ошибка.text()
    посылка = json.loads(ушло["files"]["document"][1].decode("utf-8"))
    отметки = посылка["ручная_диагностика"]
    assert отметки["glue"] is False and отметки["keys"] is True
    assert len(отметки) == len(ocenka_media.КЛЮЧИ)


def test_the_sealed_box_is_not_asked_to_be_checked_by_hand(окно):
    """Запечатанный аппарат не вскрывают — проверять руками нечего.

    Требовать отметки значило бы требовать соврать. Отметка «коробку не вскрывали» ставится
    сама и видна словами: автоцены у такой сделки нет в любом случае."""
    from pintel_core.external import ocenka_media
    окно.начать_сделку()
    окно.анкета_готова({**АНКЕТА, "состояние": "новый", "имя": "Зама",
                        "телефон": "+77058837953", "imei": ["350585886690250"]})
    assert окно.s_work.данные()["ручная"] == {ocenka_media.ЗАПЕЧАТАН: True}
    assert ocenka_media.готова(окно.s_work.ручная)
    assert "не вскрывали" in окно.s_work.ручная_итог.text()


def test_after_the_phone_test_the_screen_asks_for_the_manual_checks(окно):
    """Порядок на экране — как в жизни: тест на телефоне → проверки руками → фото и видео.

    Сотрудник не обязан догадываться, какую карточку переключить: закончился тест — показали
    проверки руками, отметил все — показали QR для медиа."""
    from pintel_core.external import ocenka_media
    _чистый_без_теста(окно)
    окно.s_work.ручная = {}
    окно.s_work._нарисовать_ручную()
    окно.s_work.правая.setCurrentIndex(ui_deal.СТР_ТЕСТ)
    _тест_прошёл(окно)
    assert окно.s_work.правая.currentIndex() == ui_deal.СТР_РУЧНАЯ
    for ключ in ocenka_media.КЛЮЧИ:
        окно.s_work.отметить(ключ)
    assert окно.s_work.правая.currentIndex() == ui_deal.СТР_МЕДИА


# ---------------------------------------------------------------- чек до отправки

def test_the_receipt_can_be_printed_before_the_deal_is_sent(окно, tmp_path, monkeypatch):
    """Чек печатается сразу после медиа — до отправки в Оценку.

    Клиент стоит у кассы и уходит с бумагой. Раньше кнопка оживала только после «Отправить
    в Оценку», и человека держали ради нашего порядка шагов. Номер в чеке и так наш — это
    код обмена с того же экрана, по которому бот создаст сделку."""
    monkeypatch.setattr(kapp, "data_dir", lambda: str(tmp_path))
    os.makedirs(tmp_path / "out", exist_ok=True)
    monkeypatch.setattr(kapp.os, "startfile", lambda p: None, raising=False)
    _чистый_без_теста(окно)
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    assert окно.s_work.b_печать.isEnabled(), "медиа дошли, а чек не напечатать"
    assert not окно.s_work.отправлено
    окно.напечатать_чек()
    файл = tmp_path / "out" / f"чек_{окно.код_медиа}.html"
    assert файл.is_file()
    текст = файл.read_text(encoding="utf-8")
    assert "Зама" in текст and окно.код_медиа in текст and "iPhone 14 Pro" in текст
    assert not окно.s_work.отправлено, "печать чека не должна отправлять сделку"
    assert "ещё не отправили" in окно.s_work.ошибка.text()
    # а до медиа печатать нечего: проверка ещё не кончилась
    окно.начать_сделку()
    assert not окно.s_work.b_печать.isEnabled()


# ---------------------------------------------------------------- прошлая проверка на экране

def test_a_reused_check_is_visible_with_a_way_out(окно):
    """Проверку взяли прошлую — это видно словами, и рядом есть кнопка «заново».

    Иначе экран выглядит как после обычного чтения по кабелю, и отчёт получасовой давности
    не отличить от сделанного минуту назад."""
    окно.cfg["ocenka_bot"] = "PintelOlxBot"
    окно.начать_сделку()
    окно.анкета_готова(АНКЕТА)
    assert not окно.s_work.b_перепроверить.isVisible()
    rep = _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip")
    rep["повторная_проверка"] = {"словами": "сегодня в 13:20, 40 мин назад", "возраст_мин": 40,
                                 "сверка": "сошлась"}
    окно.state = "scanning"
    окно.on_done({"report": rep, "client_id": "x", "повторная": True})
    плашки = " ".join(окно.s_work.плашки.itemAt(i).widget().text()
                      for i in range(окно.s_work.плашки.count())
                      if окно.s_work.плашки.itemAt(i).widget() is not None)
    assert "Проверка прошлая" in плашки and "40 мин назад" in плашки
    assert "не перечитывали" in окно.s_work.повтор_текст.text()
    assert окно.s_work.b_перепроверить.isVisibleTo(окно.s_work)
    # телефона на кабеле нет — говорим прямо, а не делаем вид, что читаем
    окно.кабель = "NO_DEVICE"
    окно.перепроверить_телефон()
    assert "на кабеле" in окно.s_work.ошибка.text()


def test_a_real_click_on_the_row_marks_it(окно):
    """Отметка ставится настоящим нажатием мыши — и именно так, как на точке.

    Так это и сломалось: ряд принимал только отпускание кнопки, а Qt отдаёт его лишь тому,
    кто принял нажатие. На точке окно живёт внутри QGraphicsView (экраны свёрстаны на
    1920×1080 и масштабируются целиком), и там непринятое нажатие теряется совсем — строки
    выглядели мёртвыми, хотя в обычном окне клик срабатывал. Поэтому кликаем через тот же
    QGraphicsView, а не по виджету напрямую: иначе тест этого не увидит.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    экран = окно.s_work
    _чистый_без_теста(окно)
    экран.ручная = {}
    экран._нарисовать_ручную()
    экран.правая.setCurrentIndex(ui_deal.СТР_РУЧНАЯ)
    хост = kapp.ScaledHost(экран)
    хост.resize(1920, 1080)
    хост.show()
    QApplication.processEvents()

    def кликнуть(виджет, точка=None):
        точка = точка if точка is not None else виджет.rect().center()
        на_экране = виджет.mapTo(экран, точка)
        QTest.mouseClick(хост.viewport(), Qt.LeftButton,
                         pos=хост.mapFromScene(на_экране.x(), на_экране.y()))
        QApplication.processEvents()

    ряд = экран.пункты_ряды["keys"]
    кликнуть(ряд)
    assert экран.данные()["ручная"].get("keys") is True, "клик по строке не отметил пункт"

    # попадают обычно по тексту, а не по рамке — подписи не должны съедать нажатие
    кликнуть(ряд.имя, QPoint(2, 2))
    assert экран.данные()["ручная"].get("keys") is False, "клик по названию не дошёл до строки"
    кликнуть(ряд.подробно, QPoint(2, 2))
    assert "keys" not in экран.данные()["ручная"], "третий клик должен снимать отметку"

    хост.close()
    экран.setParent(None)                  # вернуть экран окну: дальше его закрывает фикстура
    окно.stack.addWidget(экран)


def test_the_deal_goes_through_the_server_and_waits_for_its_number(окно, monkeypatch):
    """Главный путь: посылка уходит на наш сервер, а сделку создаёт бот — сам.

    Так было не всегда, и за это заплатили на точке. Раньше касса слала карточку файлом в
    чат Telegram, и бот получал посылку ТОЛЬКО когда кто-то нажимал под ней кнопку: свои
    исходящие сообщения бот не видит. Значит, сделка зависела от чата, а чат отказывал —
    «chat not found», «bot was blocked by the user», — и тогда создать её было нельзя
    вовсе: сотрудник стоял с телефоном клиента в руках и ничего не мог сделать.
    """
    import httpx
    окно.cfg.update({"ocenka_bot": "PintelOlxBot", "ocenka_bot_token": "123:ABC",
                     "ocenka_chat_id": "-1001"})
    _чистый(окно)
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    поймано = _через_сервер(окно, monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("в чат слать было незачем"))
    окно.s_work._отправить()
    окно.tasks[-1].wait(5000)
    QApplication.processEvents()                   # итог приходит сигналом в главный поток

    assert поймано.get("код") == окно.код_медиа, "посылка не ушла: " + окно.s_work.ошибка.text()
    assert поймано["посылка"]["сделка"]["model"] == "iPhone 14 Pro"
    assert поймано["посылка"]["клиент"]["телефон"] == "+77058837953"
    # номера сделки ещё нет: её создаёт бот, и касса честно говорит, что ждёт его
    assert окно.s_work.отправлено and "создаётся" in окно.s_work.итог_текст.text()

    # бот создал — номер приходит тем же опросом, которым касса следила за медиа
    окно._медиа_спросили({"известно": True, "начали": True, "фото": 3, "видео": True,
                          "готово": True, "сделка": 7311, "ошибка": ""})
    assert "7311" in окно.s_work.итог_текст.text()


def test_when_the_bot_cannot_create_the_deal_the_point_is_told(окно, monkeypatch):
    """Сделка не создалась — на экране причина и возможность отправить заново.

    Молчать здесь нельзя: написано «отправлено», сотрудник ждёт номера, а номера не
    будет — и узнает он об этом, когда клиент уже ушёл."""
    import httpx
    окно.cfg.update({"ocenka_bot": "PintelOlxBot", "ocenka_bot_token": "123:ABC",
                     "ocenka_chat_id": "-1001"})
    _чистый(окно)
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    _через_сервер(окно, monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("в чат слать было незачем"))
    окно.s_work._отправить()
    окно.tasks[-1].wait(5000)
    QApplication.processEvents()

    окно._медиа_спросили({"известно": True, "начали": True, "фото": 3, "видео": True,
                          "готово": True, "сделка": None, "ошибка": "Не хватает: видео"})
    assert "видео" in окно.s_work.итог_текст.text()
    assert окно.s_work.b_отправить.isEnabled(), "отправить заново должно быть можно"


def test_without_the_server_the_card_still_goes_to_the_bot(окно, monkeypatch):
    """Сервера нет — касса шлёт карточку с кнопкой, как раньше.

    Это запасной путь, и он обязан работать: точка не должна останавливаться из-за того,
    что наш сервер недоступен."""
    import httpx
    окно.cfg.update({"ocenka_bot": "PintelOlxBot", "ocenka_bot_token": "123:ABC",
                     "ocenka_chat_id": "-1001"})
    _чистый(окно)
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    ушло = {}
    monkeypatch.setattr(окно.client, "отправить_посылку",
                        lambda код, посылка: {"принято": False, "почему": "сервер не ответил"})
    monkeypatch.setattr(httpx, "post", lambda url, data=None, files=None, timeout=None: (
        ушло.update(url=url, data=data),
        httpx.Response(200, json={"ok": True, "result": {"message_id": 42}}))[1])
    окно.s_work._отправить()
    окно.tasks[-1].wait(5000)
    QApplication.processEvents()
    assert ушло and "sendDocument" in ушло["url"]
    assert "Telegram" in окно.s_work.итог_текст.text(), "сотрудник должен знать, что ждёт кнопки"


def test_when_neither_path_works_both_reasons_are_on_the_screen(окно, monkeypatch):
    """Не прошло ни там, ни там — сотрудник читает обе причины, а не одну из них.

    По одной причине непонятно, что чинить: сервер на точке или бота."""
    import httpx
    from pintel_core.external import ocenka_tg
    окно.cfg.update({"ocenka_bot": "PintelOlxBot", "ocenka_bot_token": "123:ABC",
                     "ocenka_chat_id": "-1001"})
    _чистый(окно)
    окно.s_work.имя.setText("Зама")
    окно.s_work.телефон.setText("+77058837953")
    monkeypatch.setattr(окно.client, "отправить_посылку",
                        lambda код, посылка: {"принято": False, "почему": "сервер не ответил"})
    monkeypatch.setattr(ocenka_tg, "отправить", lambda *a, **k: (_ for _ in ()).throw(
        ocenka_tg.ОшибкаОтправки("Telegram отказал: Forbidden: bot was blocked by the user")))
    окно.s_work._отправить()
    окно.tasks[-1].wait(5000)
    QApplication.processEvents()
    текст = окно.s_work.ошибка.text()
    assert "сервер не ответил" in текст and "blocked" in текст


def test_ugolok_istorii_otkryvaetsya_i_zakryvaetsya(окно):
    """Окошко истории в углу: нажали — список, нажали снова — угол пустой.

    И главное: «ничего не нашли» и «не спросилось» на плашке выглядят по-разному. Пустой
    угол сотрудник читает как «аппарат у нас впервые» и называет цену с нуля — а это может
    быть молчащая база."""
    э = окно.s_work
    э.set_история({"есть": False, "почему": [], "оценки": [], "заявки": [], "наши": []})
    assert "ничего" in э.история_плашка.текст.text()
    э.история_переключить()
    assert э.история_панель.isHidden(), "разворачивать нечего"

    э.set_история({"почему": ["база Оценки не ответила: OperationalError"],
                   "оценки": [], "заявки": [], "наши": []})
    assert "не спросилась" in э.история_плашка.текст.text()

    э.set_история({"почему": [], "заявки": [], "наши": [],
                   "оценки": [{"сделка": 12367, "когда": "13.10.2026", "точка": "16/38 Pintel",
                               "модель": "iPhone 13 Pro Max 256 ГБ", "акб": "78%",
                               "автоцена": 180000, "выкуп": 80000, "статус": "Выкуплен"}]})
    assert "1 запись" in э.история_плашка.текст.text()
    э.история_переключить()
    assert not э.история_панель.isHidden()
    текст = э.история_панель.текст.text()
    assert "12367" in текст and "16/38 Pintel" in текст and "выкуп 80 000 ₸" in текст
    э.история_переключить()
    assert э.история_панель.isHidden()


def test_otkaz_po_germetiku_vidno_na_plashke(окно):
    """Отметил «Герметик — НЕ работает» — плашка состояния тут же становится «Есть видимые
    дефекты». Узнавать об этом из карточки бота поздно: цену называют здесь."""
    from pintel_core.external import ocenka, ocenka_media

    _чистый_без_теста(окно)
    окно.s_work.ручная = {}
    окно.s_work._нарисовать_ручную()
    for ключ in ocenka_media.КЛЮЧИ:
        окно.s_work.пункты_ряды[ключ].нажали.emit(ключ)        # всё работает
    assert "дефект" not in окно.s_work.состояние.text().lower()
    окно.s_work.пункты_ряды["glue"].нажали.emit("glue")        # второе нажатие — «НЕ работает»
    assert окно.статус_сделки == ocenka.СТАТУС_ДЕФЕКТ
    надпись = окно.s_work.состояние.text()
    assert "дефект" in надпись.lower() and "Герметик" not in надпись    # причина — не на экран
    assert "Герметик" in окно.переклассификация


# ---------------------------------------------------------------- новый облик: Pintel Diagnostics

def test_ozhidanie_nachinaetsya_nazhatiem_v_lyuboe_mesto(окно):
    """На экране ожидания кнопки «Начать» нет: знак, одна фраза — и нажатие куда угодно.

    Перед стойкой стоит клиент, и искать на экране кнопку не должен никто. Клавиша тоже
    годится: у кассы под рукой клавиатура."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent
    from PySide6.QtCore import QEvent

    нажатий = []
    окно.s_main.начать.connect(lambda: нажатий.append(1))
    точка = QPointF(900, 500)
    for вид in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        QApplication.sendEvent(окно.s_main, QMouseEvent(вид, точка, точка, Qt.LeftButton,
                                                         Qt.LeftButton, Qt.NoModifier))
    assert нажатий == [1]
    QApplication.sendEvent(окно.s_main, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
    assert нажатий == [1, 1]
    # и сделка действительно начинается — с анкеты
    assert окно.stack.currentWidget() is окно.s_start


def test_shagi_sdelki_idut_za_sostoyaniem(окно):
    """Строка шагов сверху — карта сделки: что сделано, что идёт, где мы сейчас.

    Она обязана говорить правду: «Фото и видео» зелёным, пока сервер медиа не видел, — это
    сотрудник, который отдал телефон клиенту раньше, чем бот получил видео."""
    э = окно.s_work
    окно.начать_сделку()
    окно.анкета_готова(АНКЕТА)
    assert э.степпер.готово == [False] * 5 and 0 in э.степпер.идут, "телефон ещё читается"

    окно.state = "scanning"
    окно.on_done({"report": _отчёт("эталон_iPhone-14-Pro_iOS26.5.zip"), "client_id": "x"})
    assert э.степпер.готово[0] is True and not э.степпер.идут
    assert э.степпер.текущий == 1, "после кабеля — тест на телефоне"

    _тест_прошёл(окно)
    assert э.степпер.готово[1] is True and э.степпер.текущий == 2, "тест прошёл — проверки руками"

    _руками_отмечено(окно)
    assert э.степпер.готово[2] is True
    # сервер медиа не видит — шаг не зелёный, хотя сделку это не держит
    э.set_медиа({"известно": False, "почему": "сервер не ответил"})
    assert э.степпер.готово[3] is False
    _медиа_собраны(окно)
    assert э.степпер.готово[3] is True and э.степпер.готово[4] is False


def test_po_shagu_mozhno_nazhat(окно):
    """Шаги — ещё и навигация: кнопок «К тесту», «К фото» в карточках больше нет."""
    _чистый(окно)
    э = окно.s_work
    for шаг, страница in ((1, ui_deal.СТР_ТЕСТ), (2, ui_deal.СТР_РУЧНАЯ), (3, ui_deal.СТР_МЕДИА)):
        э.степпер.выбран.emit(шаг)
        assert э.правая.currentIndex() == страница and э.степпер.текущий == шаг
    э.степпер.выбран.emit(0)                       # «Проверка» и «Отправка» — не страницы
    assert э.правая.currentIndex() == ui_deal.СТР_МЕДИА


def test_pasport_govorit_glavnoe_krupno(окно):
    """Кольцо батареи и вердикт одним словом — в паспорте телефона, а не мелкими плашками."""
    _чистый(окно)
    э = окно.s_work
    assert э.кольцо.значение == 81
    assert э.вердикт.text() == "Хороший"
    assert "1642" in э.вердикт_подпись.text() and "цикл" in э.вердикт_подпись.text()
    assert "iPhone 14 Pro" in э.аппарат.text() and "IMEI" in э.аппарат_подробно.text()
    # новая сделка — паспорт пустой: чужой телефон на экране остаться не может
    э.начать()
    assert э.кольцо.значение is None and э.вердикт.text() == "" and э.аппарат_подробно.text() == ""


def test_slova_bez_emodzi_i_s_pravilnym_chislom():
    """Надписи Оценки приходят с эмодзи — на экране кассы их нет. И «1064 цикла», а не «циклов»."""
    assert ui_deal.без_значка("📱 Б/у телефон в нормальном состоянии") == "Б/у телефон в нормальном состоянии"
    assert ui_deal.без_значка("📦 Запечатанный (новый)") == "Запечатанный (новый)"
    assert ui_deal.без_значка("«Детали»") == "«Детали»"
    assert [ui_deal.циклов(n) for n in (1, 2, 5, 11, 22, 101, 1064)] == [
        "1 цикл", "2 цикла", "5 циклов", "11 циклов", "22 цикла", "101 цикл", "1064 цикла"]


def test_panel_istorii_vmeshchaet_svoy_tekst(окно):
    """Развёрнутая история не обрезает строки. Раньше панель выходила ниже своего текста:
    высота подписи с переносом зависит от ширины, а `adjustSize` этого не считает."""
    э = окно.s_work
    э.set_история({"почему": [], "наши": [],
                   "заявки": [{"номер": "PT-0001", "когда": "19.10.2026 13:11", "имя": "Клиент",
                               "телефон": "…0011", "модель": "iPhone 14 Pro 256 ГБ", "цена": "220500",
                               "вид": "В идеальном состоянии", "не_работает": "всё работает"}],
                   "оценки": [{"сделка": 12367, "когда": "13.10.2026", "точка": "Тарлан",
                               "модель": "iPhone 14 Pro 256 ГБ", "акб": "78%", "автоцена": 180000,
                               "выкуп": 80000, "статус": "Выкуплен", "состояние": "Не был в ремонте"}]})
    э.история_переключить()
    панель = э.история_панель
    assert not панель.isHidden()
    assert панель.height() >= панель.высота_для(панель.width())
    assert панель.текст.heightForWidth(панель.текст.width()) <= панель.текст.height() + 1


def test_a_silent_apple_service_is_fixed_by_the_program_itself(окно, monkeypatch):
    """Служба Apple молчит: сначала программа молча пробует поднять её сама, и только если
    не вышло — показывает кнопку. Сотруднику не нужно знать слов «Apple Mobile Device
    Service»: раньше экран просил перезапустить её руками, и точка стояла."""
    from pintel_core.devicelink import apple_service
    from pintel_core.devicelink.connect import NO_DEVICE, NO_DRIVER

    попытки, по_кнопке = [], []
    monkeypatch.setattr(окно, "_run", lambda fn, ok=None, err=None: попытки.append((fn, ok)))
    кнопка = окно.s_main.b_связь
    assert кнопка.isHidden()

    окно.on_tick(NO_DRIVER, "", 0)
    assert len(попытки) == 1 and попытки[0][0] is apple_service.починить
    assert кнопка.isHidden(), "пока идёт тихая попытка, кнопку не показываем"
    окно.on_tick(NO_DRIVER, "", 0)
    assert len(попытки) == 1, "вторую попытку поверх первой не запускаем"

    попытки[0][1](apple_service.НУЖНЫ_ПРАВА)            # без прав не вышло
    окно.on_tick(NO_DRIVER, "", 0)
    assert not кнопка.isHidden() and "Починить связь" in кнопка.text()
    assert len(попытки) == 1, "молча пробуем один раз за сбой"

    # по кнопке — полный путь: установка или перезапуск с окном Windows
    monkeypatch.setattr(apple_service, "обеспечить",
                        lambda сказать=None: по_кнопке.append(1) or (apple_service.ГОТОВО, "готово"))
    окно.починить_связь()
    assert not кнопка.isEnabled() and "Чиним" in кнопка.text()
    fn, ok = попытки[-1]
    ok(fn())
    assert по_кнопке == [1] and кнопка.isHidden()

    # связь вернулась — следующий сбой снова начнётся с тихой попытки
    окно.on_tick(NO_DEVICE, "", 0)
    окно.on_tick(NO_DRIVER, "", 0)
    assert len(попытки) == 3 and попытки[-1][0] is apple_service.починить


def test_the_repair_button_is_not_offered_outside_windows(окно, monkeypatch):
    """На маке и линуксе службы Apple нет вовсе — кнопка там была бы обманом."""
    from pintel_core.devicelink import apple_service
    from pintel_core.devicelink.connect import NO_DRIVER

    попытки = []
    monkeypatch.setattr(окно, "_run", lambda fn, ok=None, err=None: попытки.append((fn, ok)))
    окно.on_tick(NO_DRIVER, "", 0)
    попытки[0][1](apple_service.НЕ_WINDOWS)
    окно.on_tick(NO_DRIVER, "", 0)
    assert окно.s_main.b_связь.isHidden() and len(попытки) == 1
