# -*- coding: utf-8 -*-
"""Бот Оценки: карточка товара МойСклада по новым правилам — и при прежних именах полей.

    python3.13 ms_card_patch.py <каталог бота> --check    # только проверить, ляжет ли
    python3.13 ms_card_patch.py <каталог бота>            # поставить

Сначала положить рядом модуль: `cp ms_card_fields.py <каталог бота>/utils/`.

Зачем. 12.11.2026 владелец перестроил карточку товара в МойСкладе: «Ремонт статус» стал
«Статус» со значениями как кнопки бота, появились «Sim Лоток» галочкой, точные проценты
«АКБ», «Цвет», «Panic full», «Сим без ограничений», «Номер сделки», «Отчёт диагностики».
Бот ищет поля и значения справочников ПО ИМЕНИ, в двух местах:

* автоприёмка при выкупе (`utils/ms_auto_supply.py`) — не найдя поле, молча принимала бы
  телефон без состояния;
* приход из Excel (`utils/ms_prihod_importer.py`) — не найдя поле или значение, отказывает
  всему файлу: «в МойСклад нет доп. поля 'Ремонт статус'».

После этой правки оба места понимают и прежние имена, и новые — поэтому ставить её надо
ДО переименования в МойСкладе, а переименовывать после перезапуска бота. Порядок обратный
— и приход из Excel встанет.

Что именно меняется в файлах бота:

* `ms_auto_supply._soft_attributes` отдаёт сборку полей в `utils/ms_card_fields.py`.
  Прежняя функция остаётся под именем `_soft_attributes_legacy` и вызывается, если новый
  модуль упал: приёмка важнее полей.
* `ms_prihod_importer`: колонка шаблона «Доп. поле: Ремонт статус» принимается и как
  «Доп. поле: Статус»; поле находится по любому из двух имён; значение справочника — по
  прежнему имени и по новому.

Каждая замена обязана лечь ровно один раз, иначе скрипт останавливается, ничего не
записав. Рядом кладутся копии `<файл>.bak_<дата>`.
"""
import datetime
import io
import os
import sys

root = sys.argv[1].rstrip("/")
ТОЛЬКО_ПРОВЕРКА = "--check" in sys.argv
_файлы = {}


def читать(p):
    if p not in _файлы:
        _файлы[p] = io.open(root + p, encoding="utf-8").read()
    return _файлы[p]


def patch(p, pairs, раз=1):
    s = читать(p)
    for old, new in pairs:
        if s.count(old) != раз:
            sys.exit(f"СТОП, ничего не записано: {p} — замена должна лечь {раз} раз(а), "
                     f"а легла бы {s.count(old)}: {old[:70]!r}")
        s = s.replace(old, new)
    _файлы[p] = s


if not os.path.exists(root + "/utils/ms_card_fields.py"):
    sys.exit("СТОП: сначала положите модуль — cp ms_card_fields.py " + root + "/utils/")
if "ms_card_fields" in читать("/utils/ms_auto_supply.py"):
    sys.exit("уже стоит: ms_auto_supply.py отдаёт поля в ms_card_fields — ничего не делаю")

patch("/utils/ms_auto_supply.py", [
    ('''def _soft_attributes(session, device) -> list[dict]:
    """Доп. поля товара. Значение, которого нет в справочнике МойСклада, пропускаем:
''', '''def _soft_attributes(session, device) -> list[dict]:
    """Доп. поля товара собирает utils/ms_card_fields.py: он знает и прежние имена полей
    МойСклада, и новые. Упал — ставим поля прежним кодом: приёмка важнее полей."""
    try:
        from utils import ms_card_fields
        out, skipped = ms_card_fields.поля_товара(
            session, device, запрос=_ms_request, кэш=_cached, pick_imeis=pick_imeis,
            defect_fields=DEFECT_FIELDS, defect_set=defect_set, dict_aliases=DICT_ALIASES)
        _last_skipped.clear()
        _last_skipped.extend(skipped)
        return out
    except Exception as e:
        logger.exception("Автоприёмка: новые доп. поля не собрались (%s) — ставлю по-старому", e)
        return _soft_attributes_legacy(session, device)


def _soft_attributes_legacy(session, device) -> list[dict]:
    """Доп. поля товара. Значение, которого нет в справочнике МойСклада, пропускаем:
'''),
])

