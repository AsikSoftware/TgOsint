# -*- coding: utf-8 -*-
"""Бот Оценки: занятый номер приёмки больше не оставляет документ непроведённым.

    python3.13 supply_number_patch.py <каталог бота> --check    # только проверить, ляжет ли
    python3.13 supply_number_patch.py <каталог бота>            # поставить

Сначала положить рядом модуль: `cp ms_supply_number.py <каталог бота>/utils/`.

Зачем. 21.11.2026, сделка 17476: документ приёмки № 80879 создался, позиция встала, а
провести МойСклад не дал — «нарушено ограничение уникальности параметра 'name'». Живая
приёмка с таким номером была ровно одна, наша: номер держала удалённая. В ту же секунду
приёмку руками создавал сотрудник, ей достался 80880. Сотрудник дважды нажал кнопку — оба
раза тот же отказ, документ так и висел непроведённым, а телефон на 140 000 ₸ не был принят.

Что меняется. Отказ именно про номер (и только он) больше не бросает документ: бот берёт
следующий свободный номер, ставит его ЭТОМУ ЖЕ документу и проводит. Второго документа не
появляется, товар и деньги те же, наружу бот называет итоговый номер — по нему ищет сверка.

Проверено на боевом вручную: застрявший 80879 провёлся под номером 80881, сумма и позиция
те же. Правила подбора номера проверены тестами без сети: tests/test_ms_supply_number.py.

Замена обязана лечь ровно один раз, иначе скрипт останавливается, ничего не записав.
Рядом кладётся копия `<файл>.bak_<дата>`.
"""
import datetime
import io
import os
import sys

root = sys.argv[1].rstrip("/")
ТОЛЬКО_ПРОВЕРКА = "--check" in sys.argv
_файлы = {}

ФАЙЛ = "/utils/ms_auto_supply.py"


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


if not os.path.exists(root + "/utils/ms_supply_number.py"):
    sys.exit("СТОП: сначала положите модуль — cp ms_supply_number.py " + root + "/utils/")
if "ms_supply_number" in читать(ФАЙЛ):
    sys.exit("уже стоит: автоприёмка умеет брать свободный номер — ничего не делаю")

patch(ФАЙЛ, [
    ('''        # проводим в последнюю очередь, когда позиция уже на месте
        if post:
            try:
                _ms_request(session, "PUT", f"/entity/supply/{supply['id']}",
                            body={"applicable": True})
            except Exception as e:''',
     '''        # проводим в последнюю очередь, когда позиция уже на месте
        if post:
            try:
                try:
                    _ms_request(session, "PUT", f"/entity/supply/{supply['id']}",
                                body={"applicable": True})
                except Exception as номер_занят:
                    # Номер документа занят — обычно его держит удалённая приёмка: номер она
                    # счётчику отдаёт, а из-под себя не отпускает (21.11.2026, сделка 17476).
                    # Бросать из-за этого готовый документ нельзя: телефон остаётся непринятым.
                    from utils import ms_supply_number
                    if not ms_supply_number.это_занятый_номер(номер_занят):
                        raise
                    новый = ms_supply_number.свободный_номер(
                        lambda метод, путь, params=None: _ms_request(
                            session, метод, путь, params=params))
                    logger.warning("Автоприёмка: номер %s занят, провожу под номером %s",
                                   supply.get("name"), новый)
                    supply = _ms_request(session, "PUT", f"/entity/supply/{supply['id']}",
                                         body={"name": новый, "applicable": True})
            except Exception as e:'''),
])

for p, s in _файлы.items():
    compile(s, root + p, "exec")
изменённые = [p for p, s in _файлы.items() if s != io.open(root + p, encoding="utf-8").read()]
if ТОЛЬКО_ПРОВЕРКА:
    print("проверка: замена ложится, изменится файлов:", len(изменённые))
    sys.exit(0)
метка = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
for p in изменённые:
    with open(root + p, "rb") as f:
        прежнее = f.read()
    with open(root + p + ".bak_" + метка, "wb") as f:
        f.write(прежнее)
    io.open(root + p, "w", encoding="utf-8", newline="\n").write(_файлы[p])
    print("записан", p, "(копия .bak_" + метка + ")")
print("готово. Дальше: проверить импорт (python3 -c 'from utils import ms_auto_supply') "
      "и перезапустить бота.")
