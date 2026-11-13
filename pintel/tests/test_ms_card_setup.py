# -*- coding: utf-8 -*-
"""Правки самого МойСклада (`deploy/оценка_бот/ms_card_setup.py`): «Заключение» и «Цвет».

МойСклад у нас один — и у боевого бота, и у тестового, — поэтому обкатать скрипт «на тесте»
нельзя: любая запись настоящая. Обкатываем здесь, на подменном МойСкладе, который ведёт
себя как настоящий в том, что скрипту важно: поля товара, справочники, значения, товары.
Первый же прогон всухую на боевом упал на ошибке, которую поймал бы этот файл.
"""
import importlib.util
import os
import re
import urllib.parse

import pytest

from pintel_core import colours

HERE = os.path.dirname(os.path.abspath(__file__))
ФАЙЛ = os.path.join(HERE, "..", "deploy", "оценка_бот", "ms_card_setup.py")
А = "https://api.moysklad.ru/api/remap/1.2"
# справочник «Цвет», каким он был в МойСкладе 13.11.2026: заведён, но ни к чему не подключён
БЫЛО = ["Ultramarine", "Teal", "Orange", "Silver", "Black (Midnight)", "White (Starlight)",
        "Green", "Purple", "Red", "Blue", "Gold", "Pink", "Natural", "Desert"]


@pytest.fixture(scope="module")
def м():
    spec = importlib.util.spec_from_file_location("ms_card_setup", ФАЙЛ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)            # main() при импорте не запускается
    return m


