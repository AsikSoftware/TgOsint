# -*- coding: utf-8 -*-
"""Отправка сделки боту Оценки: посылка, карточка, запрос в Telegram.

В базу Оценки с точки хода нет (порт Postgres закрыт наружу), поэтому единственный канал —
сам бот. Здесь проверяется то, что ломается молча: имена полей (их бот кладёт в devices
как есть), размер подписи и то, что приложение и обработчик зовут кнопку одинаково.
"""
import importlib.util
import json
import os

import httpx
import pytest

from pintel_core.external import ocenka, ocenka_tg

HERE = os.path.dirname(os.path.abspath(__file__))
ЯДРО = os.path.join(HERE, "..", "deploy", "оценка_бот", "kiosk_core.py")

ДАННЫЕ = {
    "модель": "iPhone 14 Pro", "код_модели": "iPhone15,2", "память": 256, "акб": 86,
    "цвет": "чёрный космос", "sim": "Dual sim", "коробка": True, "шнур": False,
    "panic_full": False, "статус_ремонта": ocenka.СТАТУС_ЧИСТЫЙ, "цена": 250000,
    "комментарий": "скол на рамке", "комментарий_оценщика": "Детали: родные",
    "имя_клиента": "Зама", "телефон_клиента": "+77058837953",
    "imei": "350585886690250", "imei_все": ["350585881725184", ""],
    "замки": ["Найти iPhone вкл."],
}


def ядро():
    spec = importlib.util.spec_from_file_location("kiosk_core", ЯДРО)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_payload_speaks_in_her_column_names():
    """Бот кладёт «сделку» в devices как есть — значит имена здесь её, а не наши."""
    п = ocenka.посылка(ДАННЫЕ, "7KQ4M", литера="16/38", точка="16/38 Pintel")
    assert п["версия"] == ocenka.ВЕРСИЯ_ПОСЫЛКИ and п["код"] == "7KQ4M"
    сд = п["сделка"]
    assert сд["model"] == "iPhone 14 Pro" and сд["ddr"] == 256
    assert сд["akb"] == "86%" and сд["akb_exact"] == 86          # строка для карточки и число для отчётов
    assert сд["phone_status"] == "Не был в ремонте" and сд["price_grade_auto"] == 250000
    assert сд["sim"] in ocenka.SIM_ВАРИАНТЫ and сд["color"] == "чёрный космос"
    assert п["клиент"] == {"имя": "Зама", "телефон": "+77058837953"}
    assert п["imei"] == ["350585886690250", "350585881725184"]   # без пустых и без повторов
    assert "видео" not in json.dumps(п, ensure_ascii=False)      # медиа добавляет бот, не мы


def test_payload_refuses_before_it_leaves_the_point():
    """Чего не хватает — видно на точке, а не в чате у оценщика."""
    with pytest.raises(ocenka.ОшибкаЭкспорта) as e:
        ocenka.посылка({}, "7KQ4M")
    for слово in ("модель", "объём памяти", "имя и телефон клиента", "IMEI"):
        assert слово in str(e.value)


def test_card_shows_what_will_be_written():
    """Карточка — это и есть подтверждение: в ней видно то, что уйдёт в сделку."""
    текст = ocenka_tg.карточка(ocenka.посылка(ДАННЫЕ, "7KQ4M", точка="16/38"))
    assert "код 7KQ4M" in текст and "iPhone 14 Pro · 256 ГБ · чёрный космос" in текст
    assert "350585886690250" in текст and "Аккумулятор 86%" in текст
    assert "250 000 ₸" in текст                                  # цена читается, а не слипается
    assert "Не был в ремонте" in текст and "⚠ Найти iPhone вкл." in текст
    assert "Зама" in текст and "+77058837953" in текст
    assert "коробка" in текст and "шнур" not in текст.split("SIM:")[1].split("\n")[0]


def test_card_fits_telegram_caption():
    """Подпись к файлу у Telegram — 1024 знака; обрезаем сами, иначе оборвётся на полуслове."""
    длинный = {**ДАННЫЕ, "комментарий": "скол " * 400}
    текст = ocenka_tg.карточка(ocenka.посылка(длинный, "7KQ4M"))
    assert len(текст) <= ocenka_tg.ПРЕДЕЛ_ПОДПИСИ and текст.endswith("…")


def test_send_posts_file_with_button(monkeypatch):
    """Посылка уходит файлом с кнопкой: нажатие — единственное, что приносит её боту."""
    ушло = {}

    def фейк(url, data=None, files=None, timeout=None):
        ушло.update(url=url, data=data, files=files)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    monkeypatch.setattr(httpx, "post", фейк)
    п = ocenka.посылка(ДАННЫЕ, "7KQ4M")
    итог = ocenka_tg.отправить("123:ABC", -1001, п)
    assert итог["message_id"] == 42 and итог["код"] == "7KQ4M"
    assert ушло["url"].endswith("/bot123:ABC/sendDocument")
    assert ушло["data"]["chat_id"] == "-1001"
    кнопка = json.loads(ушло["data"]["reply_markup"])["inline_keyboard"][0][0]
    assert кнопка["callback_data"] == "kiosk_deal_7KQ4M"
    # файл — та же посылка: бот читает его, а не разбирает текст карточки
    assert json.loads(ушло["files"]["document"][1].decode("utf-8"))["код"] == "7KQ4M"


def test_both_sides_call_the_button_the_same():
    """Разойдутся префиксы — нажатие не дойдёт ни до одного обработчика, и это не увидит
    ни один другой тест: половина кода живёт на сервере."""
    assert ocenka_tg.ПРЕФИКС_КНОПКИ == ядро().ПРЕФИКС_КНОПКИ


def test_send_says_what_telegram_answered(monkeypatch):
    """Отказ Telegram показываем словами: «не ушло» без причины сотруднику бесполезно."""
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(
        400, json={"ok": False, "description": "chat not found"}))
    with pytest.raises(ocenka_tg.ОшибкаОтправки) as e:
        ocenka_tg.отправить("123:ABC", -1001, ocenka.посылка(ДАННЫЕ, "7KQ4M"))
    assert "chat not found" in str(e.value)

    def рвётся(*a, **k):
        raise httpx.ConnectError("нет сети")

    monkeypatch.setattr(httpx, "post", рвётся)
    with pytest.raises(ocenka_tg.ОшибкаОтправки) as e:
        ocenka_tg.отправить("123:ABC", -1001, ocenka.посылка(ДАННЫЕ, "7KQ4M"))
    assert "нет сети" in str(e.value)


@pytest.mark.parametrize("токен,чат,слово", [("", -1001, "ocenka_bot_token"),
                                             ("123:ABC", "", "ocenka_chat_id")])
def test_send_names_the_missing_setting(токен, чат, слово):
    with pytest.raises(ocenka_tg.ОшибкаОтправки) as e:
        ocenka_tg.отправить(токен, чат, {"код": "7KQ4M", "сделка": {}})
    assert слово in str(e.value)
