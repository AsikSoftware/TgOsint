# -*- coding: utf-8 -*-
"""Бот Оценки: «Вернуться в меню» посреди ревизии спрашивает подтверждение.

    python3.13 exit_confirm_revision_patch.py <каталог бота>            # поставить
    python3.13 exit_confirm_revision_patch.py <каталог бота> --check    # только проверить

Что было. Выход в меню удаляет незаконченную ревизию пользователя
(`return_to_menu` → `delete_unfinished_revision_sessions_by_user`). Подтверждение «Выйти в
главное меню? Незаконченные данные будут потеряны» бот спрашивал, только когда у диалога
есть состояние FSM или открытая сделка. А ревизия идёт без состояния — она живёт в базе и
в веб-сканере, — поэтому начатая ревизия со всеми сканами терялась одним нажатием.

Что стало. Перед выходом бот смотрит в базу: есть у пользователя незаконченная ревизия —
спрашивает то же подтверждение. «Остаться» — ревизия цела, «Да, выйти» — как раньше.

Правка своих файлов бота (`handlers/start.py`, `database/database.py`) заменами: каждая
обязана лечь ровно один раз, иначе скрипт останавливается, ничего не записав. Рядом
кладутся копии `<файл>.bak_<дата>`.
"""
import datetime
import io
import sys

root = sys.argv[1].rstrip("/")
ТОЛЬКО_ПРОВЕРКА = "--check" in sys.argv
_файлы = {}


def читать(p):
    if p not in _файлы:
        _файлы[p] = io.open(root + p, encoding="utf-8").read()
    return _файлы[p]


def patch(p, pairs):
    s = читать(p)
    for old, new in pairs:
        if s.count(old) != 1:
            sys.exit(f"СТОП, ничего не записано: {p} — замена не легла ровно один раз "
                     f"({s.count(old)}): {old[:70]!r}")
        s = s.replace(old, new)
    _файлы[p] = s


if "has_unfinished_revision_session" in читать("/handlers/start.py"):
    sys.exit("уже стоит: в handlers/start.py есть has_unfinished_revision_session — ничего не делаю")

patch("/database/database.py", [
    ('''    @staticmethod
    async def delete_unfinished_revision_sessions_by_user(started_by_user_id: int) -> int:
''', '''    @staticmethod
    async def has_unfinished_revision_session(started_by_user_id: int) -> bool:
        """Есть ли у пользователя ревизия, которую выход в меню удалит. Условие то же, что
        у `delete_unfinished_revision_sessions_by_user` ниже, — менять их только вместе."""
        async with async_session_factory() as session:
            result = await session.execute(
                select(RevisionSession.id)
                .where(
                    RevisionSession.started_by_user_id == started_by_user_id,
                    RevisionSession.status.in_([
                        RevisionSession.STATUS_ACTIVE,
                        RevisionSession.STATUS_CHECKING,
                        RevisionSession.STATUS_ERROR,
                    ]),
                )
                .limit(1)
            )
            return result.first() is not None

    @staticmethod
    async def delete_unfinished_revision_sessions_by_user(started_by_user_id: int) -> int:
'''),
])
patch("/handlers/start.py", [
    ('''    # спрашиваем подтверждение, только если есть что терять
    if current_state or data.get("device_id"):
''', '''    # Ревизия идёт без состояния FSM: она живёт в базе, а выход в меню её удаляет
    # (return_to_menu). Поэтому про неё спрашиваем базу — иначе начатая ревизия со всеми
    # сканами терялась одним нажатием, без вопроса.
    revision_open = False
    if not current_state:
        user = await AsyncOrm.get_user_chat_id(message.chat.id)
        if user:
            revision_open = await AsyncOrm.has_unfinished_revision_session(user.id)

    # спрашиваем подтверждение, только если есть что терять
    if current_state or data.get("device_id") or revision_open:
'''),
])

for p, s in _файлы.items():
    compile(s, root + p, "exec")
if "select(" not in читать("/database/database.py").split("class AsyncOrm")[0] and \
        "import select" not in читать("/database/database.py") and \
        "select," not in читать("/database/database.py").split("class AsyncOrm")[0]:
    sys.exit("СТОП, ничего не записано: в database/database.py не импортирован select")
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
print("готово. Дальше: проверить импорт и перезапустить бота.")
