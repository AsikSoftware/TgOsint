# -*- coding: utf-8 -*-
"""Panic full: отчёт о панике ядра — вопрос, который Оценка задаёт о каждом телефоне.

Читаем его сами, из crash-логов по кабелю — там же, где смотрят глазами в «Аналитике».
Два требования к этому чтению: не соврать (не прочитали — значит «не знаем», а не «нет»)
и ничего не испортить на телефоне клиента.
"""
import asyncio
import os

import pytest

from pintel_core import reference
from pintel_core.analysis import report as report_mod
from pintel_core.devicelink import panic, snapshot

HERE = os.path.dirname(os.path.abspath(__file__))
ЭТАЛОН = os.path.join(HERE, "fixtures_real", "эталоны", "эталон_iPhone-14-Pro_iOS26.5.zip")


def test_panic_full_is_found_among_other_logs():
    """Имена как на телефоне: полный отчёт о панике — panic-full-*.ips, старые лежат
    в Retired. Остальные crash-логи паникой не считаем."""
    р = panic.разобрать([
        "panic-full-2026-10-01-123456.ips",
        "Retired/panic-full-2025-05-05-000000.ips",
        "panic-base-2026-02-02-000000.ips",
        "JetsamEvent-2026-03-03.ips", "stacks-2026-10-02.ips", "log-aggregated.ips",
    ])
    assert р["panic_full"] is True and р["полных"] == 2
    assert р["последняя"] == "2026-10-01"                   # самая свежая, а не первая попавшаяся
    assert р["паник_всего"] == 3 and р["файлов"] == 6


def test_other_crashes_are_not_panic_full():
    """Обычные падения приложений есть у всех — выдавать их за panic full нельзя."""
    р = panic.разобрать(["JetsamEvent-2026-03-03.ips", "WhatsApp-2026-01-01.ips",
                         "panic-base-2026-02-02.ips"])
    assert р["panic_full"] is False and р["полных"] == 0
    assert р["паник_всего"] == 1                             # panic-base — паника, но не полная
    assert "нет" in panic.словами(р)


def test_empty_device_reads_as_no_panic():
    р = panic.разобрать([])
    assert р["проверено"] is True and р["panic_full"] is False and р["файлов"] == 0


def test_probe_reads_the_list_and_touches_nothing(monkeypatch):
    """На телефоне клиента логи должны остаться: только список имён, никаких pull и clear."""
    from pymobiledevice3.services import crash_reports as cr
    трогали = []

    class ФейкСервис:
        def __init__(self, lockdown):
            self.lockdown = lockdown

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def ls(self, path="/", depth=1):
            трогали.append(("ls", path, depth))
            return ["panic-full-2026-09-09-111111.ips", "stacks-2026-09-09.ips"]

        async def pull(self, *a, **k):
            raise AssertionError("скачивать логи клиента нельзя")

        async def clear(self, *a, **k):
            raise AssertionError("удалять логи клиента нельзя")

    monkeypatch.setattr(cr, "CrashReportsManager", ФейкСервис)
    р = asyncio.run(panic.probe(object()))
    assert р["panic_full"] is True and р["последняя"] == "2026-09-09"
    assert трогали == [("ls", "/", panic.ГЛУБИНА)]           # ровно одно действие, и то чтение


def test_probe_never_raises_and_says_it_did_not_read(monkeypatch):
    """Сервис недоступен (старая iOS, телефон отключили) — это «не знаем», не «нет»."""
    from pymobiledevice3.services import crash_reports as cr

    class Падает:
        def __init__(self, lockdown):
            raise OSError("нет сервиса")

    monkeypatch.setattr(cr, "CrashReportsManager", Падает)
    р = asyncio.run(panic.probe(object()))
    assert р["проверено"] is False and р["panic_full"] is None
    assert "нет сервиса" in р["ошибка"] and "не проверено" in panic.словами(р)


def _отчёт(паника):
    snap, _ = reference.load_bundle(ЭТАЛОН, loads=snapshot.loads)
    snap["panic"] = паника
    return report_mod.build(snap)


def test_report_warns_about_panic_full():
    """На выкупе panic full — признак проблемы платы. Не стоп-фактор, но оценщик обязан
    это увидеть, а не узнать после покупки."""
    rep = _отчёт(panic.разобрать(["panic-full-2026-10-01-1.ips"]))
    assert rep["паника"]["panic_full"] is True
    assert any("panic full: ЕСТЬ" in x for x in rep["внимание"])
    assert any("плата" in x for x in rep["внимание"])


def test_report_does_not_claim_a_clean_board_when_it_could_not_read():
    """Не прочитали — так и пишем. «Паники нет» без проверки хуже, чем «не знаем»."""
    rep = _отчёт({"проверено": False, "panic_full": None, "ошибка": "нет сервиса"})
    assert rep["паника"]["panic_full"] is None
    assert any("panic full" in x for x in rep["не_прочиталось"])
    assert not any("panic full: ЕСТЬ" in x for x in rep["внимание"])


@pytest.mark.parametrize("паника,ждём", [
    (panic.разобрать(["panic-full-2026-10-01-1.ips"]), True),
    (panic.разобрать(["stacks-2026-10-02.ips"]), False),
    ({"проверено": False, "panic_full": None}, None),
])
def test_export_sends_what_we_actually_know(паника, ждём):
    """В сделку уходит ровно то, что прочитали: True, False или пусто. У Оценки пустое
    поле печатается как «Panic full: -», и это честно."""
    from pintel_core.external import ocenka
    данные = {"модель": "iPhone 14 Pro", "память": 256, "имя_клиента": "Зама",
              "телефон_клиента": "+77058837953", "imei": "350585886690250",
              "panic_full": (паника or {}).get("panic_full")}
    assert ocenka.посылка(данные, "7KQ4M")["сделка"]["panic_full"] is ждём
