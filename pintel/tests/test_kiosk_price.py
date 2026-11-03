# -*- coding: utf-8 -*-
"""Свой прайс у точки: ссылка на вкладку в `shops.price_url`.

Файл лежит в `deploy/оценка_бот/` и ставится на сервер руками, поэтому проверяем его
здесь — до установки. Google и база сюда не ходят: разбор ссылки и поиск цены в строках
чистые, а поход за вкладкой и чтение колонки подменяются.

Главное, что проверяется: **своя вкладка у точки есть, а строки в ней нет — автоцены нет
вовсе**. Падение на общий прайс в этом месте значило бы цену из чужого списка, названную
клиенту на этой точке.
"""
import asyncio
import importlib.util
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ФАЙЛ = os.path.join(HERE, "..", "deploy", "оценка_бот", "kiosk_price.py")

# Раскладка колонок по диапазонам АКБ — копия из `utils/google_price.py` бота: модуль берёт
# её оттуда, а в тестах того модуля нет, поэтому подкладываем такой же.
КОЛОНКИ_АКБ = {"нет информации": 3, "0-74": 4, "75-79": 5, "80-85": 6, "86-90": 7,
               "91-95": 8, "96-99": 9, "100": 10, "100 (0-30)": 11}

ТАБЛИЦА = [
    ["Марка", "Модель", "Память", "нет информации", "0-74", "75-79", "80-85", "86-90",
     "91-95", "96-99", "100", "100 (0-30)"],
    ["Apple", "iPhone 14 Pro", "128", "200000", "210000", "220000", "230000", "240 000",
     "250000", "260000", "270000", "280000"],
    ["Apple", "iPhone 13", "256", "", "", "", "", "", "", "", "", ""],
    ["Apple", "iPhone 12", "64", "100000"],
]


class Сделка:
    """Та часть `devices`, по которой считается цена."""

    def __init__(self, shop_id_grade=7, producer="Apple", model="iPhone 14 Pro",
                 ddr=128, akb="86-90"):
        self.shop_id_grade, self.producer, self.model = shop_id_grade, producer, model
        self.ddr, self.akb = ddr, akb


