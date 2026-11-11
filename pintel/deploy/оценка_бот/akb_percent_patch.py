# -*- coding: utf-8 -*-
"""Бот Оценки: продавец вводит точный процент АКБ, кнопок-диапазонов больше нет.

    python3.13 akb_percent_patch.py <каталог бота>            # поставить
    python3.13 akb_percent_patch.py <каталог бота> --check    # только проверить, ляжет ли

Это правка СВОИХ файлов бота (не наших обработчиков), поэтому она не копия файла, а набор
замен поверх того, что стоит на сервере. Каждая замена обязана лечь ровно один раз: если
файл бота с тех пор изменился, скрипт остановится, ничего не записав, и скажет, где.
Перед записью рядом кладётся копия `<файл>.bak_<дата>`.

Что меняется:
  • вопрос «Укажи состояние аккумулятора» с девятью кнопками → «Укажи точный процент АКБ»,
    кнопка одна — «нет информации»;
  • введённый процент уходит в `devices.akb_exact`, по нему прайс берёт свою колонку;
  • `devices.akb` остаётся служебной меткой, выводится из процента сама: по ней МойСклад
    заполняет характеристику «АКБ», и её получает Pay — там ничего не меняется;
  • в карточках сделки вместо «86-90 (88%)» — «88%»;
  • в меню правки пункт «АКБ» принимает процент цифрами (0 — нет информации), отдельный
    пункт «АКБ точно» убран.

Нужен новый `utils/google_price.py` из этой же папки (функция `akb_state_from_percent`).
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


def писать(p, s):
    _файлы[p] = s


def patch(p, pairs):
    s = читать(p)
    for old, new in pairs:
        if s.count(old) != 1:
            sys.exit(f"СТОП, ничего не записано: {p} — замена не легла ровно один раз "
                     f"({s.count(old)}): {old[:70]!r}")
        s = s.replace(old, new)
    писать(p, s)


if "akb_state_from_percent" in читать("/handlers/ocenka/flow.py"):
    sys.exit("уже стоит: в handlers/ocenka/flow.py есть akb_state_from_percent — ничего не делаю")
if "def akb_state_from_percent" not in читать("/utils/google_price.py"):
    sys.exit("СТОП: сначала поставьте utils/google_price.py из этой папки — в нём нет akb_state_from_percent")

# ── клавиатура: одна кнопка вместо девяти диапазонов ──
s = читать("/keyboards/keyboards.py")
i = s.index("def akb_kb(lang) -> InlineKeyboardMarkup:\n")
j = s.index("    kb.adjust(3)\n    return kb.as_markup()\n", i) + len("    kb.adjust(3)\n    return kb.as_markup()\n")
s = s[:i] + '''def akb_kb(lang) -> InlineKeyboardMarkup:
    # Диапазонов больше нет: процент АКБ вводят цифрами, и цена берётся из колонки этого
    # процента. Кнопка одна — для аппаратов, у которых процент не узнать.
    kb = InlineKeyboardBuilder()
    kb.button(text="нет информации", callback_data="akb_нет информации")
    return kb.as_markup()
''' + s[j:]
писать("/keyboards/keyboards.py", s)

# ── вопрос про АКБ в оценке ──
patch("/handlers/ocenka/imei.py", [
    ('''    msg = await call.message.answer(
        _("Укажи состояние аккумулятора", lang),
        reply_markup=keyboards.akb_kb(lang),
    )
''', '''    msg = await call.message.answer(
        _("Укажи точный процент АКБ, только цифры", lang),
        reply_markup=keyboards.akb_kb(lang),
    )
'''),
])

# ── приём ответа ──
p = "/handlers/ocenka/flow.py"
patch(p, [
    ("from utils.google_price import get_price_for_device\n",
     "from utils.google_price import akb_state_from_percent, get_price_for_device\n"),
    ("from utils.utils import (\n    build_grade_text,\n", "from utils.utils import (\n    akb_text,\n    build_grade_text,\n"),
    ('''async def select_battery_health(call: CallbackQuery, bot: Bot, state: FSMContext, lang: str):
    await call.answer()

    akb = call.data.split("akb_", 1)[1]
    data = await state.get_data()
    await del_message(data.get("mes_del"), bot, call.message.chat.id)
    await state.update_data(akb=akb)
''', '''async def select_battery_health(call: CallbackQuery, bot: Bot, state: FSMContext, lang: str):
    # кнопка осталась одна — «нет информации»; процент вводят цифрами (ниже)
    await call.answer()
    await battery_entered(call.message, bot, state, lang, call.data.split("akb_", 1)[1], None)


@router_ocenka_flow.message(OcenkaState.akb)
async def enter_battery_percent(message: Message, bot: Bot, state: FSMContext, lang: str):
    """Точный процент АКБ цифрами: по нему берётся своя колонка прайса."""
    text = (message.text or "").strip().rstrip("%").strip()
    if not text.isdigit() or not 1 <= int(text) <= 100:
        await message.answer(
            _("Укажи точный процент АКБ, только цифры", lang),
            reply_markup=keyboards.akb_kb(lang),
        )
        return
    await battery_entered(message, bot, state, lang, akb_state_from_percent(int(text)), int(text))


async def battery_entered(message: Message, bot: Bot, state: FSMContext, lang: str, akb: str, akb_exact):
    """АКБ названа — дальше всё как раньше. `akb_exact` — процент, `akb` — служебная метка
    из него же: по ней МойСклад заполняет характеристику «АКБ», и её получает Pay."""
    data = await state.get_data()
    await del_message(data.get("mes_del"), bot, message.chat.id)
    await state.update_data(akb=akb, akb_exact=akb_exact)
'''),
    ('''        f"<b>Состояние АКБ:</b> {device.akb}\\n"
''', '''        f"<b>Состояние АКБ:</b> {akb_text(device)}\\n"
'''),
])
s = читать(p)
i = s.index("async def battery_entered(")
j = s.index("@router_ocenka_flow.callback_query(OcenkaState.box", i)
тело = s[i:j]
assert "call.message" in тело and "call." not in тело.replace("call.message", "")
s = s[:i] + тело.replace("call.message", "message") + s[j:]
писать(p, s)

# ── карточки и меню правки ──
patch("/utils/utils.py", [
    ('''async def create_tex(device_id: int, lang: str, redact: bool = False) -> str:
''', '''def akb_text(device) -> str:
    """АКБ в карточке: точный процент, а когда его нет — что есть («нет информации»)."""
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
            prompt=_("Укажи точный процент АКБ, только цифры. Нет информации — отправь 0", lang),
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
        digits = value.rstrip("%").strip()
        if not digits.isdigit() or not 1 <= int(digits) <= 100:
            raise RedactValidationError(_("Укажи точный процент АКБ, только цифры", lang))
        return int(digits)
''', '''    if field_name in {"akb", "akb_exact"}:
        digits = value.rstrip("%").strip()
        if field_name == "akb" and digits == "0":
            return 0                                   # «нет информации»
        if not digits.isdigit() or not 1 <= int(digits) <= 100:
            raise RedactValidationError(_("Укажи точный процент АКБ, только цифры", lang))
        return int(digits)
'''),
    ('''    if source == "fsm":
        update_data = {
            field_name: value,
            "field_name": None,
        }
''', '''    # АКБ — это точный процент; служебная метка (для МойСклада и Pay) выводится из него,
    # чтобы они не разошлись. 0 — «нет информации».
    akb_fields = None
    if field_name in {"akb", "akb_exact"}:
        from utils.google_price import akb_state_from_percent
        akb_fields = ({"akb": akb_state_from_percent(value), "akb_exact": value} if value
                      else {"akb": "нет информации", "akb_exact": None})

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
