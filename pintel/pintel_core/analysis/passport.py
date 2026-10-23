# -*- coding: utf-8 -*-
"""Паспорт аппарата из корневого домена lockdown."""
import json, os, re
from ..devicelink.nodes import boolish, txt

MODELS = json.load(open(os.path.join(os.path.dirname(__file__), "models.json"), encoding="utf-8"))

# Хвост номера модели → регион продажи. Таблица сведена по открытым спискам
# (The Apple Wiki «Model Regions», подборки 2026 г.) и 228 реальным аппаратам
# из кэша 3uTools. Код у Apple может «переезжать» между поколениями, поэтому в
# отчёте всегда показываем и сам код.
REGIONS = {
    "LL": "США", "VC": "Канада", "C": "Канада", "CL": "Канада", "E": "Мексика",
    "LA": "Латинская Америка", "LE": "Аргентина", "LZ": "Чили/Парагвай/Уругвай",
    "BR": "Бразилия", "BZ": "Бразилия", "ZQ": "Ямайка",
    "RK": "Казахстан", "KZ": "Казахстан", "RM": "Россия/СНГ", "RU": "Россия", "RS": "Россия",
    "RP": "Россия", "RR": "Россия/Молдова", "SU": "Украина", "TU": "Турция",
    "ZD": "Европа", "B": "Великобритания/Ирландия", "BT": "Великобритания", "QN": "Северная Европа",
    "D": "Германия", "DN": "Германия/Австрия/Нидерланды", "NF": "Бельгия/Франция/Люксембург",
    "F": "Франция", "FB": "Франция/Люксембург", "FD": "Австрия/Лихтенштейн/Швейцария",
    "T": "Италия", "IP": "Италия", "TY": "Италия", "Y": "Испания", "QL": "Италия/Испания/Португалия",
    "PO": "Португалия", "PL": "Польша", "PM": "Польша", "LP": "Польша", "HX": "Венгрия/Восточная Европа",
    "HU": "Венгрия", "MG": "Венгрия", "GH": "Венгрия", "SX": "Чехия", "CZ": "Чехия", "CS": "Чехия/Словакия",
    "CN": "Словакия", "SL": "Словакия", "CR": "Хорватия", "CM": "Хорватия/Венгрия", "RO": "Румыния/Молдова",
    "BG": "Болгария", "GR": "Греция", "GB": "Греция", "MM": "Черногория/Македония/Албания", "SE": "Сербия",
    "EE": "Эстония", "ET": "Эстония", "LV": "Латвия", "FS": "Финляндия", "KS": "Финляндия/Швеция",
    "KN": "Дания/Норвегия", "HB": "Израиль",
    "AE": "ОАЭ", "AB": "Египет/Иордания/Саудовская Аравия/ОАЭ", "AA": "Саудовская Аравия",
    "AH": "Бахрейн/Кувейт", "SO": "ЮАР",
    "HN": "Индия", "CH": "Китай", "ZP": "Гонконг/Макао", "ZA": "Сингапур", "MY": "Малайзия",
    "TA": "Тайвань", "J": "Япония", "JP": "Япония", "KH": "Корея", "TH": "Таиланд", "VN": "Вьетнам",
    "ID": "Индонезия", "PA": "Индонезия", "PP": "Филиппины", "X": "Австралия/НЗ",
}

_MN_RE = re.compile(r"^[A-Z0-9]{5}([A-Z]{1,2})/[A-Z]$")


def region_code(mn):
    """MGJ53RM/A → RM."""
    m = _MN_RE.match(str(mn or ""))
    return m.group(1) if m else None


def region_from_model_number(mn):
    """MGJ53RM/A → «Россия/СНГ (RM)»; неизвестный код → «не распознан (XX)»."""
    code = region_code(mn)
    if not code:
        return None
    name = REGIONS.get(code)
    return f"{name} ({code})" if name else f"не распознан ({code})"


def sim_status(r):
    """Что в лотке. По 228 реальным аппаратам: SIMTrayStatus надёжнее SIMStatus
    (тот описывает первый логический слот, который может быть eSIM)."""
    st = txt(r.get("SIMStatus"))
    tray = txt(r.get("SIMTrayStatus"))
    if "TrayAbsent" in tray:
        return "лотка нет (eSIM-only)"
    if "InsertedWithSIM" in tray:
        return "в лотке SIM-карта"
    if "NoSIM" in tray or "NotInserted" in st:
        return "SIM не вставлена"
    if "Ready" in st:
        return "SIM есть"
    return st or None


def esim_profile(r):
    """Есть ли на телефоне eSIM-профиль: у встроенного слота (SIMnIsEmbedded)
    есть ICCID. SIM1IsEmbedded=true встречается и при физической SIM в лотке —
    это лишь означает, что первый логический слот — eSIM."""
    e1, e2 = boolish(r.get("SIM1IsEmbedded")), boolish(r.get("SIM2IsEmbedded"))
    i1 = bool(txt(r.get("IntegratedCircuitCardIdentity")))
    i2 = bool(txt(r.get("IntegratedCircuitCardIdentity2")))
    return bool((e1 is True and i1) or (e2 is True and i2))


def build(root):
    from .serials import device_production
    r = root or {}
    pt = txt(r.get("ProductType"))
    mn = txt(r.get("ModelNumber")) + txt(r.get("RegionInfo"))
    prod = device_production(r.get("SerialNumber"), pt)
    return {
        "модель": MODELS.get(pt, f"{pt} — модель не в справочнике"),
        "код_модели": pt,
        "номер_модели": mn,
        "регион": region_from_model_number(mn),
        "серийник": txt(r.get("SerialNumber")),
        "серийник_платы": txt(r.get("MLBSerialNumber")),
        "imei": txt(r.get("InternationalMobileEquipmentIdentity")),
        "imei2": txt(r.get("InternationalMobileEquipmentIdentity2")),
        "meid": txt(r.get("MobileEquipmentIdentifier")),
        "udid": txt(r.get("UniqueDeviceID")),
        "ecid": txt(r.get("UniqueChipID")),
        "ios": txt(r.get("ProductVersion")),
        "сборка": txt(r.get("BuildVersion")),
        "имя_устройства": txt(r.get("DeviceName")),
        "чип": txt(r.get("ChipID")) or txt(r.get("HardwareModel")),
        "модем": txt(r.get("BasebandVersion")),
        "wifi_mac": txt(r.get("WiFiAddress")),
        "bluetooth_mac": txt(r.get("BluetoothAddress")),
        "cellular_mac": txt(r.get("EthernetAddress")),
        "sim": sim_status(r),
        "sim_в_лотке": "InsertedWithSIM" in txt(r.get("SIMTrayStatus")),
        "esim_only": "TrayAbsent" in txt(r.get("SIMTrayStatus")),
        "esim": esim_profile(r),
        "код_региона": region_code(mn),
        "выпуск": (f'{prod["год"]}, неделя {prod["неделя"]}' if prod else None),
        "модель_apple": txt(r.get("HardwareModel")),
        "часовой_пояс": txt(r.get("TimeZone")),
        # DeviceColor равнялся 1 на всех собранных аппаратах — цвет по кабелю
        # не определяется, его даёт только внешняя база.
        "цвет": None,
    }
