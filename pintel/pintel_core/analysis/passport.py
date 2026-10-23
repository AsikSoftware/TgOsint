# -*- coding: utf-8 -*-
"""Паспорт аппарата из корневого домена lockdown."""
import json, os, re
from ..devicelink.nodes import txt

MODELS = json.load(open(os.path.join(os.path.dirname(__file__), "models.json"), encoding="utf-8"))

REGIONS = {  # хвост номера модели → регион продажи (основные)
    "LL": "США", "ZA": "Сингапур", "ZP": "Гонконг", "CH": "Китай", "J": "Япония",
    "KH": "Корея", "RU": "Россия", "HN": "Индия", "AE": "ОАЭ", "AB": "Египет/ОАЭ",
    "RM": "Россия/СНГ", "ZD": "Европа", "FD": "Австрия/Лихтенштейн/Швейцария",
    "B": "Великобритания/Ирландия", "X": "Австралия/НЗ", "C": "Канада",
    "TU": "Турция", "KZ": "Казахстан", "MY": "Малайзия", "TH": "Таиланд",
    "VN": "Вьетнам", "ID": "Индонезия", "PH": "Филиппины", "LA": "Латинская Америка",
    "E": "Мексика", "BR": "Бразилия", "AA": "Саудовская Аравия", "QL": "Италия/Испания/Португалия",
    "ZD/A": "Европа",
}


def region_from_model_number(mn):
    """MGJ53RM/A → RM → Россия/СНГ. Хвост — буквы между цифрами и '/'."""
    # Номер модели: 5 знаков (MQ1G3) + 1–2 буквы региона + /A
    m = re.match(r"^[A-Z0-9]{5}([A-Z]{1,2})/[A-Z]$", str(mn or ""))
    if not m:
        return None
    return REGIONS.get(m.group(1))


def build(root):
    r = root or {}
    pt = txt(r.get("ProductType"))
    mn = txt(r.get("ModelNumber")) + txt(r.get("RegionInfo"))
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
        "часовой_пояс": txt(r.get("TimeZone")),
        # DeviceColor равнялся 1 на всех собранных аппаратах — цвет по кабелю
        # не определяется, его даёт только внешняя база.
        "цвет": None,
    }
