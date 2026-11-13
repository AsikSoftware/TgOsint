# -*- coding: utf-8 -*-
"""Самопроверка собранной программы: всё ли, чем читается телефон, загружается.

    pintel-kiosk.exe --selftest <файл>     # 0 — всё загрузилось, 1 — нет; итог в файле

Зачем. Часть модулей связи с iPhone грузится не при запуске, а в момент чтения — внутри
`try`, чтобы одна неудача не роняла всю проверку. Поэтому программа, собранная без нужной
части, запускается, выглядит рабочей и тихо теряет кусок данных.

Так и вышло 13.11.2026 со сборкой doctor-85: библиотека pymobiledevice3 обновилась (11.54),
её модуль чтения отчётов о сбоях стал тянуть пакет pyimg4, а тот при загрузке спрашивает
свою версию у метаданных пакета, которых в собранной программе не было. «Panic full» перестал
читаться на всех точках, взявших сборку, проверка стала «неполной», и бот ни по одной сделке
не называл автоцену. Тесты были зелёные: они гоняют исходники, а не exe.

Эту проверку сборка запускает на готовом exe до релиза. Список модулей — ровно те импорты,
которыми ядро ходит к телефону; тест `tests/test_selfcheck.py` следит, чтобы новый импорт не
забыли сюда дописать.
"""
from __future__ import annotations

import importlib
import sys
import traceback

# модуль → имя, которое из него берёт ядро (None — нужен сам модуль)
МОДУЛИ = (
    ("pymobiledevice3.usbmux", None),
    ("pymobiledevice3.exceptions", "NotPairedError"),
    ("pymobiledevice3.lockdown", "create_using_usbmux"),
    ("pymobiledevice3.services.diagnostics", "DiagnosticsService"),
    ("pymobiledevice3.services.afc", "AfcService"),
    ("pymobiledevice3.services.mobile_config", "MobileConfigService"),
    ("pymobiledevice3.services.syslog", "SyslogService"),
    ("pymobiledevice3.services.crash_reports", "CrashReportsManager"),
    ("pymobiledevice3.remote.userspace_tunnel", "UserspaceRsdTunnel"),
    ("pymobiledevice3.remote.core_device.device_info", "DeviceInfoService"),
    ("qrcode", None),
    ("httpx", None),
)


def проверить() -> list:
    """→ [(модуль, что не так)]. Пустой список — всё загрузилось."""
    беды = []
    for модуль, имя in МОДУЛИ:
        try:
            m = importlib.import_module(модуль)
            if имя and not hasattr(m, имя):
                беды.append((модуль, f"в модуле нет {имя}"))
        except Exception as e:                                   # noqa: BLE001
            беды.append((модуль, f"{type(e).__name__}: {e}"))
    return беды


def main(путь: str | None = None) -> int:
    """Проверить и записать итог в файл (у оконной программы нет консоли). → код возврата."""
    try:
        беды = проверить()
        строки = [f"модулей проверено: {len(МОДУЛИ)}; не загрузилось: {len(беды)}"]
        строки += [f"НЕ ЗАГРУЗИЛСЯ {модуль} :: {что}" for модуль, что in беды]
    except Exception:                                            # noqa: BLE001
        беды, строки = [("selfcheck", "упала сама проверка")], [traceback.format_exc()]
    текст = "\n".join(строки) + "\n"
    if путь:
        with open(путь, "w", encoding="utf-8") as f:
            f.write(текст)
    else:
        sys.stdout.write(текст)
    return 1 if беды else 0
