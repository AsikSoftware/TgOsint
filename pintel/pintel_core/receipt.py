# -*- coding: utf-8 -*-
"""Чек оценки на A4 — то, что клиент уносит на руках.

Собирается из готового отчёта и данных сделки, без Qt: здесь только HTML, а печать или
PDF делает приложение. Так содержимое чека проверяется тестами, а не глазами.

Форму листа владелец собрал сам, правками по образцу (13.11.2026), и на листе нет ничего
сверх названного им:

* шапка — логотип, телефон, сайт (адрес и БИН не печатаем);
* «Телефон»: память, цвет, iOS, серийный номер, IMEI и под каждым — его строка в реестре
  РФС («Верификация IMEI 1/2»), комплект;
* «Аккумулятор»: ёмкость, циклы, максимальная температура за жизнь, состояние;
* «Блокировки и история»: замки и дата первой покупки по базе IMEI;
* «Проверка подлинности» — таблица во всю ширину: деталь, производитель, код, год выпуска,
  результат. Производитель известен не у всех деталей (см. docs/КОДЫ_деталей.md) — тогда
  только код и год; нет и их — только результат;
* внизу — отчёт по тестам (тест на телефоне, проверки руками) и QR на этот же чек;
* подписи обеих сторон.

Чего на листе нет нарочно: итога проверки одной строкой, плашки «Apple подтвердила…»,
блока «На что обратить внимание», свободной памяти, пояснений у QR, сноски. Не возвращайте
их «для полноты» — их убрал владелец.

Два случая, когда лист обязан сказать больше, чем в образце: проверку не делали заново (взята
прошлая) и аппарат запечатан (кабелем не читался). Про оба сказано одной строкой на месте —
иначе чек выглядел бы результатом чтения, которого при клиенте не было.

Цены на чеке нет: её считает Оценка по своему прайсу уже после создания сделки.

Логотип вшит в страницу (data:), чтобы чек печатался и открывался на любом компьютере,
без интернета и без соседних файлов.
"""
from __future__ import annotations

import base64
import html as _html
import os
import re
from datetime import datetime

