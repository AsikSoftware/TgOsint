# -*- coding: utf-8 -*-
"""Диск на точке: оценка весит около мегабайта, и без уборки его хватает на пару месяцев.

Кончившийся диск останавливает приём совсем — записать очередную оценку будет некуда,
поэтому уборка проверяется тестами, а не «потом посмотрим».
"""
import json
import os
import tempfile
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())

from pintel_kiosk import config as kconfig            # noqa: E402
from pintel_kiosk import worker                        # noqa: E402
from pintel_kiosk.client import Client                 # noqa: E402

ДАВНО = 100 * 86400


@pytest.fixture
def точка(tmp_path, monkeypatch):
    """Свой %LOCALAPPDATA% на тест: трогать настоящую папку киоска нельзя."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for модуль in (worker, kconfig):
        monkeypatch.setattr(модуль, "data_dir", kconfig.data_dir, raising=False)
    d = kconfig.data_dir()
    return d


def _состарить(путь, дней):
    старое = time.time() - дней * 86400
    os.utime(путь, (старое, старое))


def test_old_evaluations_go_but_fresh_ones_stay(точка):
    свежая = os.path.join(точка, "out", "20261028_143512_phone")
    старая = os.path.join(точка, "out", "20260101_101010_phone")
    for d in (свежая, старая):
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "snapshot.json"), "w").write("{}")
    _состарить(старая, 100)
    убрано = worker.убрать_старое(90)
    assert убрано == 1
    assert os.path.isdir(свежая) and not os.path.exists(старая)


def test_references_are_never_touched(точка):
    """Эталоны обезличены, весят 85 КБ и ограничены числом — у них своя жизнь."""
    эталон = os.path.join(точка, "эталоны", "эталон_iPhone-14-Pro_iOS26.5_20260101.zip")
    open(эталон, "wb").write(b"PK")
    _состарить(эталон, 400)
    worker.убрать_старое(90)
    assert os.path.isfile(эталон)


def test_leftover_queue_and_receipts_are_cleaned(точка):
    """Остатки очереди на сервер и старые чеки — такой же мусор, как оценки."""
    хвост = os.path.join(точка, "queue", "phone-abc123.json")
    чек = os.path.join(точка, "out", "чек_7KQ4M.html")
    for p in (хвост, чек):
        open(p, "w").write("x")
        _состарить(p, 120)
    assert worker.убрать_старое(90) == 2
    assert not os.path.exists(хвост) and not os.path.exists(чек)


def test_cleanup_can_be_turned_off(точка):
    старая = os.path.join(точка, "out", "20260101_101010_phone")
    os.makedirs(старая, exist_ok=True)
    _состарить(старая, 999)
    assert worker.убрать_старое(0) == 0
    assert os.path.isdir(старая)


def test_without_a_server_nothing_is_queued(точка):
    """Сервера нет — досылать некуда (flush_queue работает только при настроенном
    сервере), а слепок и отчёт уже лежат в out. Копия по мегабайту на оценку росла бы
    вечно: ровно это и съедало диск."""
    клиент = Client({**kconfig.DEFAULTS, "server": "", "token": ""})
    assert клиент.upload({"client_id": "phone-1", "report": {}, "snapshot": {}}) is None
    assert клиент.queued() == 0

    настроенный = Client({**kconfig.DEFAULTS, "server": "https://x.kz", "token": "pk_1"})
    assert настроенный.upload({"client_id": "phone-2", "report": {}, "snapshot": {}}) is None
    assert настроенный.queued() == 1          # сервер есть, но молчит — копим на досылку


def test_log_does_not_grow_forever(точка, monkeypatch):
    """Лог на точке никто не чистит."""
    monkeypatch.setattr(worker, "ЛОГ_МАКС", 2000)
    for i in range(80):
        worker.log_line("строка " * 10)
    путь = os.path.join(точка, "logs", "kiosk.log")
    assert os.path.getsize(путь) <= 2000 + 200
    assert os.path.isfile(путь + ".1")        # предыдущий кусок рядом, не потерян
