# -*- coding: utf-8 -*-
"""Тесты разбора прайса из Google Таблицы. Запуск: python tests/test_gsheet.py
Без сети: проверяется только парсер, на синтетических CSV обоих форматов."""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import gsheet

models = json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                     "core", "models.json"), encoding="utf-8"))


def P(rows):
    b, w, u = gsheet.parse(rows, models)
    return b, u

# Формат 1: модели в строках, объёмы в шапке столбцов
csv1 = """Прайс выкупа,,,,
Модель,64,128 GB,256,512
iPhone 12,95000,110 000,125000,
iPhone 13 Pro Max,, 230 000 ₸,255000,290000
Айфон 14 Про,,230000,255 000,290000
iPhone 99 Ultra,,111,222,
Samsung S23,1,2,3,4
"""
base, unk = P(csv1)
assert base["iPhone13,2"] == {"64": 95000, "128": 110000, "256": 125000}, base
assert base["iPhone14,3"]["128"] == 230000 and base["iPhone14,3"]["512"] == 290000
assert base["iPhone15,2"]["256"] == 255000
assert any("iPhone 99" in u for u in unk), unk          # незнакомая модель не выдумывается

# Формат 2: объём прямо в названии, цена в той же строке
csv2 = """что,цена
iPhone 13 128 ГБ,150 000
iPhone 13 256GB,170000 тг
iPhone SE 2020 64 gb,45000
айфон 12 про макс 1 ТБ,210000
"""
base2, unk2 = P(csv2)
assert base2["iPhone14,5"] == {"128": 150000, "256": 170000}, base2
assert base2["iPhone12,8"]["64"] == 45000
assert base2["iPhone13,4"]["1024"] == 210000
assert not unk2, unk2

# Одно имя — несколько кодов (iPhone 8), и шапка из одного столбца
base3, _ = P("Модель,64\niPhone 8,40000\n")
assert base3["iPhone10,1"]["64"] == 40000 and base3["iPhone10,4"]["64"] == 40000

# Ссылка превращается в CSV-экспорт с тем же gid
u = gsheet.export_url("https://docs.google.com/spreadsheets/d/ABC123/edit?gid=777#gid=777")
assert u == "https://docs.google.com/spreadsheets/d/ABC123/export?format=csv&gid=777", u

print("OK: все тесты парсера прайса прошли")

# Новые форматы: объём без единицы; «модель | объём | цена»; шапка «Цена 128»
b4, _ = P("iPhone 13 Pro Max 256,450 000\niPhone 16 128, 300000\n")
assert b4["iPhone14,3"]["256"] == 450000, b4
assert b4["iPhone17,3"]["128"] == 300000, b4          # «16» — номер модели, «128» — объём

b5, _ = P("что,объём,цена\niPhone 13,128,150000\nАйфон 12 Про,256,180000\n")
assert b5["iPhone14,5"]["128"] == 150000, b5
assert b5["iPhone13,3"]["256"] == 180000, b5

b6, _ = P("Модель,Цена 128,Цена 256\niPhone 12,95000,110000\n")
assert b6["iPhone13,2"] == {"128": 95000, "256": 110000}, b6

print("OK: новые форматы прайса распознаются")

# Сетка по износу батареи (формат прайса магазина)
csvW = """Модель,Марка,Память,нет информации,0-74,75-79,80-85,86-90,91-95,96-99,100,100 (0-30)
Apple,iPhone 17 Pro Max,256,,,,,,470000,490000,510000,510000
Apple,iPhone 17 Pro Max (Esim),256,,,,,,430000,450000,460000,460000
Apple,iPhone 13,128,100000,,,110000,120000,130000,140000,150000,160000
"""
bw, ww, uw = gsheet.parse(csvW, models)
assert bw["iPhone18,2"]["256"] == 510000, bw           # идеал = колонка 100
assert ww["iPhone18,2"]["256"]["91-95"] == 470000, ww
assert ww["iPhone14,5"]["128"]["неизвестно"] == 100000
assert ww["iPhone14,5"]["128"]["100новый"] == 160000
assert "iPhone18,2" in bw and bw["iPhone18,2"]["256"] != 460000  # esim не перетёр
assert any("esim" in u for u in uw), uw

# Выбор цены по фактическому износу
from core import price
_orig_load = price.load
price.load = lambda: {"валюта": "₸", "база": bw, "сетка_износа": ww,
                      "вычеты": {"износ_батареи_ниже_80": -15000,
                                 "износ_батареи_ниже_85": -7000,
                                 "циклов_больше_800": -5000,
                                 "батарея_неоригинал": -25000,
                                 "экран_заменён": -40000, "экран_под_вопросом": -15000,
                                 "камера_заменена": -30000, "face_id_заменён": -35000,
                                 "taptic_заменён": -8000, "память_перепаяна": -60000,
                                 "заднее_стекло_заменено": -20000, "корпус_заменён": -25000,
                                 "плата_заменена": -70000, "деталь_бу_по_apple": -10000,
                                 "нет_гарантии_apple": 0},
                      "отказ": {"чёрный_список": "х", "mdm": "х", "данные_подменены": "х"}}
def _res(wear, cycles, pt="iPhone14,5", gb=128):
    return {"паспорт": {"код_модели": pt, "память_гб": gb},
            "батарея": {"износ": wear, "циклы": cycles},
            "детали": {}, "юридический": {"mdm": False, "каналы_сошлись": True}}
e = price.estimate(_res(93, 200));  assert e["итого"] == 130000, e   # 91-95
e = price.estimate(_res(100, 10));  assert e["итого"] == 160000, e   # 100 (0-30)
e = price.estimate(_res(100, 400)); assert e["итого"] == 150000, e   # 100
e = price.estimate(_res(None, None)); assert e["итого"] == 100000, e # нет информации
e = price.estimate(_res(77, 300))                                    # 75-79 пуст
assert e["итого"] is None and any("не задаёт цену" in s for s in e["чего_не_хватает"]), e
price.load = _orig_load
print("OK: сетка износа и выбор цены по износу работают")
