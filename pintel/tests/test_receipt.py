# -*- coding: utf-8 -*-
"""Чек на A4: клиент уносит его с собой, значит в нём не должно быть ни лишнего,
ни недосказанного. Содержимое проверяем здесь, вёрстку — глазами на печати."""
import os
import re

from pintel_core import receipt, reference
from pintel_core.devicelink import snapshot

HERE = os.path.dirname(os.path.abspath(__file__))


def _отчёт(архив="эталон_iPhone-14-Pro_iOS26.5.zip"):
    from pintel_core.analysis import report as report_mod
    snap, _ = reference.load_bundle(os.path.join(HERE, "fixtures_real", "эталоны", архив),
                                    loads=snapshot.loads)
    return report_mod.build(snap)


СДЕЛКА = {"номер": 7093, "клиент": "Зама",
          "телефон": "+77058837953", "сотрудник": "Асылбек", "точка": "16/38 Pintel",
          "коробка": True, "шнур": False}


def test_receipt_is_a_document_not_a_printout():
    """Клиент уносит это с собой: на листе должны быть логотип и реквизиты, иначе бумага
    ничья. Логотип вшит в страницу — чек открывается без интернета и соседних файлов."""
    txt = receipt.html({**СДЕЛКА, "фирма": {"название": "Pintel", "бин": "123456789012",
                                            "телефон": "+7 777 000 00 00", "адрес": "Алматы, 16/38"}},
                       _отчёт())
    assert "data:image/png;base64," in txt and "БИН 123456789012" in txt
    assert "Алматы, 16/38" in txt and "+7 777 000 00 00" in txt
    assert txt.count("подпись") == 2                 # подписывают обе стороны


def test_receipt_shows_everything_the_check_saw():
    """Прошлый чек печатал шесть строк «оригинальная» и ни слова о блокировках. Клиент
    должен видеть, за что ему назвали цену."""
    txt = receipt.html(СДЕЛКА, _отчёт())
    for раздел in ("Телефон", "Проверка подлинности", "Аккумулятор", "Блокировки и история"):
        assert раздел in txt, раздел
    assert "Циклов заряда" in txt and "Найти iPhone" in txt
    assert "Серийный номер" in txt and "Комплект" in txt
    assert "по кабелю" in txt                        # сноска о том, как проверяли


def test_receipt_has_no_price_at_all():
    """Цену называет Оценка по своему прайсу уже после создания сделки. Напечатать на
    бумаге сумму, которой ещё нет, значит пообещать то, что потом не совпадёт."""
    txt = receipt.html(СДЕЛКА, _отчёт())
    for слово in ("₸", "Цена", "цена", "250 000", "Действительна"):
        assert слово not in txt, слово


def test_receipt_shows_device_and_verdict():
    rep = _отчёт()
    txt = receipt.html(СДЕЛКА, rep)
    assert "iPhone 14 Pro" in txt and "№ 7093" in txt
    assert "Зама" in txt and "Асылбек" in txt and "16/38 Pintel" in txt
    assert "Клиент" in txt and "Оценку провёл" in txt


def test_receipt_tells_whether_apple_confirmed():
    """Главное, за что клиент платит вниманием: подтвердила ли Apple подлинность."""
    чистый = receipt.html(СДЕЛКА, _отчёт())
    assert "Apple подтвердила" in чистый
    проблемный = receipt.html(СДЕЛКА, _отчёт("эталон_iPhone-15-Pro_iOS26.6.1.zip"))
    assert "не подтвердила" in проблемный and "ПРОБЛЕМНЫЙ" in проблемный


def test_receipt_lists_parts_and_warnings():
    rep = _отчёт("эталон_iPhone-15-Pro_iOS26.6.1.zip")
    txt = receipt.html(СДЕЛКА, rep)
    assert "Экран" in txt and "не подтверждена" in txt
    assert "циклов" in txt                          # износ батареи попал в замечания


def test_receipt_hides_empty_rows():
    """Пустые поля не печатаем: пустая строка в чеке выглядит как недоработка."""
    rep = _отчёт()
    rep["паспорт"] = {**rep["паспорт"], "цвет": None, "imei2": ""}
    txt = receipt.html(СДЕЛКА, rep)
    assert "Цвет" not in txt and "IMEI 2" not in txt
    assert "IMEI" in txt


def test_receipt_is_plain_html_without_scripts():
    """Печатаем документ, а не страницу: ни скриптов, ни внешних загрузок."""
    txt = receipt.html(СДЕЛКА, _отчёт())
    assert "<script" not in txt.lower() and "http://" not in txt and "https://" not in txt
    assert re.search(r"@page\s*{[^}]*A4", txt)


def test_receipt_escapes_client_input():
    """Имя клиента приходит с клавиатуры — в документе оно должно остаться текстом."""
    сделка = {**СДЕЛКА, "клиент": '<b>Зама</b> & "сын"'}
    txt = receipt.html(сделка, _отчёт())
    assert "&lt;b&gt;Зама&lt;/b&gt;" in txt and "<b>Зама</b>" not in txt
