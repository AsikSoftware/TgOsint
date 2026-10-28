# -*- coding: utf-8 -*-
"""Серверная часть: что бот делает с посылкой из программы.

Код лежит в deploy/оценка_бот/ и ставится на сервер руками, поэтому проверяем его здесь —
до установки. Чистая часть специально вынесена отдельно от обработчика: в ней нет ни
aiogram, ни базы, и её можно прогнать как обычный модуль.
"""
import importlib.util
import json
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ЯДРО = os.path.join(HERE, "..", "deploy", "оценка_бот", "kiosk_core.py")


@pytest.fixture(scope="module")
def ядро():
    spec = importlib.util.spec_from_file_location("kiosk_core", ЯДРО)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def посылка(**замены):
    п = {"версия": 1, "код": "7KQ4M", "точка": "16/38",
         "клиент": {"имя": "Зама", "телефон": "+77058837953"},
         "imei": ["350585886690250", "350585881725184"], "imei_проверен": True,
         "сделка": {"model": "iPhone 14 Pro", "code_name": "iPhone15,2", "ddr": 256,
                    "akb": "86%", "akb_exact": 86, "color": "чёрный космос", "sim": "Dual sim",
                    "box": True, "cord": False, "panic_full": False,
                    "phone_status": "Не был в ремонте", "price_grade_auto": 250000,
                    "comment": "скол", "comment_ocenka": "Детали: родные"}}
    п.update(замены)
    return п


def test_payload_of_another_version_is_refused(ядро):
    """Программу и обработчик обновляют в разное время. Молча положить в сделку поля,
    которых бот не понимает, хуже, чем отказать с просьбой обновиться."""
    with pytest.raises(ядро.ОшибкаПосылки) as e:
        ядро.разобрать(json.dumps(посылка(версия=2)))
    assert "обновите" in str(e.value)
    for мусор in ("не json вовсе", "[1,2,3]", json.dumps({"версия": 1, "код": "ab"}),
                  json.dumps({"версия": 1, "код": "7KQ4M"})):
        with pytest.raises(ядро.ОшибкаПосылки):
            ядро.разобрать(мусор)


def test_payload_reads_from_bytes(ядро):
    """Файл приходит из Telegram байтами — разбирать его должен он же, а не вызывающий."""
    п = ядро.разобрать(json.dumps(посылка(), ensure_ascii=False).encode("utf-8"))
    assert п["код"] == "7KQ4M"


def test_video_is_required_before_the_deal_is_created(ядро):
    """Карточку Оценка открывает через InputMediaVideo(video_phone) без проверки на пусто:
    сделка без видео не открывается вовсе. Знает об этом только бот — он видит медиа."""
    нет = ядро.проверить(посылка(), {"video": None, "photos": None, "shop_id": 7})
    assert нет and "видео" in нет[0]
    assert ядро.проверить(посылка(), {"video": "BAACAgIAAx0", "shop_id": 7}) == []


@pytest.mark.parametrize("staff_id,shop_id,ждём", [
    (2, 7, 7),          # продавец закреплён за точкой — она и есть точка сделки
    (2, None, None),    # продавец без точки: догадываться нельзя, спросим
    (1, 7, None),       # администратор ездит по точкам — выбирает сам после медиа
    (1, None, None),
    (3, 7, None),       # клиент вообще не оценщик
])
def test_shop_comes_from_who_sent_the_media(ядро, staff_id, shop_id, ждём):
    assert ядро.точка_сотрудника(staff_id, shop_id) == ждём


def test_deal_without_a_shop_is_refused(ядро):
    """Сделка без магазина теряется в отчётах — лучше не создать её вовсе."""
    нет = ядро.проверить(посылка(), {"video": "v", "shop_id": None})
    assert нет == ["точка: выберите её в боте"]


def test_check_names_everything_missing_at_once(ядро):
    """Оценщику нужен полный список, а не по одной причине на нажатие."""
    пусто = посылка(клиент={}, imei=[], сделка={})
    нет = " ".join(ядро.проверить(пусто, {}))
    for слово in ("видео", "модель", "объём памяти", "имя и телефон клиента", "IMEI"):
        assert слово in нет


