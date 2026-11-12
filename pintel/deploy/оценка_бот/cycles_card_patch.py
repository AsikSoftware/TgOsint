# -*- coding: utf-8 -*-
"""Бот Оценки: циклы батареи в сделке и в карточке товара МойСклада.

    python3.13 cycles_card_patch.py <каталог бота> --check     # только проверить, ляжет ли
    python3.13 cycles_card_patch.py <каталог бота> --column    # добавить колонку в базу
    python3.13 cycles_card_patch.py <каталог бота>             # поставить (колонка уже есть)

Что меняется.

* **Сделка.** У `devices` появляется колонка `akb_cycles` (целое, пусто по умолчанию). Циклы
  читает касса по кабелю и присылает в посылке; у сделок, заведённых продавцом в боте, их
  нет, и карточка для них выглядит как раньше.
* **Карточка сделки.** «Состояние АКБ: 79% · циклов: 1719» — там же, где процент.
* **МойСклад.** Поле товара «Цикл» (оно в МойСкладе уже есть, тип «целое») заполняется из
  сделки. Для числовых полей значение теперь уходит числом, а не строкой — раньше таких
  полей в списке не было, и строку на числовое поле МойСклад отклонил бы вместе со всем
  товаром.
* **Необязательные поля.** «Цвет», «Panic full», «Сим без ограничений», «Номер сделки»
  заполняются, ЕСЛИ такое поле заведено в МойСкладе; нет поля — молча пропускаем, и в
  списке «пропущены доп. поля» оно не появляется. Так карточку товара можно дополнять в
  самом МойСкладе, не трогая бота.

Чужих товаров правка не касается: поля ставятся только тому товару, который бот создаёт
или находит по штрихкоду при выкупе, — как и раньше.

Порядок важен: **сначала колонка, потом код**. Модель с полем, которого нет в базе, роняет
любое чтение сделки. Поэтому без колонки установка останавливается.

Правка своих файлов бота заменами: каждая обязана лечь ровно один раз, иначе скрипт
останавливается, ничего не записав. Рядом кладутся копии `<файл>.bak_<дата>`.
"""
import datetime
import io
import os
import subprocess
import sys

root = sys.argv[1].rstrip("/")
ТОЛЬКО_ПРОВЕРКА = "--check" in sys.argv
КОЛОНКА = "--column" in sys.argv
_файлы = {}

ПРИМЕНИТЬ = "/database/apply_akb_cycles_field.py"
ПРИМЕНИТЬ_ТЕКСТ = '''import asyncio

from sqlalchemy import text

from database.engine import async_engine


ALTER_STATEMENTS = [
    # циклы батареи: читает касса по кабелю; у сделок из бота пусто
    'ALTER TABLE "devices" ADD COLUMN IF NOT EXISTS "akb_cycles" INTEGER',
]


async def ensure_akb_cycles_field() -> None:
    async with async_engine.begin() as conn:
        for statement in ALTER_STATEMENTS:
            await conn.execute(text(statement))


if __name__ == "__main__":
    asyncio.run(ensure_akb_cycles_field())
'''

ЕСТЬ_ЛИ_КОЛОНКА = '''
import asyncio
from sqlalchemy import text
from database.engine import async_engine

async def main():
    async with async_engine.connect() as conn:
        есть = (await conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'devices' AND column_name = 'akb_cycles'"))).scalar()
    print("КОЛОНКА_ЕСТЬ" if есть else "КОЛОНКИ_НЕТ")

asyncio.run(main())
'''


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


def колонка_есть() -> bool:
    """Спрашиваем базу тем же движком, что и бот: его настройки, его интерпретатор."""
    ответ = subprocess.run([sys.executable, "-c", ЕСТЬ_ЛИ_КОЛОНКА], cwd=root,
                           capture_output=True, text=True, timeout=60)
    if "КОЛОНКА_ЕСТЬ" in ответ.stdout:
        return True
    if "КОЛОНКИ_НЕТ" in ответ.stdout:
        return False
    sys.exit("СТОП: базу спросить не вышло — " + (ответ.stderr.strip().splitlines() or ["?"])[-1][:200])


if КОЛОНКА:
    if not os.path.exists(root + ПРИМЕНИТЬ):
        io.open(root + ПРИМЕНИТЬ, "w", encoding="utf-8", newline="\n").write(ПРИМЕНИТЬ_ТЕКСТ)
        print("записан", ПРИМЕНИТЬ)
    if колонка_есть():
        print("колонка devices.akb_cycles уже есть — ничего не делаю")
        sys.exit(0)
    итог = subprocess.run([sys.executable, root + ПРИМЕНИТЬ], cwd=root,
                          capture_output=True, text=True, timeout=120)
    if итог.returncode:
        sys.exit("СТОП: колонку добавить не вышло — "
                 + (итог.stderr.strip().splitlines() or ["?"])[-1][:300])
    print("колонка devices.akb_cycles добавлена" if колонка_есть()
          else "СТОП: команда прошла, а колонки нет — смотрите базу")
    sys.exit(0)

