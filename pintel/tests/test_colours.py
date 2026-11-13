# -*- coding: utf-8 -*-
"""Цвет телефона одним словарём: английское слово заглавными — в кассе, чеке и сделке.

До 13.11.2026 цвет из базы IMEI переводился на русский по таблице, а чего в таблице не было,
оставалось как пришло. Все написания ниже взяты из боевых проверок кассы и из сделок,
которые касса отправила в бот: «Blue Ttnm», «Naturl Ttnm», «Bur», «White Cellular» лежали
рядом с «чёрный космос» и «тёмная ночь», а в название товара МойСклада уезжало «NATURL TTNM».
"""
import pytest

from pintel_core import colours, receipt
from pintel_core.analysis import sealed
from pintel_core.external import ocenka, sickw


@pytest.mark.parametrize("сырое,ждём", [
    # сокращения и мусор базы IMEI — так цвет лежал в проверках и уезжал в название товара
    ("NATURL TTNM", "NATURAL"), ("Naturl Ttnm", "NATURAL"), ("BLUE TTNM", "BLUE"),
    ("DESERT TTNM", "DESERT"), ("BLK TTNM", "BLACK"), ("BUR", "BURGUNDY"), ("ORG", "ORANGE"),
    ("ORN", "ORANGE"), ("BLU", "BLUE"), ("BLK", "BLACK"), ("DEEPPURPLE", "DEEP PURPLE"),
    ("White Cellular", "WHITE"), ("Silver Cellular", "SILVER"), ("GPH", "GRAPHITE"),
    # полные названия Apple — уточнения выбрасываются
    ("SPACE BLACK", "BLACK"), ("Space Gray", "GRAY"), ("Natural Titanium", "NATURAL"),
    ("Black Titanium", "BLACK"), ("Jet Black", "BLACK"), ("Cosmic Orange", "ORANGE"),
    ("(PRODUCT)RED", "RED"), ("Deep Purple", "DEEP PURPLE"), ("Sierra Blue", "SIERRA BLUE"),
    ("Sky Blue", "SKY BLUE"), ("SKY", "SKY BLUE"), ("Midnight Green", "MIDNIGHT GREEN"),
    ("MIDNIGHT", "MIDNIGHT"), ("gold", "GOLD"),
    # русское — так цвет записан в прежних проверках и приходит от касс прежних сборок
    ("чёрный космос", "BLACK"), ("тёмная ночь", "MIDNIGHT"), ("тёмно-фиолетовый", "DEEP PURPLE"),
    ("синий", "BLUE"), ("золотой", "GOLD"), ("розовый", "PINK"), ("чёрный / графитовый", "BLACK"),
    # цвет по коду корпуса — пара, берём первое
    ("BLACK / GRAPHITE", "BLACK"), ("NATURAL / JET BLACK", "NATURAL"), ("ORANGE / CORAL", "ORANGE"),
    # незнакомое английское слово проходит: новые цвета выходят каждый год
    ("Mauve", "MAUVE"),
])
def test_every_spelling_becomes_one_word(сырое, ждём):
    assert colours.цвет(сырое) == ждём


@pytest.mark.parametrize("сырое", [
    "Pro A2891", "A2891", "iPhone 14 Pro", "Pro Max", "", None, "неведомый цвет", "Unknown", "N/A",
    "256GB", "one two three four",
])
def test_what_is_not_a_colour_stays_empty(сырое):
    """Пустое поле карточка и чек просто не печатают. Мусор в нём — печатают."""
    assert colours.цвет(сырое) is None


def test_dictionary_is_closed_over_itself():
    """Каждое слово словаря переводится в слово словаря — иначе правка одной таблицы молча
    разойдётся с другой."""
    for имя in colours.КАНОН:
        assert colours.цвет(имя) == имя, имя
    for откуда in (colours.СОКРАЩЕНИЯ, colours.ФРАЗЫ, colours.РУССКИЕ):
        for сырое, имя in откуда.items():
            assert имя in colours.КАНОН, (сырое, имя)
            assert colours.цвет(сырое) == имя, сырое


@pytest.mark.parametrize("описание,ждём", [
    ("IPHONE 14 PRO GOLD 256GB-RUS", "GOLD"),             # из боевой проверки: цвет был «Pro A2891»
    ("IPHONE 13 PRO MAX GPH 128GB VER-USA", "GRAPHITE"),  # из боевой проверки: цвета не было вовсе
    ("IPHONE 14 PRO DEEP PURPLE 128GB", "DEEP PURPLE"),   # два слова раньше одного
    ("IPHONE 14 PRO SPACE BLACK 256GB", "BLACK"),
    ("IPHONE 13 PRO MAX 128GB VER-USA", None),
    ("IPHONE 12 64GB RED", None),                         # за объёмом — регион, там не ищем
    ("", None), (None, None),
])
def test_colour_is_found_inside_a_solid_description(описание, ждём):
    assert colours.цвет_в_тексте(описание) == ждём


