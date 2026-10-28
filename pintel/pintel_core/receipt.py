# -*- coding: utf-8 -*-
"""Чек оценки на A4 — то, что клиент уносит на руках.

Собирается из готового отчёта и данных сделки, без Qt: здесь только HTML, а печать или
PDF делает приложение. Так содержимое чека проверяется тестами, а не глазами.

Это не распечатка из программы, а документ: шапка с логотипом и реквизитами, две колонки
с тем, что проверено, и подписи обеих сторон. Клиент должен иметь на руках доказательство
осмотра, поэтому на листе есть всё, что видела проверка, — детали, блокировки, состояние
батареи.

Цены на чеке нет: её считает Оценка по своему прайсу уже после создания сделки. Печатать
на бумаге сумму, которой ещё нет, значило бы обещать то, что потом не совпадёт.

Логотип вшит в страницу (data:), чтобы чек печатался и открывался на любом компьютере,
без интернета и без соседних файлов.
"""
from __future__ import annotations

import base64
import html as _html
import os
from datetime import datetime

ЛОГОТИП_ФАЙЛ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo.png")
_логотип_кеш = None

СТИЛЬ = """
  @page { size: A4; margin: 13mm 14mm; }
  * { box-sizing: border-box; }
  body { font-family: 'Inter', 'Segoe UI', Arial, sans-serif; color: #11161C; font-size: 10.5pt;
         line-height: 1.42; margin: 0; }
  .шапка { display: flex; justify-content: space-between; align-items: flex-start; gap: 12mm; }
  .шапка img { height: 13mm; }
  .реквизиты { text-align: right; font-size: 8.5pt; color: #6B7580; line-height: 1.5; }
  .черта { border-top: 2px solid #11161C; margin: 3mm 0 4mm 0; }
  .титул { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4mm; }
  h1 { font-size: 17pt; margin: 0; letter-spacing: -.3pt; }
  .номер { font-size: 9pt; color: #6B7580; }
  .две { display: grid; grid-template-columns: 1fr 1fr; gap: 4mm 7mm; }
  .блок { break-inside: avoid; }
  .кикер { font-size: 7.5pt; font-weight: 700; letter-spacing: .9pt; color: #6B7580;
           text-transform: uppercase; margin-bottom: 1.5mm; }
  .строка { display: flex; justify-content: space-between; gap: 4mm; padding: 1.1mm 0;
            border-bottom: 1px solid #EFF2F6; }
  .строка:last-child { border-bottom: 0; }
  .к { color: #6B7580; }
  .з { font-weight: 700; text-align: right; }
  .з.ок { color: #0B6B35; }
  .з.плохо { color: #8B1111; }
  .з.внимание { color: #7A4A00; }
  .плашка { display: inline-block; border-radius: 2mm; padding: 1.6mm 3.4mm; font-weight: 700;
            font-size: 9pt; margin-bottom: 2mm; }
  .ок { background: #E8F7EE; color: #0B6B35; }
  .внимание { background: #FFF4E0; color: #7A4A00; }
  .стоп { background: #FDE8E8; color: #8B1111; }
  .модель { font-size: 13pt; font-weight: 700; margin: 0 0 1.5mm 0; }
  .замечания { margin-top: 5mm; font-size: 9pt; }
  .замечания ul { margin: 1mm 0 0 0; padding-left: 5mm; }
  .подписи { display: grid; grid-template-columns: 1fr 1fr; gap: 12mm; margin-top: 10mm; }
  .линия { border-top: 1px solid #11161C; margin-top: 11mm; padding-top: 1.2mm;
           font-size: 8pt; color: #6B7580; }
  .сноска { margin-top: 6mm; padding-top: 2.5mm; border-top: 1px solid #E6E9ED;
            font-size: 7.5pt; color: #6B7580; line-height: 1.5; }
"""


def логотип() -> str:
    """Логотип строкой data: — чтобы чек открывался где угодно, без соседних файлов."""
    global _логотип_кеш
    if _логотип_кеш is None:
        try:
            with open(ЛОГОТИП_ФАЙЛ, "rb") as f:
                _логотип_кеш = "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
        except OSError:
            _логотип_кеш = ""
    return _логотип_кеш


def _э(значение) -> str:
    return _html.escape(str(значение if значение is not None else ""))


