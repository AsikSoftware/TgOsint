# -*- coding: utf-8 -*-
"""Следы джейлбрейка — тем же способом, что 3uTools: через AFC пробуем
пути, которых с обычного (запертого в /var/mobile/Media) AFC не видно.
Если путь виден — на телефоне стоит AFC2/джейлбрейк.

Отсутствие доступа — НЕ вердикт: «следов нет» означает лишь, что этим
способом ничего не нашлось.
"""
import asyncio

PATHS = [
    "/var/lib/dpkg/status",             # пакеты Cydia/Sileo
    "/private/var/mobile/appsync",      # AppSync (3uTools проверяет его же)
    "/private/var/mobile/tdmtanf",
    "/Applications/Cydia.app",
    "/Applications/Sileo.app",
    "/Applications/Zebra.app",
    "/var/jb",                          # rootless-джейлбрейки
    "/private/var/lib/apt",
    "/Library/MobileSubstrate",
]


async def probe(ld, timeout=20):
    """→ {проверено, признаки:[пути], ошибки:{путь: текст}} или {проверено: False, ошибка}."""
    try:
        from pymobiledevice3.services.afc import AfcService
    except Exception as e:                                   # noqa: BLE001
        return {"проверено": False, "признаки": [], "ошибка": f"нет AFC в pymobiledevice3: {e}"}

    async def run():
        found, errors = [], {}
        async with AfcService(ld) as afc:
            for p in PATHS:
                try:
                    if await afc.exists(p):
                        found.append(p)
                except Exception as e:                       # noqa: BLE001
                    errors[p] = f"{type(e).__name__}: {str(e)[:80]}"
        return {"проверено": True, "признаки": found, "ошибки": errors}

    try:
        return await asyncio.wait_for(run(), timeout)
    except Exception as e:                                   # noqa: BLE001
        return {"проверено": False, "признаки": [], "ошибка": f"{type(e).__name__}: {str(e)[:120]}"}


def verdict(jb):
    """Текст для отчёта."""
    if not jb or not jb.get("проверено"):
        return "не проверялся" + (f" ({jb.get('ошибка')})" if jb and jb.get("ошибка") else "")
    if jb.get("признаки"):
        return "НАЙДЕНЫ СЛЕДЫ: " + ", ".join(jb["признаки"][:3])
    return "следов нет"
