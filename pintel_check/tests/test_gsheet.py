# -*- coding: utf-8 -*-
"""Тесты разбора прайса из Google Таблицы. Запуск: python tests/test_gsheet.py
Без сети: проверяется только парсер, на синтетических CSV обоих форматов."""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import gsheet

models = json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                     "core", "models.json"), encoding="utf-8"))

# Формат 1: модели в строках, объёмы в шапке столбцов
csv1 = """Прайс выкупа,,,,
Модель,64,128 GB,256,512
iPhone 12,95000,110 000,125000,
iPhone 13 Pro Max,, 230 000 ₸,255000,290000
Айфон 14 Про,,230000,255 000,290000
iPhone 99 Ultra,,111,222,
Samsung S23,1,2,3,4
"""
base, unk = gsheet.parse(csv1, models)
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
base2, unk2 = gsheet.parse(csv2, models)
assert base2["iPhone14,5"] == {"128": 150000, "256": 170000}, base2
assert base2["iPhone12,8"]["64"] == 45000
assert base2["iPhone13,4"]["1024"] == 210000
assert not unk2, unk2

# Одно имя — несколько кодов (iPhone 8), и шапка из одного столбца
base3, _ = gsheet.parse("Модель,64\niPhone 8,40000\n", models)
assert base3["iPhone10,1"]["64"] == 40000 and base3["iPhone10,4"]["64"] == 40000

# Ссылка превращается в CSV-экспорт с тем же gid
u = gsheet.export_url("https://docs.google.com/spreadsheets/d/ABC123/edit?gid=777#gid=777")
assert u == "https://docs.google.com/spreadsheets/d/ABC123/export?format=csv&gid=777", u

print("OK: все тесты парсера прайса прошли")

# Новые форматы: объём без единицы; «модель | объём | цена»; шапка «Цена 128»
b4, _ = gsheet.parse("iPhone 13 Pro Max 256,450 000\niPhone 16 128, 300000\n", models)
assert b4["iPhone14,3"]["256"] == 450000, b4
assert b4["iPhone17,3"]["128"] == 300000, b4          # «16» — номер модели, «128» — объём

b5, _ = gsheet.parse("что,объём,цена\niPhone 13,128,150000\nАйфон 12 Про,256,180000\n", models)
assert b5["iPhone14,5"]["128"] == 150000, b5
assert b5["iPhone13,3"]["256"] == 180000, b5

b6, _ = gsheet.parse("Модель,Цена 128,Цена 256\niPhone 12,95000,110000\n", models)
assert b6["iPhone13,2"] == {"128": 95000, "256": 110000}, b6

print("OK: новые форматы прайса распознаются")
