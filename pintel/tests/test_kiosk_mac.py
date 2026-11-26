# -*- coding: utf-8 -*-
"""Касса на маке: обновление, папка данных, упаковка.

ВАЖНО про сами эти тесты: сборка гоняет их на трёх системах — Linux (тесты сервера, Qt там
нет вовсе), Windows (сборка для точек) и мак. Значит, проверки маковских решений обязаны
проходить и на Windows: пути там разбираются по своим правилам, и os.path.abspath припишет
к «/Applications» букву диска. Поэтому пути сверяем приведёнными к одному виду.

Владелец, 25.11.2026: «сможем ли мы сделать ещё версию для мака?» — точка на маке.

Проверять это на самом маке мало: сборка идёт на машине GitHub, а гонять тесты мы будем и
на Windows. Поэтому систему здесь подменяем и смотрим на решения, которые от неё зависят.
Ошибиться тут дорого: маковская касса, скачавшая windows-архив, не поднимется вовсе, а
подмена не того каталога оставит половину прошлой версии внутри программы.
"""
import os
import sys
import zipfile

import pytest

from pintel_kiosk import updater


def _как_путь(п: str) -> str:
    """Путь к одному виду: на машине сборки под Windows разделитель свой."""
    return str(п).replace("\\", "/")


def test_each_kind_of_point_asks_for_its_own_archive(monkeypatch):
    """Имя архива выбирает сама программа, а не настройка с сервера: настройка одна на все
    точки, а касса бывает windows-овая и маковская."""
    monkeypatch.setattr(sys, "platform", "win32")
    assert updater.архив_этой_системы("что угодно") == "pintel-kiosk_Windows_x64.zip"

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    assert updater.архив_этой_системы("pintel-kiosk_Windows_x64.zip") == "pintel-kiosk_macOS_arm64.zip"
    # старый мак на Intel своей сборки пока не имеет — он попросит её по имени и не найдёт
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    assert updater.архив_этой_системы("") == "pintel-kiosk_macOS_x86_64.zip"


def test_on_a_mac_the_whole_app_is_replaced(monkeypatch):
    """На маке программа — это весь .app, а exe лежит внутри него.

    Подменить только внутреннюю папку значит оставить половину прошлой версии рядом с новой
    и сломать программу совсем."""
    monkeypatch.setattr(sys, "platform", "darwin")
    внутри = "/Applications/pintel-kiosk.app/Contents/MacOS"
    assert _как_путь(updater.папка_программы(внутри)) == "/Applications/pintel-kiosk.app"
    # .app нет вовсе (запущено из исходников) — подменять нечего, путь не выдумываем
    assert updater.папка_программы("/Users/kassa/pintel") == "/Users/kassa/pintel"

    monkeypatch.setattr(sys, "platform", "win32")
    assert updater.папка_программы(r"C:\Pintel") == r"C:\Pintel"


def test_the_mac_script_waits_for_the_program_and_can_roll_back():
    """Сценарий подмены для мака: ждёт закрытия по номеру процесса, уносит прежнюю версию
    в запас, при осечке возвращает её и запускает программу обратно."""
    текст = updater.сценарий_мак("/tmp/update/новая/pintel-kiosk.app",
                                 "/Applications/pintel-kiosk.app", 4242)
    assert "kill -0 4242" in текст, "ждём не ту программу — по имени процесса ждать нельзя"
    assert '"/Applications/pintel-kiosk.app.bak"' in текст, "прежней версии не остаётся"
    assert 'mv "/Applications/pintel-kiosk.app" "/Applications/pintel-kiosk.app.bak"' in текст
    assert 'cp -R "/tmp/update/новая/pintel-kiosk.app" "/Applications/pintel-kiosk.app"' in текст
    # осечка: новой папки нет — возвращаем прежнюю, иначе точка останется без программы
    assert 'mv "/Applications/pintel-kiosk.app.bak" "/Applications/pintel-kiosk.app"' in текст
    assert 'open "/Applications/pintel-kiosk.app"' in текст, "программа не запустится обратно"
    for строка in текст.splitlines():
        assert "\r" not in строка, "перевод строки Windows: /bin/sh такой файл не поймёт"


def test_the_mac_archive_is_unpacked_to_the_app(tmp_path, monkeypatch):
    """В маковском архиве лежит .app, и распаковка должна вернуть путь к нему."""
    monkeypatch.setattr(sys, "platform", "darwin")
    архив = tmp_path / "сборка.zip"
    with zipfile.ZipFile(архив, "w") as z:
        z.writestr("pintel-kiosk.app/Contents/MacOS/pintel-kiosk", "программа")
        z.writestr("pintel-kiosk.app/Contents/Info.plist", "<plist/>")
    путь = updater.распаковать(str(архив), str(tmp_path / "новая"))
    assert путь.endswith("pintel-kiosk.app") and os.path.isdir(путь)

    пустой = tmp_path / "пустой.zip"
    with zipfile.ZipFile(пустой, "w") as z:
        z.writestr("readme.txt", "ничего")
    with pytest.raises(RuntimeError):
        updater.распаковать(str(пустой), str(tmp_path / "нет"))


def test_nothing_is_copied_inside_a_mac_app(tmp_path, monkeypatch):
    """Внутрь .app на точке ничего не кладут, и подпись программы это ломает. Токен точки и
    настройки лежат в папке данных — обновление их не трогает."""
    monkeypatch.setattr(sys, "platform", "darwin")
    старая, новая = tmp_path / "старая.app", tmp_path / "новая.app"
    старая.mkdir(), новая.mkdir()
    (старая / "своё.txt").write_text("на точке положили", encoding="utf-8")
    assert updater.перенести_своё(str(старая), str(новая)) == []
    assert not (новая / "своё.txt").exists()


