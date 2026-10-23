# -*- coding: utf-8 -*-
"""Помощники для сырых данных IORegistry/lockdown и имена узлов.

Главное правило (выстрадано на живых аппаратах): имена узлов НЕ угадываем
по поколению — карта `ioreg IOService` отдаёт все имена, и камеру, NVMe
и остальное мы находим в ней по шаблону. Списки ниже — только запасной путь,
когда карта не прочиталась.
"""
import re

# Узлы, которые читаем всегда (имя — точное)
FIXED_NODES = [
    "AppleSmartBattery",            # батарея: ёмкости, циклы, серийник, температура
    "AppleARMBacklight",            # калибровка панели: *Panel vs *Product
    "AppleCLCD2",                   # панель дисплея
    "AppleMultitouchDevice",        # тач: Critical Errors
    "AppleHapticsSupportArcEEPROM", # серийник Taptic (сторона модуля)
    "haptics-support-interface",    # pscl-cal (сторона платы)
    "AppleProxHIDEventDriver",      # серийник датчика приближения
    "product",                      # coverglass / raw-panel serial, rosaline
    "device-tree",
    "options",                      # fm-activation-locked (второй канал Find My)
    "AIDBus",                       # TRM_TransportSupervised (MDM)
    "AppleBatteryAuth",
    "AppleSMCCharger",
]

# Запасные имена, если карта узлов недоступна
CAMERA_FALLBACK = ["AppleH13CamIn", "AppleH10CamIn", "AppleH14CamIn",
                   "AppleH16CamIn", "AppleH17CamIn", "AppleCamera"]
NVME_FALLBACK = ["AppleANS3NVMeController", "AppleANS2NVMeController",
                 "AppleANS3CGv2Controller", "AppleANS2CGv2Controller",
                 "AppleANS2CGNVMeController", "AppleANS4NVMeController",
                 "AppleEmbeddedNVMeController"]

CAMERA_RE = re.compile(r"^Apple(H\d+CamIn|Camera)$")
NVME_RE = re.compile(r"^Apple(ANS\d\w*(NVMe)?Controller|EmbeddedNVMeController)$")

# Узлы «по возможности»: имена взяты из того, что спрашивает у телефона 3uTools
# (idm_info.dll). Нет узла — не ошибка, просто None.
OPTIONAL_NODES = {
    "wifi":      (re.compile(r"^AppleBCMWLAN(Core|BusInterface)?$"), ["AppleBCMWLANCore"]),
    "touchid":   (re.compile(r"^AppleMesa"), ["AppleMesa"]),
    "port":      (re.compile(r"^Apple(TriStar|SandDollar|HPM|ACE)\w*$"), ["AppleTriStarBuiltIn", "AppleSandDollar"]),
    "accessory": (re.compile(r"^IOAccessoryManager$"), ["IOAccessoryManager"]),
}

# Ключи MobileGestalt (до iOS 17.4 телефон отдаёт их через diagnostics;
# новее — нет, 3uTools ради них поднимает RemoteXPC-туннель). Запрашиваем
# «по возможности»: цвета корпуса, серийники модулей, Wi-Fi.
MG_KEYS_COLOUR = ["DeviceColor", "DeviceEnclosureColor", "DeviceCoverGlassColor",
                  "DeviceHousingColor", "DeviceBackingColor", "MarketingProductName"]
MG_KEYS = MG_KEYS_COLOUR + [
    "WifiVendor", "WifiChipset", "WifiFirmwareVersion", "WifiAntennaSKUVersion",
    "BatterySerialNumber", "MLBSerialNumber", "WirelessBoardSnum", "BasebandSerialNumber",
    "ArcModuleSerialNumber", "LunaFlexSerialNumber", "LynxSerialNumber", "MesaSerialNumber",
    "SavageSerialNumber", "RosalineSerialNumber", "JasperSNUM", "YonkersSerialNumber",
    "PanelSerialNumber", "RawPanelSerialNumber", "CoverglassSerialNumber",
    "AmbientLightSensorSerialNumber", "BackCameraModuleSerialNumString",
    "FrontCameraModuleSerialNumString", "BackSuperWideCameraModuleSerialNumString",
    "BackTeleCameraModuleSerialNumString", "FrontIRCameraModuleSerialNumString",
    "FrontIRStructuredLightProjectorSerialNumString", "NFCUniqueChipID", "DieId",
]

