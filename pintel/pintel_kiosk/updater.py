# -*- coding: utf-8 -*-
"""Обновление программы по интернету: ездить по точкам с флешкой никто не станет.

Сборки уже лежат в релизах GitHub — туда их кладёт сама сборка. Программа спрашивает у
GitHub последний релиз, сравнивает его тег со своим и, если он другой, скачивает архив,
распаковывает рядом и подменяет папку.

Подменить работающий exe на месте Windows не даёт, поэтому замену делает маленький .cmd:
он ждёт, пока программа закроется, переносит новую папку поверх старой и запускает её
снова. Старая версия при этом остаётся рядом — если новая не поднимется, откатиться
можно руками, ничего не потеряв.

Обновление НЕ применяется само посреди работы: программа показывает кнопку на экране
ожидания, и сотрудник нажимает её, когда у стойки никого нет.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import zipfile

from . import __version__

log = logging.getLogger("pintel.update")

API = "https://api.github.com"
ТЕГ_ФАЙЛ = "build_info.json"          # кладёт сборка: из какого релиза собран этот exe


def свой_тег() -> str:
    """Тег релиза, из которого собрана эта программа. Пусто — запущено из исходников."""
    for папка in (os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False)
                                                  else __file__)),
                  os.path.dirname(os.path.abspath(__file__))):
        путь = os.path.join(папка, ТЕГ_ФАЙЛ)
        if os.path.isfile(путь):
            try:
                with open(путь, encoding="utf-8-sig") as f:   # на Windows бывает BOM
                    return str(json.load(f).get("тег") or "")
            except Exception:                                    # noqa: BLE001
                return ""
    return ""


def разобрать_релиз(релиз: dict, имя_архива: str, свой: str) -> dict:
    """Ответ GitHub → что с ним делать. Отдельно от сети, чтобы проверялось тестами."""
    тег = str((релиз or {}).get("tag_name") or "")
    активы = [a for a in ((релиз or {}).get("assets") or [])
              if str(a.get("name") or "") == имя_архива]
    if not тег or not активы:
        return {"есть": False, "тег": тег, "почему": "в релизе нет нужного архива"}
    if not свой:
        # запущено из исходников или сборка без метки — сами не обновляемся
        return {"есть": False, "тег": тег, "почему": "сборка без метки релиза"}
    if тег == свой:
        return {"есть": False, "тег": тег, "почему": "уже последняя"}
    актив = активы[0]
    return {"есть": True, "тег": тег, "почему": "",
            "url": актив.get("url"), "размер": int(актив.get("size") or 0),
            "имя": актив.get("name"), "описание": str((релиз or {}).get("name") or тег)}


def проверить(репозиторий: str, токен: str, имя_архива: str, свой: str = "",
              таймаут: float = 20.0) -> dict:
    """Спросить у GitHub последний релиз. Сети нет — просто «нет обновления»."""
    import httpx
    if not (репозиторий and токен):
        return {"есть": False, "почему": "обновление не настроено"}
    заголовки = {"Authorization": f"Bearer {токен}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"}
    try:
        r = httpx.get(f"{API}/repos/{репозиторий}/releases/latest", headers=заголовки,
                      timeout=таймаут)
        if r.status_code >= 400:
            return {"есть": False, "почему": f"GitHub ответил {r.status_code}"}
        релиз = r.json()
    except Exception as exc:                                     # noqa: BLE001
        return {"есть": False, "почему": f"нет связи: {type(exc).__name__}"}
    return разобрать_релиз(релиз, имя_архива, свой or свой_тег())


def скачать(url: str, токен: str, куда: str, таймаут: float = 600.0) -> str:
    """Архив релиза → файл на диске. → путь."""
    import httpx
    os.makedirs(os.path.dirname(куда), exist_ok=True)
    временный = куда + ".part"
    заголовки = {"Authorization": f"Bearer {токен}", "Accept": "application/octet-stream"}
    with httpx.stream("GET", url, headers=заголовки, timeout=таймаут,
                      follow_redirects=True) as r:
        r.raise_for_status()
        with open(временный, "wb") as f:
            for кусок in r.iter_bytes(1 << 20):
                f.write(кусок)
    os.replace(временный, куда)
    return куда


def распаковать(архив: str, куда: str) -> str:
    """Архив → папка с программой. → путь к папке, в которой лежит exe."""
    if os.path.isdir(куда):
        shutil.rmtree(куда, ignore_errors=True)
    os.makedirs(куда, exist_ok=True)
    with zipfile.ZipFile(архив) as z:
        for имя in z.namelist():                                 # не даём архиву вылезти из папки
            цель = os.path.normpath(os.path.join(куда, имя))
            if not цель.startswith(os.path.normpath(куда)):
                raise RuntimeError(f"архив пытается записать мимо папки: {имя}")
        z.extractall(куда)
    for корень, _, файлы in os.walk(куда):
        if any(f.lower() == "pintel-kiosk.exe" for f in файлы):
            return корень
    raise RuntimeError("в архиве нет pintel-kiosk.exe")


def сценарий(новая: str, установлена: str, exe: str) -> str:
    """Текст .cmd, который подменяет папку, пока программа закрыта.

    robocopy /MIR переносит новую папку поверх старой; старая уезжает в .bak рядом —
    если новая версия не поднимется, вернуть прежнюю можно руками.
    """
    резерв = установлена.rstrip("\\/") + ".bak"
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "echo Обновление Pintel Check...\r\n"
        ":ожидание\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        f'tasklist /fi "imagename eq {os.path.basename(exe)}" | find /i "{os.path.basename(exe)}" >nul '
        "&& goto ожидание\r\n"
        f'if exist "{резерв}" rmdir /s /q "{резерв}"\r\n'
        f'robocopy "{установлена}" "{резерв}" /E /MOVE /NFL /NDL /NJH /NJS /NC /NS >nul\r\n'
        f'robocopy "{новая}" "{установлена}" /E /NFL /NDL /NJH /NJS /NC /NS >nul\r\n'
        f'if not exist "{exe}" robocopy "{резерв}" "{установлена}" /E /MOVE /NFL /NDL /NJH /NJS '
        "/NC /NS >nul\r\n"
        f'start "" "{exe}"\r\n'
    )


def применить(новая: str, установлена: str, exe: str, папка_сценария: str) -> str:
    """Запустить подмену и вернуть путь к .cmd. Программу после этого надо закрыть."""
    os.makedirs(папка_сценария, exist_ok=True)
    путь = os.path.join(папка_сценария, "обновить.cmd")
    with open(путь, "w", encoding="utf-8") as f:
        f.write(сценарий(новая, установлена, exe))
    if sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", путь], close_fds=True,
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    else:                                    # на Linux сценарий только пишется — проверить им нечего
        log.info("обновление: сценарий готов, но подмена — только под Windows: %s", путь)
    return путь


def версия_словами(тег: str = "") -> str:
    номер = re.sub(r"\D", "", тег or "")
    return f"{__version__} (сборка {номер})" if номер else __version__