def _строка(ключ, значение, вид="") -> str:
    if значение in (None, "", []):
        return ""
    return (f"<div class='строка'><span class='к'>{_э(ключ)}</span>"
            f"<span class='з {вид}'>{_э(значение)}</span></div>")


def данные_из_отчёта(rep: dict) -> dict:
    """Вытащить из отчёта ровно то, что печатаем. Отдельно от вёрстки, чтобы можно было
    проверить содержимое, не разбирая HTML."""
    пас = rep.get("паспорт") or {}
    бат = rep.get("батарея") or {}
    пам = rep.get("память") or {}
    вердикт = rep.get("детали_вердикт") or {}
    итог = rep.get("итог") or {}
    прав = rep.get("правовой") or {}
    sk = rep.get("sickw") or {}
    пан = rep.get("паника") or {}

    детали = []
    for d in вердикт.get("детали") or []:
        если_имя = str(d.get("деталь") or "")
        if если_имя.startswith("Записи"):
            continue
        детали.append((если_имя, {"ok": ("оригинальная", "ок"),
                                  "repaired": ("меняли, оригинал Apple", "внимание"),
                                  "used": ("б/у деталь", "внимание"),
                                  "bad": ("не подтверждена", "плохо")}.get(d.get("статус"),
                                                                           ("—", ""))))
    замки = []
    if прав.get("найти_iphone") or sk.get("fmi_включён") is not None:
        включён = прав.get("найти_iphone") == "включён" or sk.get("fmi_включён") is True
        замки.append(("Найти iPhone", "включён" if включён else "выключен",
                      "плохо" if включён else "ок"))
    if sk.get("в_чёрном_списке") is not None:
        плохо = sk["в_чёрном_списке"] is True
        замки.append(("Чёрный список", "числится" if плохо else "чисто", "плохо" if плохо else "ок"))
    if прав.get("mdm") is not None:
        есть = прав["mdm"] is True
        замки.append(("Корпоративный надзор", "есть (MDM)" if есть else "нет",
                      "плохо" if есть else "ок"))
    if пан.get("проверено"):
        есть = bool(пан.get("panic_full"))
        замки.append(("Ошибка Panic full", "ЕСТЬ" if есть else "нет", "плохо" if есть else "ок"))
    if sk.get("восстановленный") is True:
        замки.append(("По данным Apple", "восстановленный аппарат", "внимание"))
    if sk.get("замена_по_гарантии") is True:
        замки.append(("По данным Apple", "выдан по замене", "внимание"))

    return {
        "модель": пас.get("модель"), "память": пам.get("объём_гб"), "цвет": пас.get("цвет"),
        "серийник": пас.get("серийник"), "imei": пас.get("imei"), "imei2": пас.get("imei2"),
        "ios": пас.get("ios"), "свободно": пам.get("свободно_гб"),
        "здоровье": бат.get("здоровье_%"), "циклы": бат.get("циклы"),
        "вердикт": итог.get("вердикт"), "почему": итог.get("почему"),
        "детали": детали, "замки": замки,
        "подтверждено": bool(вердикт.get("apple_подтверждено")),
        "итог_деталей": вердикт.get("итог"),
        "источник": rep.get("apple_история_источник") or rep.get("apple_история_статус"),
        "внимание": list(rep.get("внимание") or []),
    }


