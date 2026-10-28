# -*- coding: utf-8 -*-
"""Архив слепков: объезжать ноутбуки и собирать папки руками никто не станет.

Своего сервера нет, поэтому файлы уходят в закрытый чат Telegram. Проверяем то, из-за
чего такой выгрузкой перестают пользоваться: повторные отправки, потерянные файлы после
обрыва связи и молчаливые пропуски.
"""
import json
import os

import httpx
import pytest

from pintel_core.external import tg_upload


@pytest.fixture
def папка(tmp_path):
    д = tmp_path / "эталоны"
    д.mkdir()
    for имя in ("эталон_A_1.zip", "эталон_B_2.zip", "эталон_C_3.zip"):
        (д / имя).write_bytes(b"PK\x03\x04" + имя.encode())
    return д


def _фейк(ушедшие, падает_после=None):
    def post(url, data=None, files=None, timeout=None):
        if падает_после is not None and len(ушедшие) >= падает_после:
            raise httpx.ConnectError("нет сети")
        ушедшие.append(files["document"][0])
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(ушедшие)}})
    return post


def test_sends_each_file_once(папка, tmp_path, monkeypatch):
    """Второй запуск не должен слать то же самое ещё раз — иначе чат забивается копиями."""
    ушедшие = []
    monkeypatch.setattr(httpx, "post", _фейк(ушедшие))
    отметка = str(tmp_path / "cache" / "архив.json")
    итог = tg_upload.догнать("123:ABC", -100, str(папка), отметка, подпись="16/38")
    assert итог == {"ушло": 3, "осталось": 0, "ошибка": ""}
    assert sorted(ушедшие) == ["эталон_A_1.zip", "эталон_B_2.zip", "эталон_C_3.zip"]
    assert tg_upload.догнать("123:ABC", -100, str(папка), отметка)["ушло"] == 0
    (папка / "эталон_D_4.zip").write_bytes(b"PK")
    assert tg_upload.догнать("123:ABC", -100, str(папка), отметка)["ушло"] == 1


def test_a_broken_link_loses_nothing(папка, tmp_path, monkeypatch):
    """Связь оборвалась на втором файле: первый отмечен ушедшим, остальные ждут на диске."""
    ушедшие = []
    monkeypatch.setattr(httpx, "post", _фейк(ушедшие, падает_после=1))
    отметка = str(tmp_path / "cache" / "архив.json")
    итог = tg_upload.догнать("123:ABC", -100, str(папка), отметка)
    assert итог["ушло"] == 1 and итог["осталось"] == 2 and "нет сети" in итог["ошибка"]
    monkeypatch.setattr(httpx, "post", _фейк(ушедшие))      # связь вернулась
    assert tg_upload.догнать("123:ABC", -100, str(папка), отметка)["ушло"] == 2
    assert len(set(ушедшие)) == 3 and len(ушедшие) == 3     # ничего не ушло дважды


def test_snapshots_in_different_folders_do_not_collide(tmp_path, monkeypatch):
    """У полных слепков все файлы зовутся snapshot.json: по имени они схлопнулись бы в
    один, и выгрузился бы только первый."""
    out = tmp_path / "out"
    for день in ("20261028_101010_phone", "20261028_121212_phone"):
        (out / день).mkdir(parents=True)
        (out / день / "snapshot.json").write_text("{}", encoding="utf-8")
    ушедшие = []
    monkeypatch.setattr(httpx, "post", _фейк(ушедшие))
    итог = tg_upload.догнать("123:ABC", -100, str(out), str(tmp_path / "c.json"),
                             os.path.join("*", "snapshot.json"))
    assert итог["ушло"] == 2
    assert sorted(ушедшие) == ["20261028_101010_phone_snapshot.json",
                               "20261028_121212_phone_snapshot.json"]


def test_oversized_file_is_skipped_but_not_retried_forever(папка, tmp_path, monkeypatch):
    """Файл, который Telegram не примет, не должен держать очередь на каждом запуске."""
    monkeypatch.setattr(tg_upload, "ПРЕДЕЛ_ФАЙЛА", 10)
    (папка / "эталон_Z_9.zip").write_bytes(b"x" * 100)
    ушедшие = []
    monkeypatch.setattr(httpx, "post", _фейк(ушедшие))
    отметка = str(tmp_path / "архив.json")
    итог = tg_upload.догнать("123:ABC", -100, str(папка), отметка)
    assert итог["ушло"] == 0 and итог["осталось"] == 0      # мелкие тоже больше предела
    assert json.load(open(отметка, encoding="utf-8"))["ушло"]


def test_nothing_happens_without_a_chat(папка, tmp_path, monkeypatch):
    def нельзя(*a, **k):
        raise AssertionError("без чата ничего слать нельзя")
    monkeypatch.setattr(httpx, "post", нельзя)
    assert tg_upload.догнать("123:ABC", "", str(папка), str(tmp_path / "a.json"))["ушло"] == 0
    assert tg_upload.догнать("", -100, str(папка), str(tmp_path / "a.json"))["ушло"] == 0


def test_telegram_refusal_is_reported_in_words(папка, tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(
        400, json={"ok": False, "description": "chat not found"}))
    итог = tg_upload.догнать("123:ABC", -100, str(папка), str(tmp_path / "a.json"))
    assert итог["ушло"] == 0 and "chat not found" in итог["ошибка"]
