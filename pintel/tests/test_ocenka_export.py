# -*- coding: utf-8 -*-
"""Экспорт сделки в Оценку: поля ровно те, что ждёт её код.

Разобрано по исходникам Оценки, а не на глаз: карточка печатает `device.sim` как есть,
открытие сделки берёт `device.video_phone` без проверки на пусто, а статус зависит от
«Ремонт статус» и наличия автоцены.
"""
import pytest

from pintel_core.external import ocenka


@pytest.mark.parametrize("паспорт,ждём", [
    ({"esim_only": True}, "E-sim"),
    ({"esim": True}, "Dual sim"),
    ({"imei2": "350585881725184"}, "Dual sim"),
    ({"sim": "SIM не вставлена", "sim_в_лотке": False}, "Стандарт"),
    ({}, "Прочее"),
])
def test_sim_uses_ocenka_vocabulary(паспорт, ждём):
    """В карточке было «SIM-слот: None» — пустое поле она печатает как есть.
    Значения берём её же: Dual sim / E-sim / Прочее / Стандарт."""
    assert ocenka.sim_для_оценки(паспорт) == ждём
    assert ocenka.sim_для_оценки(паспорт) in ocenka.SIM_ВАРИАНТЫ


@pytest.mark.parametrize("вход,ждём", [
    ("Pro A2891", None),                 # ровно то, что уехало в сделку 7093
    ("A2891", None),
    ("iPhone 14 Pro", None),
    ("Pro Max", None),
    ("чёрный космос", "чёрный космос"),
    ("Space Black", "Space Black"),
    ("", None),
    (None, None),
])
def test_colour_rejects_model_leftovers(вход, ждём):
    """Лучше пустой цвет, чем кусок описания модели в поле «Цвет»."""
    assert ocenka.цвет_для_оценки(вход) == ждём


@pytest.mark.parametrize("итог,ждём", [
    ("родные", "Не был в ремонте"),
    ("замена", "Ранее был в ремонте"),
    ("ремонт", "Ранее был в ремонте"),
    ("кабель", None),
    ("неполно", None),
    (None, None),
])
def test_repair_status_matches_their_wording(итог, ждём):
    """«Не был в ремонте» — не просто текст: по нему Оценка решает, показывать ли цену
    клиенту сразу. Неподтверждённое состояние не выдаём за «не был»."""
    assert ocenka.статус_ремонта(итог) == ждём


def test_export_refuses_without_video():
    """Открытие сделки у Оценки делает InputMediaVideo(media=device.video_phone) без
    проверки: сделка без видео не открывается вовсе. Честный отказ на точке лучше."""
    данные = {"модель": "iPhone 14 Pro", "память": 256, "имя_клиента": "Зама",
              "телефон_клиента": "+77058837953", "imei": "350585886690250"}
    with pytest.raises(ocenka.ОшибкаЭкспорта) as e:
        ocenka.проверить_готовность(данные)
    assert "видео" in str(e.value)
    данные["видео"] = "BAACAgIAAx..."
    ocenka.проверить_готовность(данные)                 # с видео — проходит


def test_export_names_everything_missing_at_once():
    """Сотруднику нужен полный список недостающего, а не по одному за отправку."""
    with pytest.raises(ocenka.ОшибкаЭкспорта) as e:
        ocenka.проверить_готовность({})
    текст = str(e.value)
    for слово in ("модель", "объём памяти", "имя и телефон клиента", "видео", "IMEI"):
        assert слово in текст, текст


def test_grader_comment_is_short_and_names_the_locks():
    rep = {"детали_вердикт": {"итог": "родные"}, "apple_история_источник": "проверка компонентов (iOS 26)",
           "правовой": {"найти_iphone": "включён"}, "батарея": {"здоровье_%": 86, "циклы": 320}}
    txt = ocenka.комментарий_оценщика(rep, сверка="", откуда="Киоск №4 от 2026-10-27")
    assert "Детали: родные" in txt and "Найти iPhone вкл." in txt
    assert "86%, 320 циклов" in txt and txt.endswith("Киоск №4 от 2026-10-27")
