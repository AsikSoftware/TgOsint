# -*- coding: utf-8 -*-
"""Чек оценки на A4 — то, что отдают клиенту на руки.

Собирается из готового отчёта и данных сделки, без Qt: здесь только HTML, а печать
или PDF делает приложение. Так содержимое чека проверяется тестами, а не глазами.

Что на листе и почему именно это: клиент должен понимать, за что ему назвали цену,
и иметь на руках доказательство осмотра. Поэтому кроме цены — состояние батареи,
подлинность деталей словами Apple, блокировки и дата с номером сделки.
"""
from __future__ import annotations

import html as _html
from datetime import datetime

СТИЛЬ = """
  @page { size: A4; margin: 18mm 16mm; }
  body { font-family: 'Inter', 'Segoe UI', Arial, sans-serif; color: #11161C; font-size: 11pt; }
  h1 { font-size: 20pt; margin: 0 0 2mm 0; }
  .шапка { border-bottom: 2px solid #11161C; padding-bottom: 3mm; margin-bottom: 5mm; }
  .серый { color: #6B7580; font-size: 10pt; }
  table { width: 100%; border-collapse: collapse; margin: 0 0 5mm 0; }
  td { padding: 2.2mm 0; vertical-align: top; border-bottom: 1px solid #E6E9ED; }
  td.к { color: #6B7580; width: 46%; }
  td.з { font-weight: 700; }
  .цена { font-size: 26pt; font-weight: 700; margin: 2mm 0 1mm 0; }
  .плашка { padding: 3mm 4mm; border-radius: 3mm; margin: 0 0 5mm 0; }
  .ок { background: #E8F7EE; color: #0B6B35; }
  .внимание { background: #FFF4E0; color: #7A4A00; }
  .стоп { background: #FDE8E8; color: #8B1111; }
  .подпись { margin-top: 10mm; font-size: 10pt; color: #6B7580; }
  .линия { border-top: 1px solid #11161C; width: 70mm; margin-top: 12mm; }
"""


def _строка(ключ, значение):
    if значение in (None, "", []):
        return ""
    return f"<tr><td class='к'>{_html.escape(str(ключ))}</td><td class='з'>{_html.escape(str(значение))}</td></tr>"


def _деньги(сумма, валюта="₸"):
    if сумма in (None, ""):
        return "—"
    return f"{int(сумма):,}".replace(",", " ") + f" {валюта}"


def данные_из_отчёта(rep: dict) -> dict:
    """Вытащить из отчёта ровно то, что печатаем. Отдельно от вёрстки, чтобы можно было
    проверить содержимое, не разбирая HTML."""
    пас = rep.get("паспорт") or {}
    бат = rep.get("батарея") or {}
    пам = rep.get("память") or {}
    вердикт = rep.get("детали_вердикт") or {}
    итог = rep.get("итог") or {}
    замки = []
    прав = rep.get("правовой") or {}
    sk = rep.get("sickw") or {}
    if sk.get("в_чёрном_списке") is True:
        замки.append("числится в чёрном списке")
    if прав.get("найти_iphone") == "включён" or sk.get("fmi_включён") is True:
        замки.append("включён «Найти iPhone»")
    if прав.get("mdm") is True:
        замки.append("корпоративный надзор (MDM)")
    детали = []
    for d in вердикт.get("детали") or []:
        if str(d.get("деталь", "")).startswith("Записи"):
            continue
        детали.append((d["деталь"], {"ok": "оригинальная", "repaired": "меняли (оригинал Apple)",
                                     "used": "б/у деталь", "bad": "не подтверждена"}.get(d["статус"], "—")))
    return {
        "модель": пас.get("модель"), "память": пам.get("объём_гб"), "цвет": пас.get("цвет"),
        "серийник": пас.get("серийник"), "imei": пас.get("imei"), "imei2": пас.get("imei2"),
        "ios": пас.get("ios"),
        "здоровье": бат.get("здоровье_%"), "циклы": бат.get("циклы"),
        "вердикт": итог.get("вердикт"), "детали": детали,
        "подтверждено": bool(вердикт.get("apple_подтверждено")),
        "замки": замки,
        "внимание": list(rep.get("внимание") or []),
    }


def html(сделка: dict, rep: dict, когда: datetime | None = None) -> str:
    """Готовая страница A4. `сделка`: номер, цена, клиент, точка, сотрудник, комплектность."""
    d = данные_из_отчёта(rep)
    когда = когда or datetime.now()
    класс = {"ХОРОШИЙ": "ок", "ПРОБЛЕМНЫЙ": "стоп"}.get(d["вердикт"] or "", "внимание")
    подлинность = ("Apple подтвердила: все отслеживаемые детали оригинальные"
                   if d["подтверждено"] and (rep.get("детали_вердикт") or {}).get("итог") == "родные"
                   else "Подлинность деталей Apple не подтвердила — см. список ниже")
    строки = "".join([
        _строка("Модель", d["модель"]),
        _строка("Память", f"{d['память']} ГБ" if d["память"] else None),
        _строка("Цвет", d["цвет"]),
        _строка("iOS", d["ios"]),
        _строка("Серийный номер", d["серийник"]),
        _строка("IMEI", d["imei"]),
        _строка("IMEI 2", d["imei2"]),
        _строка("Аккумулятор", f"{d['здоровье']}%" + (f", {d['циклы']} циклов" if d["циклы"] else "")
                if d["здоровье"] is not None else None),
        _строка("Коробка", "есть" if сделка.get("коробка") else "нет"),
        _строка("Шнур", "есть" if сделка.get("шнур") else "нет"),
    ])
    детали = "".join(_строка(имя, сост) for имя, сост in d["детали"])
    замечания = "".join(f"<li>{_html.escape(x)}</li>" for x in (d["замки"] + d["внимание"]))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{СТИЛЬ}</style></head><body>
<div class="шапка">
  <h1>Оценка телефона</h1>
  <div class="серый">Pintel · {_html.escape(str(сделка.get('точка') or ''))} ·
    сделка № {_html.escape(str(сделка.get('номер') or '—'))} · {когда:%d.%m.%Y %H:%M}</div>
</div>

<div class="плашка {класс}"><b>{_html.escape(str(d['вердикт'] or 'ПРОВЕРКА'))}</b> — {_html.escape(подлинность)}</div>

<div class="серый">Предложенная цена</div>
<div class="цена">{_деньги(сделка.get('цена'), сделка.get('валюта') or '₸')}</div>
<div class="серый">Цена действительна в день оценки и может измениться после осмотра корпуса.</div>

<h3>Телефон</h3><table>{строки}</table>
{'<h3>Детали по данным Apple</h3><table>' + детали + '</table>' if детали else ''}
{'<h3>На что обратить внимание</h3><ul>' + замечания + '</ul>' if замечания else ''}

<div class="подпись">
  Клиент: {_html.escape(str(сделка.get('клиент') or '—'))} · {_html.escape(str(сделка.get('телефон') or ''))}<br>
  Оценку провёл: {_html.escape(str(сделка.get('сотрудник') or '—'))}
  <div class="линия"></div>Подпись клиента
</div>
</body></html>"""