def test_mac_data_lives_where_mac_programs_keep_it(tmp_path, monkeypatch):
    """Папка данных на маке — в «Библиотеке», а не в домашней: иначе она валяется на виду."""
    from pintel_kiosk import config

    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    путь = config.data_dir()
    # Хвост, а не путь целиком: домашнюю папку Windows берёт не из HOME, и на машине сборки
    # начало пути будет своё. Важно одно — данные лежат в «Библиотеке», как у маковских программ.
    assert _как_путь(путь).endswith("/Library/Application Support/PintelKiosk"), путь
    assert os.path.isdir(os.path.join(путь, "logs"))

    # подмена пути (тесты и Windows) по-прежнему главнее системы
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "подмена"))
    assert _как_путь(config.data_dir()).endswith("/подмена/PintelKiosk")


# ---------------------------------------------------------------- облик


def test_both_looks_have_the_same_set_of_materials():
    """Наборы материалов обязаны совпадать ключ в ключ.

    Правило QSS с незаполненным «%(…)s» — это не блеклая кнопка, а падение программы при
    запуске: на кассе это закрытая точка. Разойтись наборы могут незаметно — добавил ключ
    ради стекла и забыл про Windows, а проверяешь на маке."""
    pytest.importorskip("PySide6")               # в линуксовой работе сборки окон нет
    from pintel_kiosk import ui

    assert set(ui._МАТЕРИАЛ_WIN) == set(ui._МАТЕРИАЛ_СТЕКЛО)
    # и оба набора целиком подставляются в оба набора правил
    from pintel_kiosk import ui_deal
    for стекло in (False, True):
        палитра = ui.материал(стекло)
        for правила in (ui.QSS_ИСХОДНИК, ui_deal.QSS_DEAL_ИСХОДНИК):
            собрано = правила % палитра
            assert "%(" not in собрано


def test_the_windows_look_is_not_touched_by_the_mac_glass():
    """Облик Windows-точек остаётся прежним.

    Там он отработан, сотрудники к нему привыкли, и менять его заодно со стеклом незачем:
    любая правка облика на точке — это переучивание людей и новые вопросы на кассе."""
    pytest.importorskip("PySide6")               # в линуксовой работе сборки окон нет
    from pintel_kiosk import ui

    обычный = ui.материал(False)
    assert обычный["м_карточка"] == ui.C["card"]
    assert обычный["м_окно"] == ui.C["ground"]
    assert обычный["р_карточка"] == "22px"

    стекло = ui.материал(True)
    assert "rgba" in стекло["м_карточка"], "карточка на маке должна пропускать фон"
    assert "rgba" not in стекло["м_окно"], "сквозь окно поверх экрана не должно быть видно текст"


def test_unpacking_keeps_the_program_runnable(tmp_path, monkeypatch):
    """После распаковки программа внутри .app обязана остаться запускаемой, а ссылки — ссылками.

    Это не придирка. 26.11.2026 касса на маке обновилась и умерла: `zipfile` снял право на
    запуск с самой программы и превратил ссылки внутри рамок Qt в текстовые файлы. Папка на
    месте, вид правильный, запускать нечего."""
    import subprocess
    import zipfile

    if sys.platform != "darwin":
        pytest.skip("распаковка ditto проверяется на маке: на Windows её нет")

    # собираем .app как это делает сборка: ditto сохраняет права и ссылки
    исходник = tmp_path / "pintel-kiosk.app" / "Contents" / "MacOS"
    исходник.mkdir(parents=True)
    программа = исходник / "pintel-kiosk"
    программа.write_text("#!/bin/sh\necho я программа\n", encoding="utf-8")
    программа.chmod(0o755)
    рамки = tmp_path / "pintel-kiosk.app" / "Contents" / "Frameworks" / "QtCore.framework"
    рамки.mkdir(parents=True)
    (рамки / "Versions").mkdir()
    (рамки / "QtCore").symlink_to("Versions/Current/QtCore")

    архив = tmp_path / "сборка.zip"
    subprocess.check_call(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                           str(tmp_path / "pintel-kiosk.app"), str(архив)])

    путь = updater.распаковать(str(архив), str(tmp_path / "новая"))
    снова = os.path.join(путь, "Contents", "MacOS", "pintel-kiosk")
    assert os.access(снова, os.X_OK), "программа после распаковки не запускается"
    assert os.path.islink(os.path.join(путь, "Contents", "Frameworks", "QtCore.framework",
                                       "QtCore")), "ссылка внутри рамки Qt стала файлом"

    # защита от архива, который лезет мимо папки, осталась на месте
    злой = tmp_path / "злой.zip"
    with zipfile.ZipFile(злой, "w") as z:
        z.writestr("../сбежал.txt", "ой")
    with pytest.raises(RuntimeError):
        updater.распаковать(str(злой), str(tmp_path / "куда"))


def test_the_mac_script_rolls_back_when_the_new_program_cannot_run():
    """Откат смотрит на саму программу, а не на папку: испорченная сборка оставляет папку
    на месте, и проверка «папка есть» пропустила бы мёртвую кассу."""
    текст = updater.сценарий_мак("/tmp/новая/pintel-kiosk.app",
                                 "/Applications/pintel-kiosk.app", 4242)
    assert '[ ! -x "/Applications/pintel-kiosk.app/Contents/MacOS/pintel-kiosk" ]' in текст
    assert 'mv "/Applications/pintel-kiosk.app.bak" "/Applications/pintel-kiosk.app"' in текст
