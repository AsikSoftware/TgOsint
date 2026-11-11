# -*- coding: utf-8 -*-
"""Бот Оценки: вместо выбора типа SIM — один вопрос «Есть SIM-лоток?».

    python3.13 sim_tray_patch.py <каталог бота>            # поставить
    python3.13 sim_tray_patch.py <каталог бота> --check    # только проверить, ляжет ли

Было четыре кнопки: Dual sim / E-sim / Прочее / Стандарт. На цену из них влияла одна:
«E-sim» дописывает к модели «(Esim)», и прайс берёт строку аппарата без лотка. Остальные
три значили для цены одно и то же, а выбирать между ними продавцу было нечем.

Стало: «Есть SIM-лоток» / «Нет SIM-лотка». В базе при этом прежние значения поля `sim`
(по нему МойСклад заполняет характеристику «Sim слот»): лоток есть → «Стандарт», лотка
нет → «E-sim», и модель, как и раньше, получает «(Esim)». В карточках сделки —
«SIM-лоток: есть / нет».

Правка своих файлов бота заменами: каждая обязана лечь ровно один раз (вопрос «Выбери
SIM» — ровно два), иначе скрипт останавливается, ничего не записав. Рядом кладутся копии
`<файл>.bak_<дата>`.
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


if "def sim_text" in читать("/utils/utils.py"):
    sys.exit("уже стоит: в utils/utils.py есть sim_text — ничего не делаю")

patch("/keyboards/keyboards.py", [
    ('''    kb = InlineKeyboardBuilder()
    kb.button(text=_("Dual sim", lang), callback_data="sim_Dual sim")
    kb.button(text=_("E-sim", lang), callback_data="sim_E-sim")
    kb.button(text=_("Прочее", lang), callback_data="sim_Прочее")
    kb.button(text=_("Стандарт", lang), callback_data="sim_Стандарт")
    kb.adjust(2)
''', '''    # Тип SIM не выбирают: вопрос один — есть ли SIM-лоток. В базе прежние значения:
    # лоток есть → «Стандарт», лотка нет → «E-sim» (по нему модель получает «(Esim)»).
    kb = InlineKeyboardBuilder()
    kb.button(text=_("Есть SIM-лоток", lang), callback_data="sim_Стандарт")
    kb.button(text=_("Нет SIM-лотка", lang), callback_data="sim_E-sim")
    kb.adjust(2)
'''),
    ('''    buttons = [
        _("🔹 Dual sim", lang),
        _("🔹 E-sim", lang),
        _("🔹 Прочее", lang),
        _("🔹 Стандарт", lang),
        _("🔙 Вернуться в меню", lang),
    ]
''', '''    buttons = [
        _("🔹 Есть SIM-лоток", lang),
        _("🔹 Нет SIM-лотка", lang),
        _("🔙 Вернуться в меню", lang),
    ]
'''),
])

patch("/handlers/ocenka/imei.py", [('_("Выбери SIM", lang)', '_("Есть SIM-лоток?", lang)')], раз=2)
patch("/handlers/ocenka/imei.py", [
    ('''    buttons = [
        _("🔹 Dual sim", lang),
        _("🔹 E-sim", lang),
        _("🔹 Прочее", lang),
        _("🔹 Стандарт", lang),
    ]
    text = message.text

    if text not in buttons:
        await message.answer(
            _("Выбери SIM кнопкой ниже.", lang),
''', '''    # вопрос один — есть ли SIM-лоток; в базу идут прежние значения поля sim
    buttons = {
        _("🔹 Есть SIM-лоток", lang): "Стандарт",
        _("🔹 Нет SIM-лотка", lang): "E-sim",
    }
    text = message.text

    if text not in buttons:
        await message.answer(
            _("Ответь кнопкой ниже: есть SIM-лоток или нет.", lang),
'''),
    ('''    sim = text.lstrip("🔹 ")
''', '''    sim = buttons[text]
'''),
])

patch("/utils/utils.py", [
    ('''def apply_esim_to_model(model: str | None, sim: str | None) -> str:
''', '''def sim_text(sim) -> str:
    """SIM-лоток в карточке: есть / нет. В базе это прежние значения поля `sim`."""
    sim = (sim or "").strip()
    if sim == "E-sim":
        return "нет"
    if sim in {"Стандарт", "Dual sim"}:
        return "есть"
    return sim or "-"


def apply_esim_to_model(model: str | None, sim: str | None) -> str:
'''),
    ('''        + f"<b>SIM-слот:</b> {device.sim}\\n"
''', '''        + f"<b>SIM-лоток:</b> {sim_text(device.sim)}\\n"
'''),
    ('''        f"<b>SIM-слот:</b> {sim or '-'}\\n"
''', '''        f"<b>SIM-лоток:</b> {sim_text(sim)}\\n"
'''),
    ('''        "sim": RedactFieldConfig(
            label=_("SIM", lang),
            kind="inline",
            prompt=_("Выбери тип SIM-слота", lang),
''', '''        "sim": RedactFieldConfig(
            label=_("SIM-лоток", lang),
            kind="inline",
            prompt=_("Есть SIM-лоток?", lang),
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