def склад(м, всухую=False, *, справочник=БЫЛО, цвет_строкой=True, товары=()):
    """Подменный МойСклад. → объект Склад, у которого `.мир` — всё, что в нём лежит."""
    мир = {"поля": [], "справочники": {}, "товары": [], "счёт": 0, "записи": []}

    def новый_id():
        мир["счёт"] += 1
        return f"id{мир['счёт']:04d}"

    def поле(имя, вид, справочник_id=None):
        i = новый_id()
        a = {"id": i, "name": имя, "type": вид,
             "meta": {"href": f"{А}/entity/product/metadata/attributes/{i}"}}
        if справочник_id:
            a["customEntityMeta"] = {"href": f"{А}/context/companysettings/metadata/customEntities/{справочник_id}",
                                     "type": "customentitymetadata", "mediaType": "application/json"}
        мир["поля"].append(a)
        return a

    def значение(cid, имя):
        i = новый_id()
        v = {"id": i, "name": имя, "meta": {"href": f"{А}/entity/customentity/{cid}/{i}"}}
        мир["справочники"][cid]["значения"].append(v)
        return v

    мир["справочники"]["akb"] = {"name": "АКБ", "значения": []}
    значение("akb", "100%")
    поле("АКБ", "customentity", "akb")
    if справочник is not None:
        мир["справочники"]["col"] = {"name": "Цвет", "значения": []}
        for имя in справочник:
            значение("col", имя)
    строка = поле("Цвет", "string") if цвет_строкой else None
    for n, цвет in enumerate(товары):
        мир["товары"].append({"meta": {"href": f"{А}/entity/product/p{n}"},
                              "attributes": [{"meta": строка["meta"], "name": "Цвет", "value": цвет}]})

    class Подмена(м.Склад):
        def запрос(self, метод, адрес, тело=None):
            путь = адрес.replace(А, "")
            if метод != "GET":
                мир["записи"].append((метод, путь, тело))
            if метод == "GET" and путь.startswith("/entity/product/metadata/attributes"):
                return {"rows": [dict(a) for a in мир["поля"]]}
            if метод == "GET" and путь == "/context/companysettings/metadata":
                return {"customEntities": [
                    {"name": d["name"], "entityMeta": {"href": f"{А}/entity/customentity/{cid}"},
                     "meta": {"href": f"{А}/context/companysettings/metadata/customEntities/{cid}"}}
                    for cid, d in мир["справочники"].items()]}
            m_ = re.fullmatch(r"/entity/customentity/(\w+)\?limit=100&offset=(\d+)", путь)
            if метод == "GET" and m_:
                return {"rows": [dict(v) for v in мир["справочники"][m_.group(1)]["значения"]][int(m_.group(2)):][:100]}
            if метод == "POST" and путь == "/entity/customentity":
                cid = новый_id()
                мир["справочники"][cid] = {"name": тело["name"], "значения": []}
                return {"id": cid, "name": тело["name"]}
            m_ = re.fullmatch(r"/entity/customentity/(\w+)", путь)
            if метод == "POST" and m_:
                assert not any(v["name"] == тело["name"] for v in мир["справочники"][m_.group(1)]["значения"])
                return значение(m_.group(1), тело["name"])
            m_ = re.fullmatch(r"/entity/customentity/(\w+)/(\w+)", путь)
            if метод == "PUT" and m_:
                v = next(v for v in мир["справочники"][m_.group(1)]["значения"] if v["id"] == m_.group(2))
                v["name"] = тело["name"]
                return v
            if метод == "POST" and путь == "/entity/product/metadata/attributes":
                assert not any(a["name"] == тело["name"] for a in мир["поля"]), "двух полей с одним именем не бывает"
                cid = тело["customEntityMeta"]["href"].rsplit("/", 1)[-1] if тело.get("customEntityMeta") else None
                assert cid is None or cid in мир["справочники"], "поле ссылается на несуществующий справочник"
                return поле(тело["name"], тело["type"], cid)
            m_ = re.fullmatch(r"/entity/product/metadata/attributes/(\w+)", путь)
            if метод == "PUT" and m_:
                assert not any(a["name"] == тело["name"] for a in мир["поля"]), "имя поля занято"
                a = next(a for a in мир["поля"] if a["id"] == m_.group(1))
                a["name"] = тело["name"]
                return a
            if метод == "GET" and путь.startswith("/entity/product?"):
                q = urllib.parse.parse_qs(путь.split("?", 1)[1])
                href = q["filter"][0][:-2]
                assert q["filter"][0].endswith("!=")
                есть = [т for т in мир["товары"] if any(a["meta"]["href"] == href for a in т["attributes"])]
                return {"rows": есть[int(q["offset"][0]):][:int(q["limit"][0])]}
            m_ = re.fullmatch(r"/entity/product/(p\d+)", путь)
            if метод == "PUT" and m_:
                т = next(т for т in мир["товары"] if т["meta"]["href"].endswith("/" + m_.group(1)))
                т["attributes"] += тело["attributes"]            # прежние поля товара не трогаются
                return т
            raise AssertionError(f"скрипт спросил то, чего мы не ждали: {метод} {путь}")

    с = Подмена("ключ", всухую)
    с.мир = мир
    return с


def test_colour_becomes_a_dictionary_with_the_words_of_the_shared_dictionary(м, capsys):
    """«Цвет» из строки — в справочник: значения — слова словаря кассы, прежнее поле остаётся
    под именем «Цвет (старое)», цвет товаров переносится. Ничего не удаляется."""
    с = склад(м, товары=["WHITE", "СИНИ", "Natural Titanium", "чёрный космос"])
    м.цвет(с)
    мир = с.мир
    слова = [v["name"] for v in мир["справочники"]["col"]["значения"]]
    assert sorted(слова) == sorted(colours.КАНОН) and len(слова) == len(set(слова)), \
        "в справочнике ровно слова словаря: без дублей и без прежних «Black (Midnight)»"
    поля = {a["name"]: a for a in мир["поля"]}
    assert поля["Цвет"]["type"] == "customentity" and поля["Цвет"]["customEntityMeta"]["href"].endswith("/col")
    assert поля["Цвет (старое)"]["type"] == "string" and "Цвет (справочник)" not in поля
    assert not any(метод == "DELETE" for метод, _, _ in мир["записи"])

    def цвет_товара(n):
        новые = [a for a in мир["товары"][n]["attributes"] if a["meta"] == поля["Цвет"]["meta"]]
        return next((v["name"] for v in мир["справочники"]["col"]["значения"]
                     if новые and v["meta"] == новые[0]["value"]["meta"]), None)
    assert [цвет_товара(n) for n in range(4)] == ["WHITE", None, "NATURAL", "BLACK"]
    assert all(т["attributes"][0]["value"] for т in мир["товары"]), "прежнее значение при товаре осталось"
    вывод = capsys.readouterr().out
    assert "слова в словаре нет у 1: СИНИ" in вывод, "что не перенеслось — названо, а не потеряно"

    # повторный запуск ничего не меняет
    было_записей = len(мир["записи"])
    м.цвет(с)
    assert len(мир["записи"]) == было_записей
    assert "уже стояло 3" in capsys.readouterr().out