@pytest.fixture
def прайс(monkeypatch):
    """Модуль с подменёнными походами наружу: в базу и в Google."""
    фальшивый = types.ModuleType("utils.google_price")
    фальшивый.AKB_COL_INDEX_BY_STATE = dict(КОЛОНКИ_АКБ)
    фальшивый._get_client = lambda: (_ for _ in ()).throw(AssertionError("в тесте Google не зовём"))
    utils = types.ModuleType("utils")
    utils.google_price = фальшивый
    monkeypatch.setitem(sys.modules, "utils", utils)
    monkeypatch.setitem(sys.modules, "utils.google_price", фальшивый)

    spec = importlib.util.spec_from_file_location("kiosk_price", ФАЙЛ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.сбросить_кэш()
    return m


def _подменить(модуль, monkeypatch, ссылка="", вкладка=ТАБЛИЦА, падать=False):
    """Точка со ссылкой (или без) и вкладка, которую «вернул» Google."""
    прочитано = []

    async def ссылка_точки(shop_id):
        return ссылка

    def вкладка_из_google(ключ, номер):
        прочитано.append((ключ, номер))
        if падать:
            raise RuntimeError("Google не ответил")
        return вкладка

    monkeypatch.setattr(модуль, "ссылка_точки", ссылка_точки)
    monkeypatch.setattr(модуль, "_вкладка", вкладка_из_google)
    return прочитано


@pytest.mark.parametrize("ссылка,ждём", [
    ("https://docs.google.com/spreadsheets/d/1TJWXvVC9eBFqqqqqqqqqqqqqqqqqq/edit#gid=1917713663",
     ("1TJWXvVC9eBFqqqqqqqqqqqqqqqqqq", 1917713663)),
    # «скопировать ссылку на лист» отдаёт номер вкладки после вопросительного знака
    ("https://docs.google.com/spreadsheets/d/1TJWXvVC9eBFqqqqqqqqqqqqqqqqqq/edit?gid=42#gid=42",
     ("1TJWXvVC9eBFqqqqqqqqqqqqqqqqqq", 42)),
    # без номера — первый лист документа, как и у самого Google
    ("https://docs.google.com/spreadsheets/d/1TJWXvVC9eBFqqqqqqqqqqqqqqqqqq/edit",
     ("1TJWXvVC9eBFqqqqqqqqqqqqqqqqqq", None)),
    ("  https://docs.google.com/spreadsheets/d/1TJWXvVC9eBFqqqqqqqqqqqqqqqqqq/  ",
     ("1TJWXvVC9eBFqqqqqqqqqqqqqqqqqq", None)),
])
def test_the_link_to_a_tab_is_parsed(прайс, ссылка, ждём):
    """Ссылку в базу вписывают руками, копируя из адресной строки, — разбирать надо все её
    обычные виды."""
    assert прайс.разобрать_ссылку(ссылка) == ждём


@pytest.mark.parametrize("мусор", ["", None, "гугл-таблица точки", "https://example.com/x",
                                   "https://docs.google.com/document/d/abcdefghijklmnopqrstuv/edit"])
def test_what_is_not_a_link_is_not_taken_for_one(прайс, мусор):
    """В колонку могут вписать что угодно: пояснение, адрес документа, пустую строку."""
    assert прайс.разобрать_ссылку(мусор) is None


def test_the_price_is_found_the_same_way_as_in_the_common_list(прайс):
    """Правила поиска те же, что у общего прайса: марка, модель, память и колонка по АКБ."""
    цена = прайс.цена_в_таблице(ТАБЛИЦА, КОЛОНКИ_АКБ["86-90"], "Apple", "iPhone 14 Pro", 128)
    assert цена == 240000, "пробел внутри числа — это разделитель тысяч, а не другая цена"
    assert прайс.цена_в_таблице(ТАБЛИЦА, КОЛОНКИ_АКБ["100"], " apple ", "IPHONE 14 PRO",
                                " 128 ") == 270000, "регистр и пробелы не должны мешать"
    # пустая клетка — это «цены нет», а не ноль
    assert прайс.цена_в_таблице(ТАБЛИЦА, КОЛОНКИ_АКБ["100"], "Apple", "iPhone 13", 256) is None
    # строка короче нужной колонки — тоже «нет цены», а не ошибка
    assert прайс.цена_в_таблице(ТАБЛИЦА, КОЛОНКИ_АКБ["100"], "Apple", "iPhone 12", 64) is None
    assert прайс.цена_в_таблице(ТАБЛИЦА, КОЛОНКИ_АКБ["86-90"], "Apple", "iPhone 15", 128) is None
    # шапку за цену не принимаем
    assert прайс.цена_в_таблице(ТАБЛИЦА, 3, "Марка", "Модель", "Память") is None


def test_a_point_without_its_own_price_is_counted_by_the_common_one(прайс, monkeypatch):
    """Пустая `price_url` — поведение ровно прежнее: цену считает общий прайс."""
    прочитано = _подменить(прайс, monkeypatch, ссылка="")
    свой, цена = asyncio.run(прайс.по_точке(Сделка()))
    assert (свой, цена) == (False, None) and прочитано == [], "за вкладкой ходить незачем"


def test_a_point_with_its_own_price_gets_it(прайс, monkeypatch):
    """Ссылка есть — цена берётся из её вкладки, а не из общей."""
    прочитано = _подменить(
        прайс, monkeypatch,
        ссылка="https://docs.google.com/spreadsheets/d/1TJWXvVC9eBFqqqqqqqqqqqqqqqqqq/edit#gid=55")
    свой, цена = asyncio.run(прайс.по_точке(Сделка()))
    assert (свой, цена) == (True, 240000)
    assert прочитано == [("1TJWXvVC9eBFqqqqqqqqqqqqqqqqqq", 55)]


def test_a_model_missing_from_the_point_price_gets_no_autoprice(прайс, monkeypatch):
    """Свой прайс есть, а строки в нём нет — автоцены нет вовсе.

    Падение на общий прайс здесь значило бы цену из чужого списка, названную клиенту на
    этой точке. Такая сделка уходит оценщику — это и просили."""
    _подменить(прайс, monkeypatch,
               ссылка="https://docs.google.com/spreadsheets/d/1TJWXvVC9eBFqqqqqqqqqqqqqqqqqq/edit#gid=55")
    свой, цена = asyncio.run(прайс.по_точке(Сделка(model="iPhone 15 Pro Max")))
    assert (свой, цена) == (True, None)


def test_an_unreadable_tab_gets_no_autoprice_either(прайс, monkeypatch):
    """Google не ответил или в колонке не ссылка — тоже без автоцены, а не по общему прайсу.

    Сеть и квоты падают молча, и подстановка общей цены была бы незаметной ошибкой в
    деньгах."""
    _подменить(прайс, monkeypatch, падать=True,
               ссылка="https://docs.google.com/spreadsheets/d/1TJWXvVC9eBFqqqqqqqqqqqqqqqqqq/edit#gid=55")
    assert asyncio.run(прайс.по_точке(Сделка())) == (True, None)

    _подменить(прайс, monkeypatch, ссылка="прайс в телеграме у Асхата")
    assert asyncio.run(прайс.по_точке(Сделка())) == (True, None)


def test_an_unknown_battery_range_gets_no_autoprice(прайс, monkeypatch):
    """Диапазон АКБ, которого нет в раскладке колонок, — не повод взять соседнюю колонку."""
    _подменить(прайс, monkeypatch,
               ссылка="https://docs.google.com/spreadsheets/d/1TJWXvVC9eBFqqqqqqqqqqqqqqqqqq/edit#gid=55")
    assert asyncio.run(прайс.по_точке(Сделка(akb="почти новый"))) == (True, None)


class ФейкЛист:
    def __init__(self, значения):
        self.значения = значения

    def get_all_values(self):
        return self.значения


class ФейкКнига:
    def __init__(self, счётчик):
        self.счётчик = счётчик

    def get_worksheet_by_id(self, номер):
        self.счётчик.append(номер)
        return ФейкЛист(ТАБЛИЦА)

    def get_worksheet(self, n):
        self.счётчик.append(n)
        return ФейкЛист(ТАБЛИЦА)


def test_the_tab_is_not_fetched_for_every_deal(прайс, monkeypatch):
    """Вкладку держим в памяти: иначе каждая сделка — это поход в Google посреди нажатия.

    Кэш живёт минутами и сбрасывается кнопкой админа, поэтому правка цен доезжает сама."""
    походы = []
    клиент = type("Клиент", (), {"open_by_key": lambda self, ключ: ФейкКнига(походы)})()
    sys.modules["utils.google_price"]._get_client = lambda: клиент

    assert прайс._вкладка("К", 55) == ТАБЛИЦА
    assert прайс._вкладка("К", 55) == ТАБЛИЦА
    assert походы == [55], "вторая сделка подряд не должна ходить в Google"

    прайс.сбросить_кэш()                       # кнопка админа «сбросить кэш»
    assert прайс._вкладка("К", 55) == ТАБЛИЦА
    assert походы == [55, 55], "после сброса вкладка читается заново"

    # просроченная запись тоже перечитывается — правка цен доезжает и без кнопки
    прайс._кэш[("К", 55)] = (прайс.time.monotonic() - прайс.КЭШ_СЕКУНД - 1, [["старое"]])
    assert прайс._вкладка("К", 55) == ТАБЛИЦА
    assert походы == [55, 55, 55]