@pytest.mark.parametrize("поля,ждём", [
    ({"Model Description": "IPHONE 15 PRO,NAJP,256GB,BLUE TTNM"}, "BLUE"),
    ({"Model Description": "IPHONE 15 PRO MAX,ROW,256GB,NATURL TTNM"}, "NATURAL"),
    ({"Model Description": "IPHONE 16 PRO,ROW,256GB,DESERT TTNM"}, "DESERT"),
    ({"Model Description": "IPHONE 16 PROMAX,ROW,256GB,BLK TTNM"}, "BLACK"),
    ({"Model Description": "IPHONE 18 PRO MAX,NAUS,256GB,BUR"}, "BURGUNDY"),
    ({"Model Description": "IPHONE 17 PRO MAX,ROW,512GB,ORG"}, "ORANGE"),
    ({"Model Description": "IPHONE 14 PRO MAX,CHINA,256GB,DEEPPURPLE"}, "DEEP PURPLE"),
    ({"Model Description": "IPHONE 14 PRO,NAJP,128GB,SPACE BLACK"}, "BLACK"),
    ({"Model Description": "IPHONE 13,RUSSIA,128GB,MIDNIGHT"}, "MIDNIGHT"),
    ({"Model": "iPhone 11 128GB White Cellular", "Model Description": "IPHONE 11,NA,128GB,WHITE"}, "WHITE"),
    ({"Model": "iPhone 14 Pro A2891", "Model Description": "IPHONE 14 PRO GOLD 256GB-RUS"}, "GOLD"),
    ({"Model Description": "IPHONE 13 PRO MAX GPH 128GB VER-USA"}, "GRAPHITE"),
])
def test_imei_database_answers_from_production(поля, ждём):
    """Ответы базы IMEI ровно в том виде, в каком они лежат в боевых проверках."""
    n = sickw.normalize(поля)
    assert n["цвет"] == ждём
    assert ocenka.цвет_для_оценки(n["цвет"]) == ждём      # в сделку и в название товара — то же слово


def test_old_russian_answer_is_translated_in_the_report():
    """Ответ базы IMEI, сохранённый кассой до правки, лежит по-русски. Отчёт, собранный по
    нему заново, обязан назвать цвет уже по-новому — и на экране, и в чеке."""
    rep = sealed.build({"модель": "iPhone 15 Pro", "объём_гб": 256, "цвет": "натуральный титан",
                        "активирован": False}, ["356789012345678"])
    assert rep["паспорт"]["цвет"] == "NATURAL"
    страница = receipt.html({"номер": 1, "клиент": "Пример", "телефон": "", "сотрудник": "Пример",
                             "точка": "Пример"}, rep)
    assert "NATURAL" in страница and "натуральный титан" not in страница


def test_old_report_falls_back_to_the_raw_word():
    """В прежней записи русского слова могло и не быть — только сырое «Naturl Ttnm»."""
    rep = sealed.build({"модель": "iPhone 15 Pro Max", "объём_гб": 256, "цвет": "Naturl Ttnm",
                        "цвет_исходный": "NATURL TTNM"}, ["356789012345678"])
    assert rep["паспорт"]["цвет"] == "NATURAL"


# ---------------------------------------------------------------- цвета по моделям

@pytest.mark.parametrize("слово,модель,ждём", [
    ("BLUE", "iPhone 17 Pro", "DEEP BLUE"),          # база пишет «BLU», цвет называется DEEP BLUE
    ("BLUE", "iPhone 13 Pro", "SIERRA BLUE"),
    ("GREEN", "iPhone 13 Pro Max", "ALPINE GREEN"),
    ("PURPLE", "iPhone 14 Pro", "DEEP PURPLE"),
    ("WHITE", "iPhone Air", "CLOUD WHITE"),
    ("BLUE", "iPhone 17", "MIST BLUE"),
    ("BLUE", "iPhone 15 Pro", "BLUE"),               # своё слово — не трогаем
    ("BLUE", "iPhone 12", "BLUE"),
    ("BLACK", "iPhone 16 Promax", "BLACK"),          # так модель пишет база IMEI
    ("BURGUNDY", "iPhone 18 Pro Max", "BURGUNDY"),   # модели нет в списке — не трогаем
    ("MAUVE", "iPhone 14 Pro", "MAUVE"),             # нового цвета список может не знать
    ("BLUE", None, "BLUE"), (None, "iPhone 14 Pro", None),
])
def test_database_word_becomes_the_models_own_colour(слово, модель, ждём):
    """Сотрудник кнопкой выбирает полное слово, база сокращает. Без сверки один и тот же
    цвет лёг бы в товары под двумя названиями — «BLUE» и «DEEP BLUE» у iPhone 17 Pro."""
    assert colours.уточнить(слово, модель) == ждём


def test_imei_database_short_word_is_matched_to_the_model():
    assert sickw.normalize({"Model Description": "IPHONE 17 PRO,NAJP,256GB,BLU"})["цвет"] == "DEEP BLUE"
    assert sickw.normalize({"Model Description": "IPHONE 12,ROW,128GB,BLUE"})["цвет"] == "BLUE"


def test_model_lists_and_swatches_speak_the_dictionary():
    """Кнопки выбора цвета строятся из этих таблиц: слово не из словаря на кнопке — это
    слово не из словаря в сделке и в названии товара."""
    assert set(colours.ОБРАЗЦЫ) == set(colours.КАНОН)
    for модель, цвета in colours.ЦВЕТА_МОДЕЛЕЙ.items():
        assert цвета and len(set(цвета)) == len(цвета), модель
        assert set(цвета) <= colours.КАНОН, модель
        assert colours.цвета_модели(модель.upper()) == цвета      # регистр и пробелы не важны
    assert colours.цвета_модели("iPhone 99") == () and colours.цвета_модели(None) == ()
