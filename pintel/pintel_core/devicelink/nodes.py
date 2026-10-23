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


def collect_entry_names(tree):
    """Все имена узлов из карты плана IOService (вложенный словарь)."""
    names = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, (dict, list)):
                    names.add(str(k))
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(tree)
    return names


def pick_names(names, pattern, fallback):
    """Имена узлов по шаблону из карты; если карты нет — запасной список."""
    found = sorted(n for n in names if pattern.match(n))
    return found or list(fallback)
