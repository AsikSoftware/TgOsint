# -*- coding: utf-8 -*-
"""Бот Оценки: ссылка на чек диагностики в сделке — для поля «Заключение» МойСклада.

    python3.13 check_url_patch.py <каталог бота> --check     # только проверить, ляжет ли
    python3.13 check_url_patch.py <каталог бота> --column    # добавить колонку в базу
    python3.13 check_url_patch.py <каталог бота>             # поставить (колонка уже есть)

Что меняется.

* **Сделка.** У `devices` появляется колонка `check_url` (строка до 300 знаков, пусто по
  умолчанию). Чек — заключение диагностики — живёт на домене кассы, касса присылает ссылку
  в посылке (`ссылка_чека`), обработчик `kiosk_media.py` кладёт её в сделку. У сделок,
  заведённых продавцом в боте, чека нет, и колонка у них пустая.
* **МойСклад.** Поле товара «Заключение» (тип «ссылка») при выкупе заполняется из этой
  колонки — это делает `utils/ms_card_fields.py`, он читает `device.check_url`. Нет поля в
  МойСкладе — молча пропускает.

Здесь только колонка и строка модели: без строки в `database/models.py` бот колонку не
прочитает, и `device.check_url` будет пуст.

Порядок важен: **сначала колонка, потом код**. Модель с полем, которого нет в базе, роняет
любое чтение сделки. Поэтому без колонки установка останавливается.

Правка файла бота — заменой: она обязана лечь ровно один раз, иначе скрипт
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

ПРИМЕНИТЬ = "/database/apply_check_url_field.py"
ПРИМЕНИТЬ_ТЕКСТ = '''import asyncio

from sqlalchemy import text

from database.engine import async_engine


ALTER_STATEMENTS = [
    # ссылка на чек диагностики на домене кассы; у сделок из бота пусто
    'ALTER TABLE "devices" ADD COLUMN IF NOT EXISTS "check_url" VARCHAR(300)',
]


async def ensure_check_url_field() -> None:
    async with async_engine.begin() as conn:
        for statement in ALTER_STATEMENTS:
            await conn.execute(text(statement))


if __name__ == "__main__":
    asyncio.run(ensure_check_url_field())
'''

ЕСТЬ_ЛИ_КОЛОНКА = '''
import asyncio
from sqlalchemy import text
from database.engine import async_engine

async def main():
    async with async_engine.connect() as conn:
        есть = (await conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'devices' AND column_name = 'check_url'"))).scalar()
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
        print("колонка devices.check_url уже есть — ничего не делаю")
        sys.exit(0)
    # Модулем, а не файлом: при запуске файлом первым в путях встаёт сама папка database/,
    # и `import database` находит в ней database.py вместо пакета.
    итог = subprocess.run([sys.executable, "-m", "database.apply_check_url_field"], cwd=root,
                          capture_output=True, text=True, timeout=120)
    if итог.returncode:
        sys.exit("СТОП: колонку добавить не вышло — "
                 + (итог.stderr.strip().splitlines() or ["?"])[-1][:300])
    print("колонка devices.check_url добавлена" if колонка_есть()
          else "СТОП: команда прошла, а колонки нет — смотрите базу")
    sys.exit(0)

if "check_url" in читать("/database/models.py"):
    sys.exit("уже стоит: в database/models.py есть check_url — ничего не делаю")

patch("/database/models.py", [
    ('''    akb_cycles: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
''', '''    akb_cycles: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # ссылка на чек диагностики на домене кассы: присылает касса; у сделок из бота пусто
    check_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
'''),
])

for p, s in _файлы.items():
    compile(s, root + p, "exec")
изменённые = [p for p, s in _файлы.items() if s != io.open(root + p, encoding="utf-8").read()]
if ТОЛЬКО_ПРОВЕРКА:
    print("проверка: все замены ложатся, изменится файлов:", len(изменённые))
    sys.exit(0)
if not колонка_есть():
    sys.exit("СТОП, ничего не записано: в базе нет колонки devices.check_url. Сначала:\n"
             f"    {os.path.basename(sys.executable)} check_url_patch.py {root} --column")
метка = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
for p in изменённые:
    with open(root + p, "rb") as f:
        прежнее = f.read()
    with open(root + p + ".bak_" + метка, "wb") as f:
        f.write(прежнее)
    io.open(root + p, "w", encoding="utf-8", newline="\n").write(_файлы[p])
    print("записан", p, "(копия .bak_" + метка + ")")
print("готово. Дальше: проверить импорт и перезапустить бота.")