def test_a_dry_run_writes_nothing_and_says_what_it_would_do(м, capsys):
    с = склад(м, всухую=True, товары=["WHITE", "СИНИ"])
    м.цвет(с)
    assert с.мир["записи"] == [] and с.сделано == []
    вывод = capsys.readouterr().out
    assert "[всухую] переименовать значение «Black (Midnight)» → «BLACK»" in вывод
    assert "[всухую] добавить значение «DEEP PURPLE»" in вывод
    assert "[всухую] создать поле «Цвет (справочник)»" in вывод
    assert "[всухую] переименовать строковое поле «Цвет» → «Цвет (старое)»" in вывод
    assert "[всухую] переименовать поле «Цвет (справочник)» → «Цвет»" in вывод
    assert "[всухую] товар: «WHITE» → WHITE" in вывод and "слова в словаре нет у 1: СИНИ" in вывод


def test_colour_starts_from_nothing_and_stops_when_the_dictionary_is_someone_elses(м):
    """Справочника нет вовсе — заводится. А если справочник «Цвет» уже подключён к чужому
    полю, его значения стоят у чьих-то товаров: переименовывать их нельзя — стоп, без записей."""
    с = склад(м, справочник=None, цвет_строкой=False)
    м.цвет(с)
    свой = next(cid for cid, d in с.мир["справочники"].items() if d["name"] == "Цвет")
    assert sorted(v["name"] for v in с.мир["справочники"][свой]["значения"]) == sorted(colours.КАНОН)
    assert any(a["name"] == "Цвет" and a["type"] == "customentity" for a in с.мир["поля"])

    чужой = склад(м)
    чужой.мир["поля"].append({"id": "x1", "name": "Оттенок", "type": "customentity",
                              "meta": {"href": f"{А}/entity/product/metadata/attributes/x1"},
                              "customEntityMeta": {"href": f"{А}/context/companysettings/metadata/customEntities/col"}})
    with pytest.raises(SystemExit) as e:
        м.цвет(чужой)
    assert "Оттенок" in str(e.value) and чужой.мир["записи"] == []


def test_the_conclusion_field_is_added_as_a_link(м, capsys):
    """«Заключение» — новое поле товара типа «ссылка»; повторный запуск его не дублирует."""
    с = склад(м)
    с.мир["справочники"]["rem"] = {"name": "Ремонт статус", "значения": [
        {"id": "s1", "name": "Запечатанный (новый)", "meta": {"href": "x"}}]}
    с.мир["поля"].append({"id": "st", "name": "Статус", "type": "customentity",
                          "meta": {"href": f"{А}/entity/product/metadata/attributes/st"},
                          "customEntityMeta": {"href": f"{А}/context/companysettings/metadata/customEntities/rem"}})
    for п in м.ПРОЦЕНТЫ:
        с.мир["справочники"]["akb"]["значения"].append({"id": п, "name": п, "meta": {"href": п}})
    м.добавить(с)
    заключение = [a for a in с.мир["поля"] if a["name"] == "Заключение"]
    assert len(заключение) == 1 and заключение[0]["type"] == "link"
    assert not any(a["name"] == "Цвет" and a["type"] == "string" and a is not с.мир["поля"][1]
                   for a in с.мир["поля"]), "строковое «Цвет» шаг add больше не заводит"
    записей = len(с.мир["записи"])
    м.добавить(с)
    assert len([a for a in с.мир["поля"] if a["name"] == "Заключение"]) == 1
    assert len(с.мир["записи"]) == записей
