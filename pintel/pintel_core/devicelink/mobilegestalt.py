# -*- coding: utf-8 -*-
"""MobileGestalt на всех iOS — через правильный канал, как 3uTools.

MobileGestalt закрыт по классическому пути с iOS 17.4 (libimobiledevice #1542).
Поэтому:
  iOS < 17.4  → DiagnosticsService.mobilegestalt(keys)         (классика, работает)
  iOS ≥ 17.4  → CoreDevice querymobilegestalt поверх userspace-туннеля CoreDeviceProxy
                (pmd-pytcp, БЕЗ прав администратора на Windows и Linux — тот же канал,
                ради которого 3uTools тащит wintun + librxpc + NCM-драйверы)

Ключи дают прямой ответ о подлинности и состоянии деталей независимо от формата
журнала и без действий клиента: FDRSealingStatus (цела ли заводская печать),
IsServicePart (деталь сервисная), аутентификация батареи, серийники модулей,
цвета корпуса (бонус: цвет по кабелю на iOS 17.4+).

Туннель — «по возможности»: не поднялся — не падаем, вердикт по деталям всё равно
даёт IORegistry (canal 1). Ничего не ломаем, если что-то недоступно.
"""
import asyncio

# Печать/подлинность/сервис — прямые признаки замены
SEAL_KEYS = [
    "FDRSealingStatus", "IsServicePart", "DeviceSupportsBatteryModuleAuthentication",
    "TopModuleAuthChipID",
]
# Серийники модулей (для сверки привязки, когда IORegistry их не отдаёт по кабелю)
SERIAL_KEYS = [
    "BatterySerialNumber", "DisplaySerialNumber", "PanelSerialNumber", "ScreenSerialNumber",
    "CoverglassSerialNumber", "MLBSerialNumber", "RearFacingCameraModuleSerialNumber",
    "FrontFacingCameraModuleSerialNumber", "FrontIRCameraModuleSerialNumber",
    "ArcModuleSerialNumber", "MesaSerialNumber", "SavageSerialNumber",
    "AmbientLightSensorSerialNumber", "WirelessChargingSerialNumber",
]
# Цвета корпуса (на iOS 17.4+ только этим путём; на старых — тоже отдаёт)
COLOUR_KEYS = [
    "DeviceColor", "DeviceEnclosureColor", "DeviceCoverGlassColor", "DeviceHousingColor",
    "DeviceBackingColor", "DeviceColorMapPolicy", "ArtworkDeviceSubType", "MarketingProductName",
    "RegionInfo", "RegulatoryModelNumber",
]
DEFAULT_KEYS = SEAL_KEYS + SERIAL_KEYS + COLOUR_KEYS

# «Статус» внутренний у diagnostics — убираем из результата
_DROP = {"Status"}


def _clean(d):
    return {k: v for k, v in (d or {}).items() if k not in _DROP and v is not None}


async def _via_diagnostics(diag, keys):
    """iOS < 17.4: классический diagnostics-канал (мы и так его открыли для IORegistry)."""
    try:
        res = await diag.mobilegestalt(keys)
        return _clean(res), None
    except Exception as e:                                   # noqa: BLE001
        name = type(e).__name__
        if "Deprecat" in name or "Deprecated" in str(e):
            return {}, "deprecated"                          # ожидаемо на iOS 17.4+
        return {}, f"{name}: {str(e)[:120]}"


async def _via_coredevice(serial, keys, timeout):
    """iOS ≥ 17.4: userspace-туннель → CoreDevice querymobilegestalt. Без прав администратора."""
    try:
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
        from pymobiledevice3.remote.core_device.device_info import DeviceInfoService
    except Exception as e:                                   # noqa: BLE001
        return {}, f"нет CoreDevice в pymobiledevice3: {e}", None

    async def run():
        async with UserspaceRsdTunnel(serial=serial, autopair=True,
                                      remotepairing_fallback=False) as rsd:
            info = DeviceInfoService(rsd)
            mg = await info.query_mobilegestalt(keys)
            extra = {}
            try:
                extra = await info.get_device_info() or {}
            except Exception:                                # noqa: BLE001
                pass
            return _clean(mg.get("CacheData") or mg.get("GestaltData") or mg), extra
    try:
        mg, extra = await asyncio.wait_for(run(), timeout)
        return mg, None, extra
    except Exception as e:                                   # noqa: BLE001
        return {}, f"{type(e).__name__}: {str(e)[:150]}", None


async def read(diag, serial=None, keys=None, prefer_tunnel=None, tunnel_timeout=25):
    """Прочитать ключи лучшим доступным каналом.

    prefer_tunnel: None — авто (сначала классика; если deprecated — туннель),
                   False — только классика, True — только туннель.
    → {значения:{...}, канал:'diagnostics|coredevice|нет', ошибка:str|None, device_info:{...}}
    """
    keys = keys or DEFAULT_KEYS
    out = {"значения": {}, "канал": "нет", "ошибка": None, "device_info": None}

    if prefer_tunnel is not True and diag is not None:
        vals, err = await _via_diagnostics(diag, keys)
        if vals:
            out.update(значения=vals, канал="diagnostics")
            return out
        if err and err != "deprecated":
            out["ошибка"] = f"diagnostics: {err}"
        if prefer_tunnel is False:
            out["ошибка"] = out["ошибка"] or (err or "пусто")
            return out

    # сюда попадаем на iOS 17.4+ (deprecated) или при prefer_tunnel=True
    vals, err, extra = await _via_coredevice(serial, keys, tunnel_timeout)
    if vals or extra:
        out.update(значения=vals, канал="coredevice", device_info=extra or None)
        return out
    out["ошибка"] = f"туннель: {err}" if err else (out["ошибка"] or "недоступно")
    return out


def seal_summary(values):
    """Разобрать seal-ключи в понятные флаги. Отсутствие ключа → None (не вывод)."""
    v = values or {}

    def b(x):
        return None if x is None else (bool(x) if not isinstance(x, str) else x.strip().lower() in ("1", "true", "yes", "sealed"))

    fdr = v.get("FDRSealingStatus")
    service = v.get("IsServicePart")
    return {
        "печать_цела": b(fdr),
        "сервисная_деталь": b(service),
        "аутентификация_батареи": b(v.get("DeviceSupportsBatteryModuleAuthentication")),
    }