def html(сделка: dict, rep: dict, когда: datetime | None = None) -> str:
    """Готовая страница A4. `сделка`: номер, клиент, телефон, точка, сотрудник,
    комплектность, комментарий и `фирма` — реквизиты из настроек."""
    d = данные_из_отчёта(rep)
    когда = когда or datetime.now()
    фирма = сделка.get("фирма") or {}
    чисто = d["подтверждено"] and d["итог_деталей"] == "родные"
    класс = "ок" if чисто else ("стоп" if d["вердикт"] == "ПРОБЛЕМНЫЙ" else "внимание")
    заголовок = ("Apple подтвердила подлинность деталей" if чисто
                 else "Apple не подтвердила подлинность деталей")

    реквизиты = "<br>".join(_э(x) for x in (
        фирма.get("адрес") or сделка.get("точка"),
        фирма.get("телефон"), фирма.get("сайт") or "pintel.kz",
        f"БИН {фирма['бин']}" if фирма.get("бин") else "") if x)
    лого = (f"<img src='{логотип()}' alt='{_э(фирма.get('название') or 'Pintel')}'>"
            if логотип() else
            f"<div class='модель'>{_э(фирма.get('название') or 'Pintel')}</div>")

    телефон_блок = "".join([
        _строка("Память", f"{d['память']} ГБ" if d["память"] else None),
        _строка("Свободно", f"{d['свободно']:.0f} ГБ" if d.get("свободно") else None),
        _строка("Цвет", d["цвет"]),
        _строка("iOS", d["ios"]),
        _строка("Серийный номер", d["серийник"]),
        _строка("IMEI", d["imei"]),
        _строка("IMEI 2", d["imei2"]),
        _строка("Комплект", ", ".join(x for x, есть in (("коробка", сделка.get("коробка")),
                                                        ("шнур", сделка.get("шнур"))) if есть)
                or "без коробки и шнура"),
    ])
    батарея_блок = "".join([
        _строка("Ёмкость", f"{d['здоровье']}%" if d["здоровье"] is not None else None,
                "внимание" if (d["здоровье"] or 100) < 85 else "ок"),
        _строка("Циклов заряда", d["циклы"],
                "внимание" if (d["циклы"] or 0) > 800 else ""),
        _строка("Состояние", "ресурс выработан" if (d["циклы"] or 0) > 800
                else ("рабочая" if d["здоровье"] else None),
                "внимание" if (d["циклы"] or 0) > 800 else "ок"),
    ])
    детали_блок = "".join(_строка(имя, текст, вид) for имя, (текст, вид) in d["детали"])
    замки_блок = "".join(_строка(имя, текст, вид) for имя, текст, вид in d["замки"])
    замечания = [x for x in d["внимание"]]
    if сделка.get("комментарий"):
        замечания.append("Комментарий оценщика: " + str(сделка["комментарий"]))

    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Оценка {_э(d['модель'] or '')} · {_э(сделка.get('номер') or '')}</title>
<style>{СТИЛЬ}</style></head><body>
<div class="шапка">
  <div>{лого}</div>
  <div class="реквизиты">{реквизиты}</div>
</div>
<div class="черта"></div>

<div class="титул">
  <div>
    <h1>Заключение по оценке</h1>
    <div class="номер">Итог проверки: <b>{_э(d['вердикт'] or 'ПРОВЕРКА')}</b>{_э(' — ' + d['почему'] if d['почему'] else '')}</div>
  </div>
  <div class="номер">№ {_э(сделка.get('номер') or '—')} · {когда:%d.%m.%Y %H:%M}</div>
</div>

<div class="две">
  <div class="блок">
    <div class="кикер">Телефон</div>
    <div class="модель">{_э(d['модель'] or '—')}</div>
    {телефон_блок}
  </div>
  <div class="блок">
    <div class="кикер">Проверка подлинности</div>
    <div class="плашка {класс}">{_э(заголовок)}</div>
    {детали_блок or "<div class='к'>Детали не удалось проверить</div>"}
  </div>
  <div class="блок">
    <div class="кикер">Аккумулятор</div>
    {батарея_блок or "<div class='к'>Данных нет</div>"}
  </div>
  <div class="блок">
    <div class="кикер">Блокировки и история</div>
    {замки_блок or "<div class='к'>Проверка не выполнялась</div>"}
  </div>
</div>

{"<div class='замечания'><b>На что обратить внимание</b><ul>"
 + "".join(f"<li>{_э(x)}</li>" for x in замечания) + "</ul></div>" if замечания else ""}

<div class="подписи">
  <div><div class="кикер">Клиент</div>
    <div><b>{_э(сделка.get('клиент') or '—')}</b> · {_э(сделка.get('телефон') or '')}</div>
    <div class="линия">подпись</div></div>
  <div><div class="кикер">Оценку провёл</div>
    <div><b>{_э(сделка.get('сотрудник') or '—')}</b> · {_э(сделка.get('точка') or '')}</div>
    <div class="линия">подпись</div></div>
</div>

<div class="сноска">
  Проверка выполнена по кабелю: прочитаны серийные номера модулей и их привязка к телефону,
  состояние аккумулятора, память, журнал обслуживания Apple и отчёты о сбоях.
  {_э("Источник данных Apple: " + str(d['источник']) + "." if d['источник'] else "")}
  Заключение описывает состояние телефона на {когда:%d.%m.%Y} и не является договором купли-продажи.
</div>
</body></html>"""
