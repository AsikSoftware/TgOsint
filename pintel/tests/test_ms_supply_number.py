# -*- coding: utf-8 -*-
"""Занятый номер приёмки: документ не бросаем, а проводим под свободным номером.

21.11.2026, сделка 17476: приёмка создалась, а провести МойСклад не дал — «нарушено
ограничение уникальности параметра 'name'». Живая приёмка с таким номером была ровно одна,
наша: номер держала удалённая. Сотрудник нажимал кнопку дважды, оба раза тот же отказ.
"""
import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ФАЙЛ = os.path.join(HERE, "..", "deploy", "оценка_бот", "ms_supply_number.py")

спец = importlib.util.spec_from_file_location("ms_supply_number", ФАЙЛ)
м = importlib.util.module_from_spec(спец)
спец.loader.exec_module(м)

ОТКАЗ = ('HTTP 412 PUT https://api.moysklad.ru/api/remap/1.2/entity/supply/c51e26a2\n'
         '{\n  "errors": [\n    {\n      "error": "Ошибка сохранения объекта: нарушено '
         'ограничение уникальности параметра \'name\'",\n      "code": 3006,\n'
         '      "parameter": "name"\n    }\n  ]\n}')


def склад(занятые):
    """Подменный МойСклад: знает только занятые номера. → (запросить, журнал)."""
    журнал = []

    def запросить(метод, путь, params=None):
        журнал.append((метод, путь, dict(params or {})))
        if (params or {}).get("filter", "").startswith("name="):
            номер = params["filter"].split("=", 1)[1]
            return {"rows": [{"name": номер}] if номер in занятые else []}
        строки = [{"name": н} for н in sorted(занятые, reverse=True)]
        return {"rows": строки[:int((params or {}).get("limit") or 50)]}

    return запросить, журнал


def test_the_refusal_about_a_taken_number_is_recognised():
    """Отказ про номер отличаем от любого другого: смена номера чинит только его."""
    assert м.это_занятый_номер(ОТКАЗ)
    assert not м.это_занятый_номер("HTTP 403 Тарифное ограничение: лимит доп. полей")
    assert not м.это_занятый_номер("HTTP 412 позиция без цены")
    assert not м.это_занятый_номер("")


def test_the_next_free_number_is_taken_after_the_last_one():
    """Считаем от самого большого живого номера, а не от номера застрявшего документа:
    пока он висел, счётчик ушёл вперёд (у нас — на 80880, созданный руками)."""
    запросить, журнал = склад({"80879", "80880"})
    assert м.свободный_номер(запросить) == "80881"
    assert журнал[0][0] == "GET", "номер подбираем чтением, записи здесь не бывает"


def test_busy_numbers_are_skipped_one_by_one():
    """Следующий тоже занят — идём дальше, а не сдаёмся."""
    запросить, _ = склад({"80879", "80880", "80881", "80882"})
    assert м.свободный_номер(запросить) == "80883"


def test_an_empty_warehouse_starts_from_one():
    """Приёмок нет вовсе — начинаем с первого номера, а не падаем на пустом списке."""
    запросить, _ = склад(set())
    assert м.свободный_номер(запросить) == "1"


def test_it_gives_up_loudly_rather_than_looping_forever():
    """Если занято всё подряд — говорим словами, а не крутимся в МойСкладе без конца."""
    занятые = {str(n) for n in range(80879, 80879 + м.ПОПЫТОК + 5)}
    запросить, _ = склад(занятые)
    with pytest.raises(RuntimeError) as беда:
        м.свободный_номер(запросить, начать_с=80879)
    assert "свободный номер" in str(беда.value)