patch("/utils/ms_prihod_importer.py", [
    ('''def validate_excel_columns(df: pd.DataFrame) -> None:
    expected = EXPECTED_COLUMNS
    actual = [c for c in df.columns if isinstance(c, str)]
    actual_set = set(actual)

    missing = [c for c in expected if c not in actual_set]
''', '''def _column_present(column: str, actual_set: set) -> bool:
    """Колонка шаблона на месте — под своим именем или под новым: поле в МойСкладе
    переименовали («Ремонт статус» → «Статус»), а файлы приходят и по старому шаблону."""
    if column in actual_set:
        return True
    try:
        from utils import ms_card_fields
        return ms_card_fields.колонка_на_месте(column, actual_set)
    except Exception:
        return False


def validate_excel_columns(df: pd.DataFrame) -> None:
    expected = EXPECTED_COLUMNS
    actual = [c for c in df.columns if isinstance(c, str)]
    actual_set = set(actual)

    missing = [c for c in expected if not _column_present(c, actual_set)]
'''),
    ('''        for a in rows:
            key = _norm_attr_name(a.get("name"))
            if key:
                out[key] = a
        return out
''', '''        for a in rows:
            key = _norm_attr_name(a.get("name"))
            if key:
                out[key] = a
        # поле переименовали в МойСкладе, а колонка в файле названа по-прежнему (или
        # наоборот) — оба имени находят одно и то же поле
        try:
            from utils import ms_card_fields
            ms_card_fields.дописать_прежние_имена(out, _norm_attr_name)
        except Exception as e:
            logger.warning("Приход: прежние имена полей не дописаны (%s)", e)
        return out
'''),
    ('''            data = self.ms_request("GET", f"/entity/customentity/{custom_id}",
                                   params={"filter": f"name={val}", "limit": 1})
            rows = data.get("rows", []) or []
            if not rows:
                return None
''', '''            data = self.ms_request("GET", f"/entity/customentity/{custom_id}",
                                   params={"filter": f"name={val}", "limit": 1})
            rows = data.get("rows", []) or []
            if not rows:
                # значение справочника переименовали («Ранее был ремонт» → «Телефон был в
                # ремонте»), а в файле оно по-прежнему — ищем и под другим именем
                try:
                    from utils import ms_card_fields
                    others = ms_card_fields.другие_имена_значения(val)
                except Exception:
                    others = []
                for other in others:
                    rows = self.ms_request("GET", f"/entity/customentity/{custom_id}",
                                           params={"filter": f"name={other}", "limit": 1}).get("rows") or []
                    if rows:
                        break
            if not rows:
                return None
'''),
])

for p, s in _файлы.items():
    compile(s, root + p, "exec")
изменённые = [p for p, s in _файлы.items() if s != io.open(root + p, encoding="utf-8").read()]
if ТОЛЬКО_ПРОВЕРКА:
    print("проверка: все замены ложатся, изменится файлов:", len(изменённые))
    sys.exit(0)
метка = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
for p in изменённые:
    with open(root + p, "rb") as f:
        прежнее = f.read()
    with open(root + p + ".bak_" + метка, "wb") as f:
        f.write(прежнее)
    io.open(root + p, "w", encoding="utf-8", newline="\n").write(_файлы[p])
    print("записан", p, "(копия .bak_" + метка + ")")
print("готово. Дальше: проверить импорт и перезапустить бота; МойСклад переименовывать "
      "только ПОСЛЕ перезапуска.")
