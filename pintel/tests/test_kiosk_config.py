# -*- coding: utf-8 -*-
"""kiosk.toml: его читает каждая точка при запуске, и ошибка здесь останавливает работу.

Проверяется то, что ломается у клиента, а не у нас: что файл, который мы кладём в
сборку, вообще разбирается, что все ключи записываемы в TOML, и что испорченный файл не
роняет программу — на точке нужен экран с причиной, а не окно Windows с traceback.
"""
import os
import re
import tomllib

import pytest

from pintel_kiosk import config

HERE = os.path.dirname(os.path.abspath(__file__))
КОРЕНЬ = os.path.dirname(HERE)
ГОЛЫЙ_КЛЮЧ = re.compile(r"[A-Za-z0-9_-]+")


def test_every_setting_can_be_written_in_toml():
    """В TOML голый ключ — только ASCII-буквы, цифры, «_» и «-». Ключ «сотрудник»
    кириллицей роняет tomllib на этой строке, и киоск не поднимается вовсе."""
    плохие = [k for k in config.DEFAULTS if not ГОЛЫЙ_КЛЮЧ.fullmatch(k)]
    assert not плохие, "эти ключи нельзя записать в kiosk.toml: " + ", ".join(плохие)


def test_shipped_example_parses_and_matches_the_code():
    """kiosk.example.toml едет в сборку, и на точке его переименовывают в kiosk.toml.
    Если он не разбирается — программа не запустится ни на одной точке."""
    путь = os.path.join(КОРЕНЬ, "kiosk.example.toml")
    with open(путь, "rb") as f:
        данные = tomllib.load(f)
    лишние = sorted(set(данные) - set(config.DEFAULTS))
    assert not лишние, "в примере ключи, которых нет в коде: " + ", ".join(лишние)
    assert данные.get("ocenka_bot"), "без имени бота QR на медиа собрать не из чего"


@pytest.mark.parametrize("имя", ["config.example.toml", "server.example.toml"])
def test_other_shipped_examples_parse(имя):
    with open(os.path.join(КОРЕНЬ, имя), "rb") as f:
        tomllib.load(f)


def test_broken_file_does_not_kill_the_kiosk(tmp_path):
    """Точка правит kiosk.toml руками. Опечатка не должна превращаться в неработающий
    киоск: поднимаемся на умолчаниях и говорим, в какой строке беда."""
    битый = tmp_path / "kiosk.toml"
    битый.write_text('point = "16/38"\nсотрудник = "Асылбек"\n', encoding="utf-8")
    cfg = config.load(str(битый))
    assert "line 2" in cfg["_ошибка"], cfg["_ошибка"]      # tomllib называет строку — она и нужна
    assert cfg["point"] == config.DEFAULTS["point"]        # умолчания, а не полуразобранный файл
    assert cfg["fullscreen"] is True


def test_unknown_key_is_named_not_swallowed(tmp_path):
    """Опечатка в имени ключа раньше проглатывалась молча — выглядело как «настройка
    не работает»."""
    файл = tmp_path / "kiosk.toml"
    файл.write_text('point = "16/38"\nocenka_chatid = "-100500"\n', encoding="utf-8")
    cfg = config.load(str(файл))
    assert "ocenka_chatid" in cfg["_ошибка"]
    assert cfg["point"] == "16/38"                         # остальное всё равно применилось


def test_good_file_is_silent(tmp_path):
    файл = tmp_path / "kiosk.toml"
    файл.write_text('point = "16/38"\nstaff_name = "Асылбек"\nserver = "https://x.kz/"\n',
                    encoding="utf-8")
    cfg = config.load(str(файл))
    assert cfg["_ошибка"] == "" and cfg["staff_name"] == "Асылбек"
    assert cfg["server"] == "https://x.kz"                 # хвостовой слэш убираем сами
