# -*- coding: utf-8 -*-
"""Прошлая проверка того же телефона: когда её берут, когда не берут и что об этом видно.

Тот же аппарат оказывается у кассы второй раз за смену постоянно: сделку отменили,
программа перезапустилась, клиент ушёл подумать и вернулся. Читать телефон минуты заново
ради того же ответа незачем — но и прикрываться старым отчётом молча нельзя. Здесь
проверяется ровно эта граница.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta

import pytest

from pintel_core import previous
from pintel_core.external import ocenka

ПАСПОРТ = {"модель": "iPhone 14 Pro", "код_модели": "iPhone15,2", "серийник": "F2LW104QPN",
           "udid": "00008120-001A2C3D4E5F6061", "imei": "350585886690250"}
ПРАВОВОЙ = {"найти_iphone": "выключен", "активация": "Activated", "пароль": False}


def _отчёт(**замены):
    rep = {"паспорт": dict(ПАСПОРТ), "правовой": dict(ПРАВОВОЙ), "итог": {"вердикт": "ХОРОШИЙ"}}
    rep.update(замены)
    return rep


def _положить(папка, когда: datetime, отчёт: dict, серийник=None):
    """Папка проверки ровно такая, какую складывает киоск: «время_серийник/report.json»."""
    серийник = серийник or отчёт["паспорт"]["udid"]
    путь = os.path.join(папка, f"{когда:%Y%m%d_%H%M%S}_{серийник[:12]}")
    os.makedirs(путь, exist_ok=True)
    with open(os.path.join(путь, "report.json"), "w", encoding="utf-8") as f:
        json.dump(отчёт, f, ensure_ascii=False)
    with open(os.path.join(путь, "snapshot.json"), "w", encoding="utf-8") as f:
        json.dump({"root": {"SerialNumber": отчёт["паспорт"]["серийник"]}}, f, ensure_ascii=False)
    return путь


def test_the_freshest_check_of_the_same_phone_is_the_one_taken(tmp_path):
    """Берём самую свежую проверку этого же телефона — и только если она в окне."""
    сейчас = datetime(2026, 11, 3, 14, 0, 0)
    папка = str(tmp_path / "out")
    _положить(папка, сейчас - timedelta(hours=5), _отчёт(итог={"вердикт": "СТАРАЯ"}))
    свежая = _положить(папка, сейчас - timedelta(minutes=40), _отчёт())
    находка = previous.найти(папка, ПАСПОРТ["udid"], 1, сейчас)
    assert находка and находка["путь"] == свежая
    assert находка["возраст_мин"] == 40 and "40 мин назад" in находка["словами"]
    assert находка["отчёт"]["итог"]["вердикт"] == "ХОРОШИЙ"


def test_an_old_check_is_not_taken_at_all(tmp_path):
    """Отчёт старше окна не берём: он уже не про тот телефон, что лежит на столе.

    Аппарат успевает всё: разбиться, сменить владельца, получить другой экран. Ошибка в
    эту сторону стоит выкупа, а не минуты чтения."""
    сейчас = datetime(2026, 11, 3, 14, 0, 0)
    папка = str(tmp_path / "out")
    _положить(папка, сейчас - timedelta(days=2), _отчёт())
    assert previous.найти(папка, ПАСПОРТ["udid"], 1, сейчас) is None
    # окно пошире — та же проверка уже годится; окно «0» выключает поиск совсем
    assert previous.найти(папка, ПАСПОРТ["udid"], 3, сейчас)
    assert previous.найти(папка, ПАСПОРТ["udid"], 0, сейчас) is None


def test_a_check_of_another_phone_is_never_taken(tmp_path):
    """Имя папки — это первые 12 знаков UDID, и совпадения по ним мало.

    Иначе чужой отчёт с похожим началом UDID уехал бы в сделку как свой: модель, память и
    батарея — чужие, а оценщик читает их как проверку аппарата клиента."""
    сейчас = datetime(2026, 11, 3, 14, 0, 0)
    папка = str(tmp_path / "out")
    чужой = _отчёт(паспорт={**ПАСПОРТ, "udid": "00008120-001A2C3D-ДРУГОЙ",
                            "серийник": "ДРУГОЙ"})
    # папку называем НАШИМ префиксом — по имени не отличить, отличает содержимое отчёта
    _положить(папка, сейчас - timedelta(minutes=5), чужой, серийник=ПАСПОРТ["udid"])
    assert previous.найти(папка, ПАСПОРТ["udid"], 1, сейчас) is None
    assert previous.тот_же(_отчёт(), ПАСПОРТ["udid"]) is True
    assert previous.тот_же(_отчёт(), ПАСПОРТ["серийник"]) is True      # старые отчёты без udid
    assert previous.тот_же(_отчёт(), "") is False


def test_a_check_from_the_future_is_ignored(tmp_path):
    """Часы на точке переводят руками. Отчёт «из будущего» иначе остался бы свежим навсегда."""
    сейчас = datetime(2026, 11, 3, 14, 0, 0)
    папка = str(tmp_path / "out")
    _положить(папка, сейчас + timedelta(hours=2), _отчёт())
    assert previous.найти(папка, ПАСПОРТ["udid"], 1, сейчас) is None


def test_a_broken_folder_does_not_stop_the_point(tmp_path):
    """Битый файл — не повод падать: просто читаем телефон заново."""
    сейчас = datetime(2026, 11, 3, 14, 0, 0)
    папка = str(tmp_path / "out")
    путь = os.path.join(папка, f"{сейчас - timedelta(minutes=3):%Y%m%d_%H%M%S}_"
                               f"{ПАСПОРТ['udid'][:12]}")
    os.makedirs(путь)
    with open(os.path.join(путь, "report.json"), "w", encoding="utf-8") as f:
        f.write("{это не json")
    assert previous.найти(папка, ПАСПОРТ["udid"], 1, сейчас) is None


def test_the_reused_check_says_so_in_the_report_and_in_the_card():
    """Отчёт, взятый прошлым, обязан сам про это говорить — и на экране, и у оценщика.

    Оценщик читает карточку как результат проверки. Если проверку не повторяли, он должен
    видеть это словами, а не догадываться по времени создания сделки."""
    сейчас = datetime(2026, 11, 3, 14, 0, 0)
    находка = {"когда": сейчас - timedelta(minutes=40), "возраст_мин": 40,
               "словами": previous.словами(сейчас - timedelta(minutes=40), сейчас),
               "путь": "/x/out/20261103_132000_00008120-001"}
    rep = previous.отметить(_отчёт(), находка)
    отметка = rep["повторная_проверка"]
    assert отметка["возраст_мин"] == 40 and отметка["когда"].startswith("2026-11-03T13:20")
    assert "40 мин назад" in отметка["словами"] and отметка["папка"].endswith("00008120-001")
    отметка["сверка"] = "сошлась"
    карточка = ocenka.комментарий_оценщика(rep, состояние="Б/у в нормальном состоянии")
    assert "Кабелем не перечитывали" in карточка and "40 мин назад" in карточка
    # не сверили — это тоже едет в карточку: оценщик видит, насколько проверка подтверждена
    rep["повторная_проверка"]["сверка"] = "не сверили: телефон не ответил"
    assert "не сверили" in ocenka.комментарий_оценщика(rep)


def test_the_words_are_readable_for_a_human():
    """Время проверки сотрудник читает на бегу: «сегодня в 14:05, 40 минут назад»."""
    сейчас = datetime(2026, 11, 3, 14, 45, 0)
    assert previous.словами(сейчас - timedelta(minutes=5), сейчас).startswith("сегодня в 14:40")
    assert "1 ч 30 мин назад" in previous.словами(сейчас - timedelta(minutes=90), сейчас)
    вчера = previous.словами(сейчас - timedelta(days=1, hours=1), сейчас)
    assert вчера.startswith("02.11") and "дн назад" in вчера


# ---------------------------------------------------------------- сверка с живым телефоном

class ФейкЗамок:
    """Подменный lockdown: отдаёт ровно то, что читается мгновенно — корень и домен fmip."""

    def __init__(self, root, fmip=None, падать=False):
        self.root, self.fmip, self.падать = root, fmip or {}, падать
        self.чтений = 0

    async def get_value(self, domain=None):
        self.чтений += 1
        if self.падать:
            raise RuntimeError("телефон отключили")
        return dict(self.fmip) if domain == "com.apple.fmip" else dict(self.root)


def _сверить(отчёт, замок):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from pintel_kiosk import worker
    p = worker.Pipeline({}, None, None)
    return asyncio.run(p._сверить_живьём(замок, отчёт))


ЖИВОЙ = {"SerialNumber": ПАСПОРТ["серийник"], "InternationalMobileEquipmentIdentity": ПАСПОРТ["imei"],
         "fm-activation-locked": "NO", "ActivationState": "Activated", "PasswordProtected": False}


def test_the_phone_is_checked_against_the_old_report_before_it_is_reused():
    """Прошлый отчёт берём, только сверив с живым телефоном то, что читается мгновенно.

    Один `get_value` — это доли секунды, а не минуты слепка. Без него прошлый отчёт мог бы
    прикрыть включённый за это время «Найти iPhone», то есть заблокированный аппарат в
    выкупе."""
    сошлось, почему = _сверить(_отчёт(), ФейкЗамок(ЖИВОЙ))
    assert сошлось is True and почему == ""


def test_a_changed_find_my_sends_the_phone_back_to_a_full_read():
    """«Найти iPhone» включили после прошлой проверки — читаем заново, а не берём старое."""
    сошлось, почему = _сверить(_отчёт(), ФейкЗамок({**ЖИВОЙ, "fm-activation-locked": "YES"}))
    assert сошлось is False and "найти_iphone" in почему


def test_another_phone_on_the_cable_sends_the_phone_back_to_a_full_read():
    """Серийник на кабеле другой — значит это другой аппарат, что бы ни было в папке."""
    сошлось, почему = _сверить(_отчёт(), ФейкЗамок({**ЖИВОЙ, "SerialNumber": "ЧУЖОЙ"}))
    assert сошлось is False and "SerialNumber" in почему


def test_an_unreadable_phone_is_not_called_verified():
    """Телефон не ответил — это не «сошлось» и не «разошлось», и врать про сверку нельзя.

    Прошлую проверку берём (она в окне), но отметка едет словами: и на экране, и в карточке
    видно, что с живым телефоном её не сверяли."""
    сошлось, почему = _сверить(_отчёт(), ФейкЗамок(ЖИВОЙ, падать=True))
    assert сошлось is None and почему.startswith("не сверили")
    # то же, когда правовой статус сейчас не прочитался
    сошлось, почему = _сверить(_отчёт(), ФейкЗамок({"SerialNumber": ПАСПОРТ["серийник"]}))
    assert сошлось is None and "не сверили" in почему