if "akb_cycles" in читать("/database/models.py"):
    sys.exit("уже стоит: в database/models.py есть akb_cycles — ничего не делаю")

patch("/database/models.py", [
    ('''    akb_exact: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
''', '''    akb_exact: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # циклы батареи: читает касса по кабелю и присылает в посылке; у сделок из бота пусто
    akb_cycles: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
'''),
])

patch("/utils/utils.py", [
    ('''def akb_text(device) -> str:
    """АКБ в карточке: точный процент; у старых сделок без него — что записано."""
    exact = getattr(device, "akb_exact", None)
    return f"{exact}%" if exact else str(getattr(device, "akb", None) or "-")
''', '''def akb_text(device) -> str:
    """АКБ в карточке: точный процент; у старых сделок без него — что записано.
    Циклы — когда их прочитала касса: у сделок, заведённых в боте, их нет."""
    exact = getattr(device, "akb_exact", None)
    text = f"{exact}%" if exact else str(getattr(device, "akb", None) or "-")
    cycles = getattr(device, "akb_cycles", None)
    return f"{text} · циклов: {cycles}" if cycles is not None else text
'''),
])

patch("/utils/ms_auto_supply.py", [
    ('''    # способ покупки в карточке товара — тот же, что и в документе приёмки
    trade_type = (getattr(device, "trade_type", "") or "").strip()
    wanted["Способ приобретения"] = "Выкуп" if trade_type == "Выкуп" else "Trade-In"
''', '''    # способ покупки в карточке товара — тот же, что и в документе приёмки
    trade_type = (getattr(device, "trade_type", "") or "").strip()
    wanted["Способ приобретения"] = "Выкуп" if trade_type == "Выкуп" else "Trade-In"

    # циклы батареи: читает касса по кабелю; у сделок из бота их нет — поле не трогаем
    wanted["Цикл"] = getattr(device, "akb_cycles", None)

    # То, что есть в карточке сделки, а отдельного поля в МойСкладе может не быть. Заведут
    # поле с таким именем — начнёт заполняться само; нет поля — молча пропускаем.
    sim_free = getattr(device, "sim_free", None)
    panic = getattr(device, "panic_full", None)
    optional = {
        "Цвет": (getattr(device, "color", "") or "").strip() or None,
        "Panic full": None if panic is None else ("Да" if panic else "Нет"),
        "Сим без ограничений": None if sim_free is None else ("Да" if sim_free else "Нет"),
        "Номер сделки": getattr(device, "id", None),
    }
    wanted.update(optional)
'''),
    ('''        row = by_name.get(name)
        if not row:
            skipped.append(name)
            continue
        a_type = (row.get("type") or "").lower()
        if a_type == "boolean":
            out.append({"meta": row["meta"], "value": bool(value)})
            continue
        if a_type in ("string", "text", "long", "double"):
            out.append({"meta": row["meta"], "value": str(value)})
            continue
''', '''        row = by_name.get(name)
        if not row:
            if name not in optional:
                skipped.append(name)
            continue
        a_type = (row.get("type") or "").lower()
        if a_type == "boolean":
            out.append({"meta": row["meta"], "value": value in (True, "Да") if name in optional
                        else bool(value)})
            continue
        if a_type in ("long", "double"):
            # числовому полю — число: строку МойСклад отклонит вместе со всем товаром
            try:
                out.append({"meta": row["meta"],
                            "value": int(value) if a_type == "long" else float(value)})
            except (TypeError, ValueError):
                skipped.append(f"{name}={value}")
            continue
        if a_type in ("string", "text"):
            out.append({"meta": row["meta"], "value": str(value)})
            continue
'''),
])

for p, s in _файлы.items():
    compile(s, root + p, "exec")
изменённые = [p for p, s in _файлы.items() if s != io.open(root + p, encoding="utf-8").read()]
if ТОЛЬКО_ПРОВЕРКА:
    print("проверка: все замены ложатся, изменится файлов:", len(изменённые))
    sys.exit(0)
if not колонка_есть():
    sys.exit("СТОП, ничего не записано: в базе нет колонки devices.akb_cycles. Сначала:\n"
             f"    {os.path.basename(sys.executable)} cycles_card_patch.py {root} --column")
метка = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
for p in изменённые:
    with open(root + p, "rb") as f:
        прежнее = f.read()
    with open(root + p + ".bak_" + метка, "wb") as f:
        f.write(прежнее)
    io.open(root + p, "w", encoding="utf-8", newline="\n").write(_файлы[p])
    print("записан", p, "(копия .bak_" + метка + ")")
print("готово. Дальше: проверить импорт и перезапустить бота.")