from . import colours

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
  .стопка { display: grid; gap: 4mm; align-content: start; }
  .широкий { grid-column: 1 / -1; }
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
  .ок { background: #E8F7EE; color: #0B6B35; }
  .внимание { background: #FFF4E0; color: #7A4A00; }
  .модель { font-size: 13pt; font-weight: 700; margin: 0 0 1.5mm 0; }
  .деталь { display: grid; grid-template-columns: 44mm 40mm 24mm 30mm 1fr; gap: 0 4mm;
            padding: 1.1mm 0; border-bottom: 1px solid #EFF2F6; align-items: baseline; }
  .деталь:last-child { border-bottom: 0; }
  .деталь.головка { font-size: 7.5pt; font-weight: 700; letter-spacing: .6pt; color: #6B7580;
                    text-transform: uppercase; border-bottom: 1px solid #D5DBE3; }
  .деталь.головка span:last-child { text-align: right; }
  .пояснение { color: #6B7580; font-size: 9pt; }
  .низ { display: grid; grid-template-columns: 1fr auto; gap: 0 7mm; margin-top: 5mm;
         align-items: start; break-inside: avoid; }
  .kod { line-height: 0; }
  .тесты { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0 3mm; }
  .тесты + .кикер, .пояснение + .кикер { margin-top: 3mm; }
  .т { padding: 1.1mm 0; border-bottom: 1px solid #EFF2F6; }
  .т::before { content: "\\2713"; color: #0B6B35; font-weight: 700; margin-right: 2mm; }
  .т.сбой { color: #8B1111; font-weight: 700; }
  .т.сбой::before { content: "\\2715"; color: #8B1111; }
  .т.пропуск { color: #6B7580; }
  .т.пропуск::before { content: "\\2014"; color: #6B7580; }
  .подписи { display: grid; grid-template-columns: 1fr 1fr; gap: 12mm; margin-top: 10mm; }
  .линия { border-top: 1px solid #11161C; margin-top: 11mm; padding-top: 1.2mm;
           font-size: 8pt; color: #6B7580; }
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


def qr_svg(текст: str, модуль: int = 3) -> str:
    """QR как SVG прямо в странице: чек печатается и открывается без интернета и без
    соседних файлов. Нет библиотеки qrcode — просто не рисуем, чек от этого не ломается."""
    try:
        import qrcode
    except Exception:                                            # noqa: BLE001
        return ""
    q = qrcode.QRCode(border=1, box_size=1)
    q.add_data(текст)
    q.make(fit=True)
    m = q.get_matrix()
    размер = len(m) * модуль
    d = "".join(f"M{x * модуль} {y * модуль}h{модуль}v{модуль}h-{модуль}z"
                for y, строка in enumerate(m) for x, есть in enumerate(строка) if есть)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {размер} {размер}" '
            f'width="22mm" height="22mm" shape-rendering="crispEdges">'
            f'<rect width="100%" height="100%" fill="#fff"/><path d="{d}" fill="#11161C"/></svg>')


def _э(значение) -> str:
    return _html.escape(str(значение if значение is not None else ""))


def _строка(ключ, значение, вид="") -> str:
    if значение in (None, "", []):
        return ""
    return (f"<div class='строка'><span class='к'>{_э(ключ)}</span>"
            f"<span class='з {вид}'>{_э(значение)}</span></div>")


# Строка таблицы «Проверка подлинности» → деталь, чей серийник телефон отдаёт по кабелю.
# Из серийника берутся код изготовителя (первые три знака) и год выпуска. У «Верхнего модуля»,
# корпуса и заднего стекла серийника по кабелю нет — у них в таблице только результат.
СЕРИЙНИК_ДЕТАЛИ = {
    "Face ID": "ИК-камера Face ID", "Taptic Engine": "Taptic Engine", "Экран": "Экран (панель)",
    "Камера": "Основная камера", "Аккумулятор": "Аккумулятор", "Плата": "Материнская плата",
    "Датчик приближения": "Датчик приближения", "Фронтальная камера": "Фронтальная камера",
}
СТАТУС_ДЕТАЛИ = {"ok": ("оригинальная", "ок"), "repaired": ("меняли, оригинал Apple", "внимание"),
                 "used": ("б/у деталь", "внимание"), "bad": ("не подтверждена", "плохо")}
ВИД_РФС = {"verified": "ок", "blocked": "плохо", "not_verified": "внимание"}


def _дата(значение) -> str | None:
    """«2022-07-05» → «05.07.2022». Что не дата — как пришло: выдумывать число нельзя."""
    текст = str(значение or "").strip()
    try:
        return datetime.strptime(текст[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return текст or None


def _код_и_год(серийник, дата) -> tuple:
    """Код изготовителя и год выпуска детали из её серийника. Серийник панели бывает
    нечитаемым (мусорные байты) — тогда кода нет, а не три вопросительных знака."""
    код = str(серийник or "").strip()[:3].upper()
    return (код if re.fullmatch(r"[A-Z0-9]{3}", код) else "",
            str(дата)[:4] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(дата or "")) else "")


def данные_из_отчёта(rep: dict) -> dict:
    """Вытащить из отчёта ровно то, что печатаем. Отдельно от вёрстки, чтобы можно было
    проверить содержимое, не разбирая HTML."""
    пас = rep.get("паспорт") or {}
    бат = rep.get("батарея") or {}
    пам = rep.get("память") or {}
    вердикт = rep.get("детали_вердикт") or {}
    прав = rep.get("правовой") or {}
    sk = rep.get("sickw") or {}
    пан = rep.get("паника") or {}

    серийники = {str(x.get("деталь") or ""): x for x in (rep.get("детали") or []) if isinstance(x, dict)}
    детали = []
    for d in вердикт.get("детали") or []:
        имя = str(d.get("деталь") or "")
        if имя.startswith("Записи"):
            continue
        текст, вид = СТАТУС_ДЕТАЛИ.get(d.get("статус"), ("—", ""))
        свой = серийники.get(СЕРИЙНИК_ДЕТАЛИ.get(имя, "")) or {}
        код, год = _код_и_год(свой.get("серийник"), свой.get("дата"))
        детали.append({"деталь": имя, "производитель": свой.get("производитель") or "",
                       "код": код, "год": год, "результат": текст, "вид": вид})

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
    if rep.get("запечатанный") and sk.get("активация"):
        замки.append(("Активация (по базе)", sk["активация"], ""))
    if sk.get("дата_покупки"):
        замки.append(("Дата первой покупки", _дата(sk["дата_покупки"]), ""))

    # Реестр РФС отвечает по каждому IMEI сам, и ответы бывают разные — строка стоит под
    # своим номером в блоке «Телефон», а не списком в «Блокировках».
    from .external import rfs as rfs_mod
    рфс = {}
    for r in (rep.get("рфс") or []):
        if isinstance(r, dict) and r.get("imei"):
            рфс[str(r["imei"])] = (rfs_mod.словами(r), ВИД_РФС.get(r.get("verdict"), "") if r.get("ok") else "")

    return {
        "запечатанный": bool(rep.get("запечатанный")),
        "модель": пас.get("модель"), "память": пам.get("объём_гб"), "цвет": пас.get("цвет"),
        "серийник": пас.get("серийник"), "imei": пас.get("imei"), "imei2": пас.get("imei2"),
        "ios": пас.get("ios"), "рфс": рфс,
        "здоровье": бат.get("здоровье_%"), "циклы": бат.get("циклы"),
        "макс_температура": бат.get("макс_температура"),
        "детали": детали, "замки": замки,
        "повтор": str((rep.get("повторная_проверка") or {}).get("словами") or ""),
    }


def _тесты(сделка: dict) -> str:
    """Отчёт по тестам внизу листа: тест на телефоне клиента и проверки руками.

    Галочка — прошёл, крест — нет, прочерк — не проверяли. Данных нет вовсе (запечатанный,
    касса прежней сборки) — блока нет: пустая сетка из прочерков читалась бы как «ничего не
    работает»."""
    from . import phonetest
    from .external import ocenka_media

    def сетка(пары):
        return "<div class='тесты'>" + "".join(
            f"<span class='т{' ' + вид if вид else ''}'>{_э(имя)}</span>" for имя, вид in пары) + "</div>"

    куски = []
    тест = сделка.get("тест") if isinstance(сделка.get("тест"), dict) else {}
    ответы = {k: тест.get(k) for k in phonetest.КЛЮЧИ if тест.get(k) in phonetest.ОТВЕТЫ}
    if ответы:
        куски.append("<div class='кикер'>Тест на телефоне</div>" + сетка(
            (phonetest.ИМЕНА[k], {phonetest.ОК: "", phonetest.ПЛОХО: "сбой"}.get(ответы.get(k), "пропуск"))
            for k in phonetest.КЛЮЧИ))
    elif сделка.get("тест_пропущен"):
        куски.append("<div class='кикер'>Тест на телефоне</div><div class='пояснение'>Не проводился: "
                     + _э(сделка["тест_пропущен"]) + "</div>")
    ручная = ocenka_media.разобрать(сделка.get("ручная"))
    отметки = {k: ручная[k] for k in ocenka_media.КЛЮЧИ if k in ручная}
    if отметки:
        имена = {k: имя for k, имя, _ in ocenka_media.ПУНКТЫ}
        куски.append("<div class='кикер'>Проверка руками</div>" + сетка(
            (имена[k], "пропуск" if k not in отметки else ("" if отметки[k] else "сбой"))
            for k in ocenka_media.КЛЮЧИ))
    return "".join(куски)


def html(сделка: dict, rep: dict, когда: datetime | None = None) -> str:
    """Готовая страница A4. `сделка`: номер, клиент, телефон, точка, сотрудник, комплектность,
    `фирма` (реквизиты из настроек), `ссылка` на чек, `цвет` (выбран сотрудником), `тест`,
    `тест_пропущен` и `ручная` — результаты тестов."""
    d = данные_из_отчёта(rep)
    когда = когда or datetime.now()
    фирма = сделка.get("фирма") or {}

    # в шапке — телефон и сайт; адрес и БИН владелец с листа убрал
    реквизиты = "<br>".join(_э(x) for x in (фирма.get("телефон"), фирма.get("сайт") or "pintel.kz") if x)
    лого = (f"<img src='{логотип()}' alt='{_э(фирма.get('название') or 'Pintel')}'>"
            if логотип() else
            f"<div class='модель'>{_э(фирма.get('название') or 'Pintel')}</div>")

    def верификация(номер, imei):
        текст, вид = d["рфс"].get(str(imei or ""), (None, ""))
        return _строка(f"Верификация IMEI {номер}", текст, вид)

    свои = {str(x) for x in (d["imei"], d["imei2"]) if x}
    телефон_блок = "".join([
        _строка("Память", f"{d['память']} ГБ" if d["память"] else None),
        _строка("Цвет", d["цвет"] or colours.цвет(сделка.get("цвет"))),
        _строка("iOS", d["ios"]),
        _строка("Серийный номер", d["серийник"]),
        _строка("IMEI", d["imei"]), верификация(1, d["imei"]),
        _строка("IMEI 2", d["imei2"]), верификация(2, d["imei2"]),
        # ответ реестра по номеру, которого нет в паспорте (IMEI с коробки), не теряем
        *[_строка(f"Верификация {imei}", текст, вид)
          for imei, (текст, вид) in d["рфс"].items() if imei not in свои],
        _строка("Комплект", ", ".join(x for x, есть in (("коробка", сделка.get("коробка")),
                                                        ("шнур", сделка.get("шнур"))) if есть)
                or "без коробки и шнура"),
    ])
    батарея_блок = "".join([
        _строка("Ёмкость", f"{d['здоровье']}%" if d["здоровье"] is not None else None,
                "внимание" if (d["здоровье"] or 100) < 85 else "ок"),
        _строка("Циклов заряда", d["циклы"],
                "внимание" if (d["циклы"] or 0) > 800 else ""),
        # на iOS 27 телефон этого числа не отдаёт — строки просто нет
        _строка("Максимальная температура",
                f"{d['макс_температура']} °C" if d["макс_температура"] else None),
        _строка("Состояние", "ресурс выработан" if (d["циклы"] or 0) > 800
                else ("рабочая" if d["здоровье"] else None),
                "внимание" if (d["циклы"] or 0) > 800 else "ок"),
    ])
    замки_блок = "".join(_строка(имя, текст, вид) for имя, текст, вид in d["замки"])
    if d["детали"]:
        детали_блок = ("<div class='деталь головка'><span>Деталь</span><span>Производитель</span>"
                       "<span>Код</span><span>Год выпуска</span><span>Результат</span></div>"
                       + "".join(
                           f"<div class='деталь'><span class='к'>{_э(x['деталь'])}</span>"
                           f"<span>{_э(x['производитель'])}</span><span>{_э(x['код'])}</span>"
                           f"<span>{_э(x['год'])}</span>"
                           f"<span class='з {x['вид']}'>{_э(x['результат'])}</span></div>"
                           for x in d["детали"]))
    elif d["запечатанный"]:
        детали_блок = ("<div class='пояснение'>Коробка не вскрыта: кабелем аппарат не читался, детали "
                       "не проверялись. Модель, память и цвет — по базе IMEI.</div>")
    else:
        детали_блок = "<div class='пояснение'>Детали не удалось проверить</div>"
    # Проверку могли взять прошлую (этот же аппарат приносили сегодня). На бумаге, которую
    # клиент уносит, это обязано быть сказано: иначе чек выглядит как результат чтения,
    # сделанного при нём.
    повтор = (f"<div class='пояснение'>Данные проверки — от {_э(d['повтор'])}: в этот раз телефон "
              f"кабелем не перечитывали.</div>") if d["повтор"] else ""

    ссылка = str(сделка.get("ссылка") or "").strip()
    qr = qr_svg(ссылка) if ссылка else ""
    тесты = _тесты(сделка)
    низ = (f'<div class="низ"><div>{тесты}</div><div class="kod">{qr}</div></div>'
           if (тесты or qr) else "")

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
    {повтор}
  </div>
  <div class="номер">№ {_э(сделка.get('номер') or '—')} · {когда:%d.%m.%Y %H:%M}</div>
</div>

<div class="две">
  <div class="блок">
    <div class="кикер">Телефон</div>
    <div class="модель">{_э(d['модель'] or '—')}</div>
    {телефон_блок}
  </div>
  <div class="стопка">
    <div class="блок">
      <div class="кикер">Аккумулятор</div>
      {батарея_блок or "<div class='пояснение'>Данных нет</div>"}
    </div>
    <div class="блок">
      <div class="кикер">Блокировки и история</div>
      {замки_блок or "<div class='пояснение'>Проверка не выполнялась</div>"}
    </div>
  </div>
  <div class="блок широкий">
    <div class="кикер">Проверка подлинности</div>
    {детали_блок}
  </div>
</div>

{низ}

<div class="подписи">
  <div><div class="кикер">Клиент</div>
    <div><b>{_э(сделка.get('клиент') or '—')}</b> · {_э(сделка.get('телефон') or '')}</div>
    <div class="линия">подпись</div></div>
  <div><div class="кикер">Оценку провёл</div>
    <div><b>{_э(сделка.get('сотрудник') or '—')}</b> · {_э(сделка.get('точка') or '')}</div>
    <div class="линия">подпись</div></div>
</div>
</body></html>"""
