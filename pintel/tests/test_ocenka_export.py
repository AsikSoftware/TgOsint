# -*- coding: utf-8 -*-
"""Экспорт сделки в Оценку: поля ровно те, что ждёт её код.

Разобрано по исходникам Оценки, а не на глаз: карточка печатает `device.sim` как есть,
открытие сделки берёт `device.video_phone` без проверки на пусто, а статус зависит от
«Ремонт статус» и наличия автоцены.

Саму вставку делает бот (в базу Оценки с точки хода нет) — она проверяется в
test_kiosk_deal_core.py, а отправка посылки боту — в test_ocenka_tg.py.
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


def test_readiness_checks_only_what_the_point_can_know():
    """Видео здесь не требуем: приложение его не видит — медиа принимает бот, и он же
    не даёт создать сделку без видео. Иначе на точке пришлось бы угадывать."""
    данные = {"модель": "iPhone 14 Pro", "память": 256, "имя_клиента": "Зама",
              "телефон_клиента": "+77058837953", "imei": "350585886690250"}
    ocenka.проверить_готовность(данные)                 # без видео — проходит
    assert ocenka.посылка(данные, "7KQ4M")["код"] == "7KQ4M"


def test_export_names_everything_missing_at_once():
    """Сотруднику нужен полный список недостающего, а не по одному за отправку."""
    with pytest.raises(ocenka.ОшибкаЭкспорта) as e:
        ocenka.проверить_готовность({})
    текст = str(e.value)
    for слово in ("модель", "объём памяти", "имя и телефон клиента", "IMEI"):
        assert слово in текст, текст


@pytest.mark.parametrize("отчёт,ждём", [
    ({"sickw": {"в_чёрном_списке": True}}, ["ЧЁРНЫЙ СПИСОК"]),
    ({"правовой": {"найти_iphone": "включён"}}, ["Найти iPhone вкл."]),
    ({"sickw": {"fmi_включён": True}}, ["Найти iPhone вкл."]),
    ({"правовой": {"mdm": True}}, ["MDM"]),
    ({"правовой": {"найти_iphone": "выключен", "mdm": False}}, []),
    ({}, []),
])
def test_locks_are_listed_once_for_comment_and_card(отчёт, ждём):
    """Один список замков на два места: комментарий сделки и карточка, которую оценщик
    подтверждает. Разъедутся — он подтвердит не то, что уйдёт в Оценку."""
    assert ocenka.замки(отчёт) == ждём


def test_grader_comment_is_short_and_names_the_locks():
    rep = {"детали_вердикт": {"итог": "родные"}, "apple_история_источник": "проверка компонентов (iOS 26)",
           "правовой": {"найти_iphone": "включён"}, "батарея": {"здоровье_%": 86, "циклы": 320}}
    txt = ocenka.комментарий_оценщика(rep, сверка="", откуда="Киоск №4 от 2026-10-27")
    assert "Детали: родные" in txt and "Найти iPhone вкл." in txt
    assert "86%, 320 циклов" in txt and txt.endswith("Киоск №4 от 2026-10-27")


# ---------------------------------------------------------------- медиа через бота Оценки

def test_media_code_is_short_and_unmistakable():
    """Код диктуют голосом и набирают руками — в нём не должно быть похожих знаков."""
    from pintel_core.external import ocenka_media
    коды = {ocenka_media.новый_код() for _ in range(200)}
    assert len(коды) > 190                                  # повторы практически исключены
    for к in коды:
        # ни одной пары, которую путают на слух и на вид: O/0, I/1, B/8, S/5, Z/2
        assert len(к) == 6 and not (set(к) & set("OI10B8SZ2"))


def test_media_link_opens_the_bot_with_the_command():
    """Ссылка — это готовая команда боту: сотрудник ничего не набирает."""
    from pintel_core.external import ocenka_media
    assert ocenka_media.ссылка("pintel_bot", "AB12") == "https://t.me/pintel_bot?start=pAB12"
    for запись in ("@pintel_bot", "https://t.me/pintel_bot", "pintel_bot/"):
        assert ocenka_media.ссылка(запись, "AB12").endswith("/pintel_bot?start=pAB12"), запись


