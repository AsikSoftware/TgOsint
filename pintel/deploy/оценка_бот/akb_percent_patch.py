# -*- coding: utf-8 -*-
"""Бот Оценки: продавец вводит точный процент АКБ. Кнопок-диапазонов и «нет информации» нет.

    python3.13 akb_percent_patch.py <каталог бота>            # поставить
    python3.13 akb_percent_patch.py <каталог бота> --check    # только проверить, ляжет ли

Это правка СВОИХ файлов бота (не наших обработчиков), поэтому она не копия файла, а набор
замен поверх того, что стоит на сервере. Каждая замена обязана лечь ровно один раз: если
файл бота с тех пор изменился, скрипт остановится, ничего не записав, и скажет, где.
Перед записью рядом кладётся копия `<файл>.bak_<дата>`.

Что меняется:
  • вопрос «Укажи состояние аккумулятора» с девятью кнопками → «Укажи точный процент АКБ,
    только цифры». Кнопок нет вовсе: ответ один — число от 1 до 100;
  • процент уходит в `devices.akb_exact`, по нему прайс берёт свою колонку;
  • `devices.akb` остаётся служебной меткой, выводится из процента сама: по ней МойСклад
    заполняет характеристику «АКБ», и её получает Pay — там ничего не меняется;
  • в карточках сделки вместо «86-90 (88%)» — «88%»;
  • в меню правки пункт «АКБ» принимает процент цифрами, отдельный пункт «АКБ точно» убран.

Варианта «нет информации» нет нарочно (слово владельца, 11.11.2026): сделка с ним
оставалась без автоцены и молча уходила админам.

Нужен новый `utils/google_price.py` из этой же папки (функция `akb_state_from_percent`).
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


def писать(p, s):
    _файлы[p] = s


def стоп(p, текст):
    sys.exit(f"СТОП, ничего не записано: {p} — {текст}")


def patch(p, pairs):
    s = читать(p)
    for old, new in pairs:
        if s.count(old) != 1:
            стоп(p, f"замена не легла ровно один раз ({s.count(old)}): {old[:70]!r}")
        s = s.replace(old, new)
    писать(p, s)


if "akb_state_from_percent" in читать("/handlers/ocenka/flow.py"):
    sys.exit("уже стоит: в handlers/ocenka/flow.py есть akb_state_from_percent — ничего не делаю")
if "def akb_state_from_percent" not in читать("/utils/google_price.py"):
    sys.exit("СТОП: сначала поставьте utils/google_price.py из этой папки — в нём нет akb_state_from_percent")

# ── клавиатура с диапазонами больше не нужна ──
p = "/keyboards/keyboards.py"
s = читать(p)
начало, конец = "def akb_kb(lang) -> InlineKeyboardMarkup:\n", "    kb.adjust(3)\n    return kb.as_markup()\n"
if s.count(начало) != 1:
    стоп(p, "не нашлась akb_kb")
i = s.index(начало)
j = s.index(конец, i) + len(конец)
писать(p, s[:i].rstrip("\n") + "\n" + s[j:])

# ── вопрос про АКБ в оценке: без кнопок ──
patch("/handlers/ocenka/imei.py", [
    ('''    msg = await call.message.answer(
        _("Укажи состояние аккумулятора", lang),
        reply_markup=keyboards.akb_kb(lang),
    )
''', '''    msg = await call.message.answer(
        _("Укажи точный процент АКБ, только цифры", lang),
    )
'''),
])

# ── приём ответа: только число ──
p = "/handlers/ocenka/flow.py"
patch(p, [
    ("from utils.google_price import get_price_for_device\n",
     "from utils.google_price import akb_state_from_percent, get_price_for_device\n"),
    ("from utils.utils import (\n    build_grade_text,\n", "from utils.utils import (\n    akb_text,\n    build_grade_text,\n"),
    ('''@router_ocenka_flow.callback_query(OcenkaState.akb, F.data.startswith("akb_"))
async def select_battery_health(call: CallbackQuery, bot: Bot, state: FSMContext, lang: str):
    await call.answer()

    akb = call.data.split("akb_", 1)[1]
    data = await state.get_data()
    await del_message(data.get("mes_del"), bot, call.message.chat.id)
    await state.update_data(akb=akb)
''', '''@router_ocenka_flow.message(OcenkaState.akb)
async def enter_battery_percent(message: Message, bot: Bot, state: FSMContext, lang: str):
    """Точный процент АКБ цифрами — другого ответа нет: по проценту берётся колонка прайса.

    `akb_exact` — сам процент. `akb` — служебная метка из него же: по ней МойСклад
    заполняет характеристику «АКБ», и её получает Pay."""
    text = (message.text or "").strip().rstrip("%").strip()
    if not text.isdigit() or not 1 <= int(text) <= 100:
        await message.answer(_("Укажи точный процент АКБ, только цифры", lang))
        return

    data = await state.get_data()
    await del_message(data.get("mes_del"), bot, message.chat.id)
    await state.update_data(akb=akb_state_from_percent(int(text)), akb_exact=int(text))
'''),
    ('''        f"<b>Состояние АКБ:</b> {device.akb}\\n"
''', '''        f"<b>Состояние АКБ:</b> {akb_text(device)}\\n"
'''),
])
s = читать(p)
i = s.index("async def enter_battery_percent(")
j = s.index("@router_ocenka_flow.callback_query(OcenkaState.box", i)
тело = s[i:j]
if "call.message" not in тело or "call." in тело.replace("call.message", ""):
    стоп(p, "тело обработчика АКБ не такое, как ожидалось")
писать(p, s[:i] + тело.replace("call.message", "message") + s[j:])

# ── карточки и меню правки ──
patch("/utils/utils.py", [
    ('''async def create_tex(device_id: int, lang: str, redact: bool = False) -> str:
''', '''def akb_text(device) -> str:
    """АКБ в карточке: точный процент; у старых сделок без него — что записано."""
    exact = getattr(device, "akb_exact", None)
    return f"{exact}%" if exact else str(getattr(device, "akb", None) or "-")


async def create_tex(device_id: int, lang: str, redact: bool = False) -> str:
'''),
    ('''        f"<b>Состояние АКБ:</b> {device.akb}"
        + (f" ({device.akb_exact}%)" if device.akb_exact else "")
        + "\\n"
''', '''        f"<b>Состояние АКБ:</b> {akb_text(device)}"
        + "\\n"
'''),
    ('''    akb = (data.get("akb") or "").strip()
''', '''    akb = f"{data['akb_exact']}%" if data.get("akb_exact") else (data.get("akb") or "").strip()
'''),
    ('''        "akb": RedactFieldConfig(
            label=_("АКБ", lang),
            kind="inline",
            prompt=_("Выбери состояние АКБ", lang),
            reply_markup_factory=lambda: keyboards.akb_kb(lang),
            db_target="device",
            db_field="akb",
        ),
''', '''        "akb": RedactFieldConfig(
            label=_("АКБ", lang),
            kind="text",
            prompt=_("Укажи точный процент АКБ, только цифры", lang),
            db_target="device",
            db_field="akb",
        ),
'''),
])
patch("/handlers/ocenka/helpers.py", [
    ('''        fields.extend(["akb_exact", "color", "simfree"])
''', '''        # процент АКБ правится пунктом «АКБ» выше — второй пункт про то же не нужен
        fields.extend(["color", "simfree"])
'''),
])
patch("/handlers/redact.py", [
    ('''    if field_name == "akb_exact":
''', '''    if field_name in {"akb", "akb_exact"}:
'''),
    ('''    if source == "fsm":
        update_data = {
            field_name: value,
            "field_name": None,
        }
''', '''    # АКБ — это точный процент; служебная метка (для МойСклада и Pay) выводится из него,
    # чтобы они не разошлись
    akb_fields = None
    if field_name in {"akb", "akb_exact"}:
        from utils.google_price import akb_state_from_percent
        akb_fields = {"akb": akb_state_from_percent(value), "akb_exact": value}

    if source == "fsm":
        update_data = {
            field_name: value,
            "field_name": None,
        }
        if akb_fields:
            update_data.update(akb_fields)
'''),
    ('''            fields = {
                db_field: value,
            }

            if field_name == "sim":
''', '''            fields = {
                db_field: value,
            }
            if akb_fields:
                fields = dict(akb_fields)

            if field_name == "sim":
'''),
])

# ── запись: всё или ничего ──
for p, s in _файлы.items():
    compile(s, root + p, "exec")                               # файл обязан остаться рабочим
for p, s in _файлы.items():
    if p != "/keyboards/keyboards.py" and "akb_kb" in s:
        стоп(p, "остался вызов убранной клавиатуры akb_kb")
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