# Код DeviceEnclosureColor → цвет корпуса (обобщённо; точное маркетинговое имя
# зависит от модели и приходит из Sickw). Сводка по таблице моделей 3uTools.
ENCLOSURE_COLOURS = {
    1: "чёрный / графитовый", 2: "белый / серебристый", 3: "золотой", 4: "розовый / розовое золото",
    5: "натуральный титан / jet black", 6: "красный", 7: "жёлтый", 8: "оранжевый / коралловый",
    9: "синий", 17: "фиолетовый", 18: "зелёный",
}

# Lockdown-домены, которые снимаем целиком (значения — в слепок)
DOMAINS = [
    "com.apple.disk_usage",          # TotalDiskCapacity, TotalDataAvailable, NANDInfo
    "com.apple.mobile.battery",      # BatteryCurrentCapacity, BatteryIsCharging
    "com.apple.fmip",                # Find My: IsAssociated (если домен отдаётся)
    "com.apple.mobile.restriction",
    "com.apple.purplebuddy",         # SetupDone — прошёл ли аппарат первичную настройку
    "com.apple.international",
    "com.apple.mobile.iTunes",
    "com.apple.mobile.internal",
    "com.apple.mobile.software_behavior",
    "com.apple.mobile.wireless_lockdown",
    "com.apple.mobile.data_sync",
    "com.apple.mobile.backup",
    "com.apple.mobile.sync_data_class",
    "com.apple.mobile.user_preferences",
    "com.apple.mobile.chaperone",
    "com.apple.mobile.third_party_termination",
    "com.apple.mobile.tethered_sync",
    "com.apple.mobile.lockdown_cache",
    "com.apple.mobile.debug",
    "com.apple.xcode.developerdomain",
    "com.apple.Accessibility",
    "com.apple.iqagent",
    "com.apple.fairplay",
]


def deep(o, key):
    """Ключ на любой глубине: Apple прячет нужное во вложенных разделах."""
    if isinstance(o, dict):
        if key in o and not isinstance(o[key], (dict, list)):
            return o[key]
        for v in o.values():
            r = deep(v, key)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = deep(v, key)
            if r is not None:
                return r
    return None


def txt(v):
    """Серийники приходят байтами с нулём на конце; строки — как есть."""
    if isinstance(v, (bytes, bytearray)):
        s = bytes(v).rstrip(b"\x00")
        try:
            return s.decode("ascii")
        except Exception:
            return ""
    if v is None:
        return ""
    return str(v)


def num(v):
    if isinstance(v, bool):
        return int(v)
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return 0


def boolish(v):
    """'True'/'YES'/1 → True; 'False'/'NO'/0 → False; иначе None."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = txt(v).strip().upper()
    if s in ("TRUE", "YES", "1"):
        return True
    if s in ("FALSE", "NO", "0"):
        return False
    return None


_NAME_KEYS = ("IORegistryEntryName", "IOObjectClass", "IOClass", "name", "class")
_STRUCT_KEYS = {"children", "IORegistryEntryChildren", "properties"}


def collect_entry_names(tree):
    """Все имена узлов из дампа плана IORegistry.

    Диагностический сервис отдаёт план как дерево {"children": [узел, …]},
    где у узла имя лежит в поле (IORegistryEntryName / name / IOClass), а не
    в ключе словаря. Собираем и такие поля, и ключи-словари (старый формат) —
    лишние имена безвредны, пропущенные — ломают поиск камеры и NVMe."""
    names = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in _NAME_KEYS and isinstance(v, (str, bytes)):
                    names.add(txt(v))
                if isinstance(v, (dict, list)):
                    if k not in _STRUCT_KEYS:
                        names.add(str(k))
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(tree)
    names.discard("")
    return names


def pick_names(names, pattern, fallback):
    """Имена узлов по шаблону из карты; если карты нет — запасной список."""
    found = sorted(n for n in names if pattern.match(n))
    return found or list(fallback)
