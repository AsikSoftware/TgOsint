# -*- coding: utf-8 -*-
"""Бот Оценки: продавец называет циклы батареи — сразу после процента АКБ.

    python3.13 cycles_question_patch.py <каталог бота> --check    # только проверить, ляжет ли
    python3.13 cycles_question_patch.py <каталог бота>            # поставить

Сначала должен стоять `cycles_card_patch.py`: он заводит колонку `devices.akb_cycles` и
поле в модели. Без него этот установщик не ставится.

Как было: циклы знала только касса (читает по кабелю), у сделок, заведённых продавцом в
боте, поле оставалось пустым. Как стало: после «Укажи точный процент АКБ» бот спрашивает
«Сколько циклов у аккумулятора?». Ответ — цифрами. Число видно в настройках не у каждого
телефона (у iPhone — с 15-й серии), поэтому вопрос можно пропустить, ответив «-»: тогда
поле остаётся пустым, а не нулём — ноль циклов это новая батарея, и выдумывать его нельзя.

Про «-» в тексте вопроса НЕ сказано, и кнопки пропуска нет — так решил владелец
(12.11.2026): подсказка «можно пропустить» превращается в «пропускают все». Продавцам о
минусе говорят отдельно. Не дописывайте его в подсказку.

Вопрос задаётся только продавцу в магазине. Клиенту, который оценивает телефон сам
(онлайн-оценка), его не задаём: ему сразу показывают цену, и лишний шаг там ни к чему.

Циклы попадают в сделку (`akb_cycles`), видны в черновике перед отправкой и в карточке
сделки («79% · циклов: 1719») и уходят в МойСклад в поле товара «Цикл».

Правка своих файлов бота заменами: каждая обязана лечь ровно один раз, иначе скрипт
останавливается, ничего не записав. Рядом кладутся копии `<файл>.bak_<дата>`.
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


def patch(p, pairs, раз=1):
    s = читать(p)
    for old, new in pairs:
        if s.count(old) != раз:
            sys.exit(f"СТОП, ничего не записано: {p} — замена должна лечь {раз} раз(а), "
                     f"а легла бы {s.count(old)}: {old[:70]!r}")
        s = s.replace(old, new)
    _файлы[p] = s


if "akb_cycles" not in читать("/database/models.py"):
    sys.exit("СТОП: в модели нет akb_cycles — сначала поставьте cycles_card_patch.py")
if "akb_cycles" in читать("/states/states.py"):
    sys.exit("уже стоит: в states/states.py есть akb_cycles — ничего не делаю")

patch("/states/states.py", [
    ('''    ddr = State()
    akb = State()
    video = State()
''', '''    ddr = State()
    akb = State()
    akb_cycles = State()
    video = State()
'''),
])

patch("/handlers/ocenka/flow.py", [
    ('''    if not data.get("online"):
        msg = await message.answer(
            _("Есть коробка?", lang),
            reply_markup=keyboards.yes_or_no(lang, "box"),
        )
        await state.update_data(mes_del=msg.message_id)
        await state.set_state(OcenkaState.box)
        return

    data = await state.get_data()
    device = await AsyncOrm.create_device_from_fsm_data(data)
''', '''    if not data.get("online"):
        # Телефон у продавца в руках — следом спрашиваем циклы батареи. Клиенту, который
        # оценивает сам (онлайн), этот вопрос не задаём: ему сразу показывают цену.
        msg = await message.answer(_(CYCLES_QUESTION, lang))
        await state.update_data(mes_del=msg.message_id)
        await state.set_state(OcenkaState.akb_cycles)
        return

    data = await state.get_data()
    device = await AsyncOrm.create_device_from_fsm_data(data)
'''),
    ('''@router_ocenka_flow.callback_query(OcenkaState.box, F.data.startswith("box_"))
''', '''CYCLES_QUESTION = (
    "Сколько циклов у аккумулятора? Только цифры.\\n"
    "iPhone: Настройки → Аккумулятор → Состояние аккумулятора → «Количество циклов»."
)
CYCLES_MAX = 20000
# Ответ «-» пропускает вопрос (телефон циклов не показывает). В подсказке об этом нарочно
# ни слова — см. шапку установщика.
CYCLES_SKIP = {"-", "–", "—"}


async def _ask_box(target: Message, state: FSMContext, lang: str) -> None:
    msg = await target.answer(_("Есть коробка?", lang), reply_markup=keyboards.yes_or_no(lang, "box"))
    await state.update_data(mes_del=msg.message_id)
    await state.set_state(OcenkaState.box)


@router_ocenka_flow.message(OcenkaState.akb_cycles)
async def enter_battery_cycles(message: Message, bot: Bot, state: FSMContext, lang: str):
    """Циклы батареи цифрами. Ноль — это ответ (батарея новая). «-» — пропуск: поле
    остаётся пустым, а не нулём."""
    text = (message.text or "").strip()
    пропуск = text in CYCLES_SKIP
    if not пропуск and (not text.isdigit() or int(text) > CYCLES_MAX):
        await message.answer(_("Укажи количество циклов, только цифры", lang))
        return

    data = await state.get_data()
    await del_message(data.get("mes_del"), bot, message.chat.id)
    await state.update_data(akb_cycles=None if пропуск else int(text))
    await _ask_box(message, state, lang)


@router_ocenka_flow.callback_query(OcenkaState.box, F.data.startswith("box_"))
'''),
])

patch("/database/database.py", [
    ('''                akb_exact=data.get("akb_exact"),
                color=data.get("color"),
''', '''                akb_exact=data.get("akb_exact"),
                akb_cycles=data.get("akb_cycles"),
                color=data.get("color"),
'''),
])

patch("/utils/utils.py", [
    ('''    akb = f"{data['akb_exact']}%" if data.get("akb_exact") else (data.get("akb") or "").strip()
''', '''    akb = f"{data['akb_exact']}%" if data.get("akb_exact") else (data.get("akb") or "").strip()
    if data.get("akb_cycles") is not None:
        akb = f"{akb or '-'} · циклов: {data['akb_cycles']}"
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
print("готово. Дальше: проверить импорт и перезапустить бота.")