def test_only_known_columns_reach_the_table(ядро):
    """Из посылки в devices попадает только разрешённое: имя колонки никогда не склеивается
    из чужого текста, даже если в файле окажется что-то лишнее."""
    п = посылка()
    п["сделка"]["price_buy"] = 1                      # не наше дело — цена выкупа
    п["сделка"]["status_id) = 1; DROP TABLE devices --"] = 1
    поля = ядро.колонки(п)
    assert set(поля) == set(ядро.КОЛОНКИ)
    sql = ядро.sql_devices(поля)
    assert "DROP" not in sql and "price_buy" not in sql
    assert sql.count("INSERT INTO devices") == 1 and "RETURNING id" in sql
    for k in поля:
        assert f":{k}" in sql                          # значения — только через bind


def test_sql_refuses_a_column_we_do_not_know(ядро):
    with pytest.raises(ядро.ОшибкаПосылки) as e:
        ядро.sql_devices({"model": "x", "наше_поле": 1})
    assert "наше_поле" in str(e.value)


def test_sim_falls_back_to_her_vocabulary(ядро):
    """«SIM-слот: None» в карточке уже видели. Чужое значение её карточка печатает как есть."""
    п = посылка()
    п["сделка"]["sim"] = "две симки"
    assert ядро.колонки(п)["sim"] == "Прочее"
    assert ядро.колонки(посылка())["sim"] == "Dual sim"


def test_long_text_is_cut_to_her_column_widths(ядро):
    """comment у неё String(500): длинный комментарий иначе рвёт вставку целиком."""
    п = посылка()
    п["сделка"]["comment"] = "ц" * 900
    п["сделка"]["model"] = "i" * 90
    поля = ядро.колонки(п)
    assert len(поля["comment"]) == 500 and len(поля["model"]) == 50


def test_status_matches_her_own_rule(ядро):
    """У неё: «Не был в ремонте» и есть автоцена → status_id 1 (клиент сразу видит цену),
    иначе 2 — сделка уходит админу на ручную оценку."""
    assert ядро.статус_id({"phone_status": "Не был в ремонте", "price_grade_auto": 250000}) == 1
    assert ядро.статус_id({"phone_status": "Не был в ремонте", "price_grade_auto": None}) == 2
    assert ядро.статус_id({"phone_status": "Ранее был в ремонте", "price_grade_auto": 1}) == 2
    assert ядро.статус_id({}) == 2


def test_imeis_keep_the_first_one_first(ядро):
    """`first` у неё помечает основной IMEI — по нему ищут сделку."""
    assert ядро.имейки(посылка(imei=["350585886690250", "350585886690250", " 35058588172518 "])) == [
        ("350585886690250", True), ("35058588172518", False)]
    assert ядро.имейки(посылка(imei=[])) == []


def test_numbers_survive_json(ядро):
    """JSON отдаёт 256 и 256.0 одинаково охотно, а ddr у неё Integer."""
    п = посылка()
    п["сделка"].update({"ddr": 256.0, "akb_exact": "86", "price_grade_auto": "250 000"})
    поля = ядро.колонки(п)
    assert поля["ddr"] == 256 and поля["akb_exact"] == 86 and поля["price_grade_auto"] == 250000


def test_handoff_doc_checksums_match_the_files():
    """В задании серверному чату лежат sha256 файлов обработчика: по ним сверяют то, что
    перенесли руками, когда с сервера не достать до GitHub. Файл поменяли, сумму забыли —
    и сверка либо врёт, либо пугает зря."""
    import hashlib
    import re
    папка = os.path.join(HERE, "..", "deploy", "оценка_бот")
    with open(os.path.join(папка, "ЗАДАНИЕ_серверу.md"), encoding="utf-8") as f:
        задание = f.read()
    названо = dict(re.findall(r"\| `([\w.]+)` \|[^|]*\| `([0-9a-f]{64})`", задание))
    assert названо, "в задании пропала таблица с суммами"
    for имя, сумма in названо.items():
        with open(os.path.join(папка, имя), "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest() == сумма, f"{имя}: сумма в задании устарела"
