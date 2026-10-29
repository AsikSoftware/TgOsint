# -*- coding: utf-8 -*-
"""Обновление по интернету: ездить по точкам с флешкой никто не станет.

Подмену папки проверить здесь нечем — она только под Windows и только на живой машине.
Поэтому проверяем всё, что можно проверить до неё: решение «обновляться или нет», защиту
распаковки и текст сценария, который и делает подмену.
"""
import os
import zipfile

import httpx
import pytest

from pintel_kiosk import updater

АРХИВ = "pintel-kiosk_Windows_x64.zip"


def релиз(тег="doctor-46", имя=АРХИВ):
    return {"tag_name": тег, "name": f"Pintel — сборка #{тег[-2:]}",
            "assets": [{"name": имя, "url": "https://api.github.com/a/1", "size": 55_000_000}]}


@pytest.mark.parametrize("свой,ждём,почему", [
    ("doctor-45", True, ""),
    ("doctor-46", False, "уже последняя"),
    ("", False, "сборка без метки"),          # запущено из исходников — не трогаем
])
def test_decides_by_the_release_tag(свой, ждём, почему):
    итог = updater.разобрать_релиз(релиз(), АРХИВ, свой)
    assert итог["есть"] is ждём and почему in итог["почему"]


@pytest.mark.parametrize("свой", ["doctor-47", "doctor-46"])
def test_update_never_goes_backwards(свой):
    """Откатиться назад касса не имеет права.

    Плохой релиз откатывают его удалением — и тогда GitHub отдаёт в «latest» предыдущий.
    Сравнение тегов «не равно» молча съехало бы на старую сборку на всех точках сразу, да
    ещё и предлагало бы это при каждой проверке."""
    итог = updater.разобрать_релиз(релиз("doctor-46"), АРХИВ, свой)
    assert итог["есть"] is False, итог
    assert "уже последняя" in итог["почему"] or "свежее релиза" in итог["почему"], итог


def test_versions_are_compared_as_numbers_not_text():
    """«doctor-9» как текст больше «doctor-46» — сравнение строк дало бы «обновление не
    нужно» и точка осталась бы на девятой сборке навсегда."""
    assert updater.разобрать_релиз(релиз("doctor-46"), АРХИВ, "doctor-9")["есть"] is True


def test_unknown_tag_shape_does_not_install_anything():
    """Тег не нашего вида сравнить нельзя. Тогда лучше ничего не ставить и сказать это
    вслух, чем наугад подменить рабочую программу на точке."""
    итог = updater.разобрать_релиз(релиз("v2.0-beta"), АРХИВ, "doctor-46")
    assert итог["есть"] is False and "вручную" in итог["почему"]


def test_release_without_our_archive_is_not_an_update():
    """В релизе лежат три архива; если нашего нет — обновляться нечем."""
    итог = updater.разобрать_релиз(релиз(имя="pintel-server_Windows_x64.zip"), АРХИВ, "doctor-45")
    assert итог["есть"] is False and "нет нужного архива" in итог["почему"]


def test_no_network_is_not_an_update(monkeypatch):
    """Точка без интернета не должна видеть ошибок на экране — просто нет обновления."""
    def рвётся(*a, **k):
        raise httpx.ConnectError("нет сети")
    monkeypatch.setattr(httpx, "get", рвётся)
    итог = updater.проверить("AsikSoftware/TgOsint", "ghp_x", АРХИВ, свой="doctor-45")
    assert итог["есть"] is False and "нет связи" in итог["почему"]


def test_github_refusal_is_reported_not_swallowed(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(401, json={}))
    итог = updater.проверить("AsikSoftware/TgOsint", "ghp_x", АРХИВ, свой="doctor-45")
    assert итог["есть"] is False and "401" in итог["почему"]


def test_check_is_skipped_without_a_token():
    assert updater.проверить("AsikSoftware/TgOsint", "", АРХИВ)["есть"] is False


def test_unpack_refuses_to_write_outside_its_folder(tmp_path):
    """Архив скачан из сети: путь вида ../../ не должен вынести файл мимо папки."""
    злой = tmp_path / "злой.zip"
    with zipfile.ZipFile(злой, "w") as z:
        z.writestr("../сбежал.txt", "ой")
    with pytest.raises(RuntimeError, match="мимо папки"):
        updater.распаковать(str(злой), str(tmp_path / "куда"))
    assert not (tmp_path / "сбежал.txt").exists()


def test_unpack_finds_the_program_folder(tmp_path):
    архив = tmp_path / "ok.zip"
    with zipfile.ZipFile(архив, "w") as z:
        z.writestr("pintel-kiosk/pintel-kiosk.exe", "MZ")
        z.writestr("pintel-kiosk/_internal/что-то.dll", "...")
    папка = updater.распаковать(str(архив), str(tmp_path / "новая"))
    assert os.path.isfile(os.path.join(папка, "pintel-kiosk.exe"))


def test_unpack_without_the_exe_is_an_error(tmp_path):
    архив = tmp_path / "пусто.zip"
    with zipfile.ZipFile(архив, "w") as z:
        z.writestr("readme.txt", "ничего")
    with pytest.raises(RuntimeError, match="нет pintel-kiosk.exe"):
        updater.распаковать(str(архив), str(tmp_path / "н"))


def test_script_waits_backs_up_and_can_roll_back():
    """Сценарий подменяет папку, пока программа закрыта. Старая версия уезжает рядом:
    не поднимется новая — вернуть прежнюю можно руками."""
    текст = updater.сценарий(r"C:\\u\\upd\\doctor-46\\pintel-kiosk", r"C:\\Pintel",
                             r"C:\\Pintel\\pintel-kiosk.exe")
    assert "tasklist" in текст and "goto ожидание" in текст        # ждёт, пока exe закроется
    assert "C:\\\\Pintel.bak" in текст                             # старая версия сохранена
    assert текст.count("robocopy") == 3                            # в резерв, новая, откат
    assert текст.rstrip().endswith('start "" "C:\\\\Pintel\\\\pintel-kiosk.exe"')
    assert "\r\n" in текст                                         # .cmd читается только с CRLF


def test_build_tag_is_absent_in_sources():
    """Из исходников программа не обновляется: метки релиза у неё нет."""
    assert updater.свой_тег() == ""
    assert updater.версия_словами("doctor-46").endswith("(сборка 46)")
