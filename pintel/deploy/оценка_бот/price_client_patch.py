# -*- coding: utf-8 -*-
"""Бот Оценки: сумма, названная клиенту, — своя колонка сделки и строка в карточке.

    python3.13 price_client_patch.py <каталог бота> --check     # только проверить, ляжет ли
    python3.13 price_client_patch.py <каталог бота> --column    # добавить колонку в базу
    python3.13 price_client_patch.py <каталог бота>             # поставить (колонка уже есть)

Что меняется.

* **Сделка.** У `devices` появляется колонка `price_client` (целое, пусто по умолчанию) —
  сумма, которую сотрудник назвал клиенту на кассе: бот прислал ему автоцену подсказкой, он
  ответил числом. Кладёт её обработчик `kiosk_media.py` при создании сделки. У сделок,
  заведённых продавцом в боте, суммы нет, и колонка у них пустая.
* **Карточка сделки.** В `create_tex` сразу под «Оценен» — строка «Сумма клиенту: 170 000 тг».
  Нет суммы — строки нет, карточка прежняя.

Чего правка НЕ меняет: «Оценен» в карточке, отчёты и процент с разницы при выкупе считаются,
как и раньше, от `price_grade_admin` / `price_grade_auto`. `price_client` — только то, что
услышал клиент. Так решил владелец 13.11.2026: оценкой в сделке остаётся автооценка.

До этой правки сумма шла первой строкой комментария оценщика («Сумма клиенту: … ₸»). С
колонкой обработчик кладёт её в колонку, а комментарий не трогает; без колонки — по-старому.

Порядок важен: **сначала колонка, потом код**. Модель с полем, которого нет в базе, роняет
любое чтение сделки. Поэтому без колонки установка останавливается.

Правка файлов бота — заменой: каждая обязана лечь ровно один раз, иначе скрипт
останавливается, ничего не записав. Рядом кладётся копия `<файл>.bak_<дата>`.
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

ПРИМЕНИТЬ = "/database/apply_price_client_field.py"
ПРИМЕНИТЬ_ТЕКСТ = '''import asyncio

from sqlalchemy import text

from database.engine import async_engine


ALTER_STATEMENTS = [
    # сумма, которую сотрудник назвал клиенту на кассе; у сделок из бота пусто
    'ALTER TABLE "devices" ADD COLUMN IF NOT EXISTS "price_client" INTEGER',
]


async def ensure_price_client_field() -> None:
    async with async_engine.begin() as conn:
        for statement in ALTER_STATEMENTS:
            await conn.execute(text(statement))


if __name__ == "__main__":
    asyncio.run(ensure_price_client_field())
'''

ЕСТЬ_ЛИ_КОЛОНКА = '''
import asyncio
from sqlalchemy import text
from database.engine import async_engine

async def main():
    async with async_engine.connect() as conn:
        есть = (await conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'devices' AND column_name = 'price_client'"))).scalar()
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
        print("колонка devices.price_client уже есть — ничего не делаю")
        sys.exit(0)
    # Модулем, а не файлом: при запуске файлом первым в путях встаёт сама папка database/,
    # и `import database` находит в ней database.py вместо пакета.
    итог = subprocess.run([sys.executable, "-m", "database.apply_price_client_field"], cwd=root,
                          capture_output=True, text=True, timeout=120)
    if итог.returncode:
        sys.exit("СТОП: колонку добавить не вышло — "
                 + (итог.stderr.strip().splitlines() or ["?"])[-1][:300])
    print("колонка devices.price_client добавлена" if колонка_есть()
          else "СТОП: команда прошла, а колонки нет — смотрите базу")
    sys.exit(0)

if "price_client" in читать("/database/models.py"):
    sys.exit("уже стоит: в database/models.py есть price_client — ничего не делаю")
if "price_client" in читать("/utils/utils.py"):
    sys.exit("уже стоит: в utils/utils.py есть price_client — ничего не делаю")

patch("/database/models.py", [
    ('''    price_grade_admin: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
''', '''    price_grade_admin: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    # сумма, которую сотрудник назвал клиенту на кассе (в боте, по подсказке с автоценой);
    # у сделок из бота пусто. Оценкой остаётся price_grade_admin / price_grade_auto.
    price_client: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
'''),
])

patch("/utils/utils.py", [
    ('''        if price is not None:
            cost = _("Оценен", lang)
            text += f"\\n\\n<b>{cost}: {format_number_with_spaces(int(price))} тг</b>"
''', '''        if price is not None:
            cost = _("Оценен", lang)
            text += f"\\n\\n<b>{cost}: {format_number_with_spaces(int(price))} тг</b>"

        # сумма, которую сотрудник назвал клиенту на кассе; «Оценен» выше — по-прежнему прайс
        price_client = getattr(device, "price_client", None)
        if price_client is not None:
            text += (("\\n" if price is not None else "\\n\\n")
                     + f"<b>Сумма клиенту:</b> {format_number_with_spaces(int(price_client))} тг")
'''),
])

for p, s in _файлы.items():
    compile(s, root + p, "exec")
изменённые = [p for p, s in _файлы.items() if s != io.open(root + p, encoding="utf-8").read()]
if ТОЛЬКО_ПРОВЕРКА:
    print("проверка: все замены ложатся, изменится файлов:", len(изменённые))
    sys.exit(0)
if not колонка_есть():
    sys.exit("СТОП, ничего не записано: в базе нет колонки devices.price_client. Сначала:\n"
             f"    {os.path.basename(sys.executable)} price_client_patch.py {root} --column")
метка = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
for p in изменённые:
    with open(root + p, "rb") as f:
        прежнее = f.read()
    with open(root + p + ".bak_" + метка, "wb") as f:
        f.write(прежнее)
    io.open(root + p, "w", encoding="utf-8", newline="\n").write(_файлы[p])
    print("записан", p, "(копия .bak_" + метка + ")")
print("готово. Дальше: проверить импорт и перезапустить бота.")
