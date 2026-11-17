# -*- coding: utf-8 -*-
"""Список обязательного: без этих величин сделку не пускаем.

Решение владельца 17.11.2026: «надо составить список вещей, которые надо прочитать, и без них
не пускать». Список составлен по боевым оценкам — каждый его пункт читается в 100% случаев
(81 проверка за месяц, 20 последних на нынешней сборке), поэтому запрет не останавливает
работу: он срабатывает там, где и правда сломалось — кабель, разъём, служба Apple.
"""
import os

import pytest

from pintel_core import reference
from pintel_core.analysis import report as report_mod
from pintel_core.analysis import обязательное as обяз
from pintel_core.devicelink import snapshot

HERE = os.path.dirname(os.path.abspath(__file__))


def _отчёт(архив="эталон_iPhone-14-Pro_iOS26.5.zip"):
    snap, _ = reference.load_bundle(os.path.join(HERE, "fixtures_real", "эталоны", архив),
                                    loads=snapshot.loads)
    return report_mod.build(snap)


def test_a_fully_read_phone_passes():
    """Телефон, прочитанный по кабелю целиком, проходит: запрет не мешает обычной работе."""
    rep = _отчёт()
    assert обяз.не_прочитано(rep) == [], обяз.словами(rep)
    assert обяз.всё_прочитано(rep) and обяз.почему_не_пустить(rep) == ""
    assert rep["обязательное_не_прочитано"] == []


@pytest.mark.parametrize("куда, что, название", [
    (("паспорт", "модель"), None, "модель телефона"),
    (("паспорт", "модель"), "iPhone19,9 — модель не в справочнике", "модель телефона"),
    (("паспорт", "imei"), "", "IMEI"),
    (("паспорт", "imei"), "35058588669", "IMEI"),
    (("паспорт", "серийник"), None, "серийный номер"),
    (("память", "объём_гб"), None, "объём памяти"),
    (("батарея", "здоровье_%"), None, "здоровье батареи"),
    (("правовой", "найти_iphone"), "не определился", "«Найти iPhone»"),
    (("правовой", "активация"), "", "состояние активации"),
    (("детали_вердикт", "итог"), "", "вердикт по деталям"),
])
def test_each_missing_item_blocks_the_deal_and_is_named(куда, что, название):
    """Нет любой из этих величин — сделку не пускаем, и сотрудник видит, какой именно."""
    rep = _отчёт()
    rep[куда[0]][куда[1]] = что
    нет = обяз.не_прочитано(rep)
    assert [н for _к, н, _з in нет] == [название], нет
    assert название in обяз.словами(rep)
    текст = обяз.почему_не_пустить(rep)
    assert название in текст and "заново" in текст and "кабель" in текст


def test_the_report_carries_the_list_and_counts_it_as_an_incomplete_check():
    """Непрочитанное обязательное едет в отчёте отдельным списком и в «не прочиталось»:
    по такой проверке автоцены не бывает — сомнение не бывает зелёным."""
    import copy
    from pintel_core.analysis import report as rm
    snap, _ = reference.load_bundle(
        os.path.join(HERE, "fixtures_real", "эталоны", "эталон_iPhone-14-Pro_iOS26.5.zip"),
        loads=snapshot.loads)
    битый = copy.deepcopy(snap)
    битый["nodes"] = {}                       # детали и батарея читаются из узлов
    битый["root"] = {k: v for k, v in (битый.get("root") or {}).items()
                     if k not in ("InternationalMobileEquipmentIdentity",)}
    rep = rm.build(битый)
    ключи = [x["ключ"] for x in rep["обязательное_не_прочитано"]]
    assert "imei" in ключи, ключи
    assert any("не прочитано обязательное" in x for x in rep["не_прочиталось"])


def test_a_sealed_box_is_not_judged_by_the_cable_list():
    """Запечатанный аппарат читают не кабелем, а по базе IMEI: ни процента батареи, ни
    вердикта по деталям у него не бывает, и запрет к нему не применяется."""
    from pintel_core.analysis import sealed as sealed_mod
    rep = sealed_mod.build({"модель": "iPhone 17 Pro", "объём_гб": 256, "цвет": "ORANGE"},
                           ["350585886690250"])
    assert rep.get("запечатанный") is True
    assert обяз.не_прочитано(rep) == [] and обяз.желательного_нет(rep) == []


def test_what_depends_on_our_build_does_not_stop_the_shop():
    """panic full читает модуль нашей сборки (однажды он отвалился из-за недостающих
    метаданных pyimg4). Останавливать точку из-за своей же ошибки нельзя — но и ставить цену
    молча тоже: сделка создаётся, автоцены нет, оценивает человек."""
    rep = _отчёт()
    assert rep.get("паника") in ({}, None) or not rep["паника"].get("проверено")
    assert обяз.не_прочитано(rep) == [], "panic full не должен запрещать сделку"
    assert [н for _к, н, _з in обяз.желательного_нет(rep)] == ["ошибка Panic full"]
    assert any("Panic full" in x for x in rep["не_прочиталось"]), rep["не_прочиталось"]

    rep["паника"] = {"проверено": True, "panic_full": False}
    assert обяз.желательного_нет(rep) == []


def test_the_parcel_refuses_a_used_phone_without_the_mandatory_values():
    """Последний заслон: даже если касса старой сборки, посылку без обязательного не собрать."""
    from pintel_core.external import ocenka
    данные = {"модель": "iPhone 14 Pro", "память": 256, "акб": 86, "статус_ремонта": ocenka.СТАТУС_ЧИСТЫЙ,
              "имя_клиента": "Зама", "телефон_клиента": "+77058837953", "imei": "350585886690250"}
    ocenka.проверить_готовность(данные)                        # полное — проходит

    for поле, слово in (("акб", "здоровье батареи"), ("статус_ремонта", "вердикт по деталям")):
        with pytest.raises(ocenka.ОшибкаЭкспорта) as e:
            ocenka.проверить_готовность({**данные, поле: None})
        assert слово in str(e.value)

    # а запечатанный проходит без них: его читают не кабелем
    ocenka.проверить_готовность({**данные, "акб": None, "статус_ремонта": ocenka.СТАТУС_НОВЫЙ,
                                 "состояние": "новый"})
