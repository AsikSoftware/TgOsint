# -*- coding: utf-8 -*-
"""Сигналы по экрану: когда они вправе сказать «меняли», а когда обязаны промолчать.

Оба сигнала ложно срабатывали на iPhone 11 и отказывали в сделке на КАЖДОМ таком
аппарате — при том что Apple в «Деталях и обслуживании» про дисплей не писала ничего.
Разобрано на двух живых iPhone 11 из одного прогона: значения у них совпали побайтово,
а так не бывает, если экран правда меняли.
"""
from pintel_core.analysis import parts as parts_mod
from pintel_core.analysis.capabilities import сравнимая_калибровка_экрана
from pintel_core.analysis.pairing import coverglass, screen_calibration


def _подсветка(пары):
    (a1, b1), (a2, b2), (a3, b3) = пары
    return {"backlight-calibration-parameters": {
        "lMinPanel": a1, "lMinProduct": b1, "lMidPanel": a2,
        "lMidProduct": b2, "lMaxPanel": a3, "lMaxProduct": b3}}


def test_calibration_still_detects_a_mismatch():
    """Сам сигнал не сломан — на моделях, где величины сравнимы, он работает."""
    сошлось = _подсветка([(262144, 262144), (10158080, 10158080), (78643200, 78643200)])
    assert screen_calibration(сошлось) is True
    assert screen_calibration(_подсветка([(262144, 1), (10158080, 10158080), (78643200, 78643200)])) is False


def test_iphone_11_calibration_is_not_a_verdict():
    """iPhone 11 (iPhone12,x) хранит калибровку иначе: там это не вывод, а молчание."""
    assert сравнимая_калибровка_экрана("iPhone12,1") is False      # 11
    assert сравнимая_калибровка_экрана("iPhone12,3") is False      # 11 Pro
    assert сравнимая_калибровка_экрана("iPhone13,2") is True       # 12
    assert сравнимая_калибровка_экрана("iPhone15,2") is True       # 14 Pro


def test_coverglass_is_silent_when_the_field_cannot_hold_the_serial():
    """Поле панели — список через «+». Если в нём нет сегмента такой длины, как серийник
    стекла, вхождение невозможно в принципе: это «не знаем», а не «не совпадает»."""
    стекло = "A" * 44
    узкое = {"coverglass-serial-number": стекло,
             "raw-panel-serial-number": "+".join(["B" * 17] * 7)}       # как на iPhone 11
    assert coverglass(узкое) is None


def test_coverglass_still_catches_a_foreign_glass():
    """Где сегмент нужной длины есть — сигнал по-прежнему отличает чужое стекло от своего."""
    стекло = "A" * 44
    своё = {"coverglass-serial-number": стекло,
            "raw-panel-serial-number": "X" * 17 + "+" + стекло + "+" + "Y" * 20}
    чужое = {"coverglass-serial-number": стекло,
             "raw-panel-serial-number": "X" * 17 + "+" + "Z" * 44 + "+" + "Y" * 20}
    assert coverglass(своё) is True and coverglass(чужое) is False


def test_the_refusal_names_the_channel_not_just_apple():
    """Отказ обязан говорить, кто именно нашёл: слова Apple и наша догадка по кабелю —
    разной силы, и оценщик сверяет их с экраном телефона."""
    по_кабелю = {"итог": "замена", "детали": [
        {"деталь": "Аккумулятор", "статус": "bad", "почему": "ёмкость выше заводской",
         "источник": "батарея (кабель)"}]}
    по_apple = {"итог": "замена", "детали": [
        {"деталь": "Экран", "статус": "bad", "почему": "деталь неизвестного происхождения",
         "источник": "журнал Apple"}]}
    assert parts_mod.причина_отказа(по_кабелю).startswith("по кабелю: Аккумулятор")
    assert parts_mod.причина_отказа(по_apple).startswith("по данным Apple: Экран")
    assert parts_mod.причина_отказа({"итог": "кабель"}) == "Apple не подтвердила подлинность деталей"


def test_the_worst_part_is_the_one_named():
    """Деталей может быть несколько — называем ту, из-за которой отказ."""
    в = {"итог": "замена", "детали": [
        {"деталь": "Корпус", "статус": "repaired", "почему": "меняли", "источник": "журнал Apple"},
        {"деталь": "Экран", "статус": "bad", "почему": "неизвестная", "источник": "журнал Apple"}]}
    assert "Экран" in parts_mod.причина_отказа(в)
