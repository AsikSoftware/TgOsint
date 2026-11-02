# -*- coding: utf-8 -*-
"""Настройки точки: их никто не вписывает руками.

Файла `kiosk.toml` больше нет. Программа — внешняя часть: адрес сервера зашит в сборку,
токен точки вводят в самой программе, настройки приходят с сервера и складываются в копию
рядом с данными. Проверяется то, что ломается у клиента: что программа поднимется и без
связи, что токен переживёт обновление и что страница теста попадёт в сборку.
"""
import os
import re

import pytest

from pintel_kiosk import config

HERE = os.path.dirname(os.path.abspath(__file__))
КОРЕНЬ = os.path.dirname(HERE)


def test_the_point_configures_nothing_by_hand():
    """Ни адреса, ни токена, ни настроек в файле у exe: ровно это и просили убрать.
    Адрес один на всю сеть и лежит в сборке."""
    assert config.СЕРВЕР.startswith("https://")
    assert not os.path.exists(os.path.join(КОРЕНЬ, "kiosk.example.toml")), \
        "пример настроек больше не нужен: на точке ничего не заполняют"
    for ключ in ("server", "token", "server_key"):
        assert ключ not in config.УМОЛЧАНИЯ, f"{ключ} приходит не из настроек"


def test_the_kiosk_starts_without_the_server(tmp_path):
    """Первый запуск или нет связи: программа поднимается на умолчаниях и знает, что
    настроек с сервера у неё ещё нет."""
    cfg = config.load(str(tmp_path))
    assert cfg["_настройки_с_сервера"] is False
    assert cfg["server"] == config.СЕРВЕР and cfg["token"] == ""
    assert cfg["fullscreen"] is True and cfg["apple_history_seconds"] == 90
    assert cfg["point"] == ""                      # имя точки говорит сервер, а не файл


def test_the_token_and_the_settings_survive_an_update(tmp_path):
    """Папку программы сносит и обновление, и переустановка распаковкой поверх. Токен и
    настройки лежат рядом с данными, поэтому ехать на точку заново никто не станет."""
    config.запомнить_токен("pk_точка1", str(tmp_path))
    config.сохранить_настройки({"point": "Алматы-1", "staff_name": "Асылбек",
                                "return_seconds": 45, "чужое": "выкинуть"}, str(tmp_path))
    cfg = config.load(str(tmp_path))
    assert cfg["token"] == "pk_точка1" and cfg["_настройки_с_сервера"] is True
    assert cfg["point"] == "Алматы-1" and cfg["return_seconds"] == 45
    assert "чужое" not in cfg                      # храним только то, что умеем читать


def test_a_broken_cache_does_not_kill_the_kiosk(tmp_path):
    """Файл копии побился (точку выключили на записи) — программа всё равно поднимается:
    у стойки нужен работающий киоск, а не окно Windows с traceback."""
    (tmp_path / config.ФАЙЛ_НАСТРОЕК).write_text("{это не json", encoding="utf-8")
    (tmp_path / config.ФАЙЛ_ТОКЕНА).write_text("тоже не json", encoding="utf-8")
    cfg = config.load(str(tmp_path))
    assert cfg["token"] == "" and cfg["point"] == "" and cfg["fullscreen"] is True


def test_build_workflow_stays_parseable():
    """Сломанный workflow не падает — он просто перестаёт запускаться: GitHub не видит
    триггеры и отвечает «Workflow does not have workflow_dispatch». Так и случилось,
    когда в строке запуска оказалось «: » — YAML принял её за пару ключ-значение."""
    yaml = pytest.importorskip("yaml")
    путь = os.path.join(КОРЕНЬ, "..", ".github", "workflows", "build-doctor.yml")
    if not os.path.isfile(путь):
        pytest.skip("рабочий процесс не в этом дереве")
    with open(путь, encoding="utf-8") as f:
        поток = yaml.safe_load(f)
    триггеры = поток.get(True) or поток.get("on") or {}       # «on:» YAML читает как True
    assert "workflow_dispatch" in триггеры, "сборку нельзя будет запустить вручную"
    шаги = [ш.get("name") for ш in поток["jobs"]["build"]["steps"]]
    assert "Метка сборки" in шаги, "без метки программа не узнает о новой версии"


@pytest.mark.parametrize("имя", ["config.example.toml", "server.example.toml"])
def test_other_shipped_examples_parse(имя):
    import tomllib
    with open(os.path.join(КОРЕНЬ, имя), "rb") as f:
        tomllib.load(f)


def test_the_phone_test_ships_with_the_build():
    """Страница теста и мини-сервер должны попасть в exe: без страницы киоск покажет QR,
    по которому телефон клиента увидит «страница не найдена» посреди сделки."""
    спека = open(os.path.join(КОРЕНЬ, "pintel-kiosk.spec"), encoding="utf-8").read()
    assert "pintel_kiosk.phoneweb" in спека and "pintel_core.phonetest" in спека
    # страница общая: её отдаёт и мини-сервер киоска, и наш сервер на домене
    assert "('pintel_core/assets', 'pintel_core/assets')" in спека, "страница лежит в assets ядра"
    assert os.path.exists(os.path.join(КОРЕНЬ, "pintel_core", "assets", "diag.html"))
    assert config.УМОЛЧАНИЯ["phone_test_port"] == 8765


def test_the_settings_names_match_the_server():
    """Сервер присылает ровно этот набор ключей. Разойдутся — настройка молча не доедет,
    и понять это можно будет только по жалобе с точки."""
    спис = open(os.path.join(КОРЕНЬ, "pintel_server", "services", "kiosk_settings.py"),
                encoding="utf-8").read()
    серверные = set(re.findall(r'^    "([a-z_]+)":', спис, re.M))
    наши = set(config.УМОЛЧАНИЯ) - {"point", "staff_name"}     # их сервер добавляет отдельно
    assert наши <= серверные, "эти ключи программа ждёт, а сервер не присылает: " + \
        ", ".join(sorted(наши - серверные))
