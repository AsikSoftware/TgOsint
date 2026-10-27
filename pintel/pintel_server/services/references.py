# -*- coding: utf-8 -*-
"""Эталоны из потока: каждый проверенный телефон — готовый эталон.

Собирать отдельно ничего не нужно. Киоск уже присылает слепок вместе с сырым журналом
Apple, а сверка сотрудника на кассе — это та же правда с экрана телефона, которую
спрашивает опрос в докторе. Значит эталон на сервере уже лежит; остаётся выбрать
ценное, обезличить и сложить в одну выгрузку.

Почему не всё подряд: сотня одинаковых чистых iPhone 13 не учит ничему, а один аппарат
с нераспознанным форматом журнала закрывает целую дыру. Поэтому у каждого аппарата есть
важность, и обычные берутся по паре на «модель + iOS + формат».
"""
import io
import json
import zipfile
from datetime import datetime

from sqlalchemy import desc, select

from pintel_core import reference
from pintel_core.analysis import report as report_mod
from pintel_core.devicelink import snapshot as snap_mod

from .. import audit
from ..db import now
from ..models import Evaluation

# Чем выше важность, тем сильнее аппарат учит разбор.
ВАЖНОСТЬ = {3: "расхождение со сверкой сотрудника", 2: "журнал есть, подтверждения нет",
            1: "сверка сотрудника подтвердила разбор", 0: "обычный аппарат"}


def снимок(ev):
    """Слепок из базы как его видит pintel_core: в JSON байтовые значения лежат как
    {"__b64__": …}, и без обратного превращения отчёт по ним не пересобрать."""
    return snap_mod.loads(json.dumps(ev.snapshot or {}, ensure_ascii=False))


def _meta(ev):
    return ((ev.snapshot or {}).get("repair_history_meta") or {})


def _fmt(ev):
    return str(_meta(ev).get("формат") or "")


def _raw(ev):
    return (ev.snapshot or {}).get("repair_history_raw") or ""


def _truth(ev):
    """Правда с экрана телефона: отметки сотрудника, если он сверял."""
    return reference.auto_truth(ev.staff_parts, раздел_открывали=_meta(ev).get("раздел_открыт"))


def rank(ev):
    """→ (важность, почему). Считаем по тому же правилу, по которому эталон полезен:
    расхождение с экраном телефона — главный материал, нераспознанный журнал — второй."""
    rep, truth = ev.report or {}, _truth(ev)
    if truth["детали"]:
        try:
            bad = reference.compare(rep, truth)
        except Exception as exc:                                  # noqa: BLE001
            return 3, f"сверка не выполнилась: {type(exc).__name__}"
        if bad:
            return 3, "расхождение: " + "; ".join(bad)[:300]
        return 1, "сверка сотрудника совпала с нашим вердиктом"
    if _raw(ev):
        fmt = _fmt(ev)
        if not fmt.startswith(("сверка", "проверка")):
            return 2, f"журнал пришёл, подтверждения Apple нет (формат: {fmt or 'не распознан'})"
        return 0, f"разобрано как обычно ({fmt})"
    return 0, "журнала нет — экран на телефоне не открывали"


def rows(db, limit=300):
    """Что уже лежит в потоке: таблица для страницы «Эталоны»."""
    evs = db.scalars(select(Evaluation).where(Evaluation.snapshot.is_not(None))
                     .order_by(desc(Evaluation.created_at)).limit(limit)).all()
    out = []
    for ev in evs:
        важн, почему = rank(ev)
        out.append({"id": ev.id, "номер": ev.number, "когда": ev.created_at,
                    "модель": ev.model_name or ev.model_code or "?", "ios": ev.ios or "?",
                    "формат": _fmt(ev) or "—", "строк": len(_raw(ev).splitlines()),
                    "подтверждено": bool(((ev.report or {}).get("детали_вердикт") or {}).get("apple_подтверждено")),
                    "правда": bool(_truth(ev)["детали"]), "важность": важн, "почему": почему,
                    "выгружен": ev.reference_at})
    return out


def combo(ev):
    """«Модель + iOS + формат журнала» — то, что определяет, учит ли аппарат чему-то новому."""
    return (ev.model_code or "?", ev.ios or "?", _fmt(ev))


def сверка_позже_выгрузки(ev):
    """Сотрудник сверил экран телефона уже ПОСЛЕ того, как аппарат уехал в выгрузку.
    Расхождение, найденное задним числом, — самый ценный материал, и без этой проверки
    оно не дошло бы до разбора никогда: заявка уже помечена выгруженной."""
    когда, было = (ev.staff_parts or {}).get("когда"), ev.reference_at
    if not когда or not было:
        return False
    try:
        return datetime.fromisoformat(str(когда)) > было and rank(ev)[0] == 3
    except Exception:                                             # noqa: BLE001 — часовые пояса, мусор в дате
        return False


def pick(db, only_new=True, limit=60, per_combo=2):
    """Отобрать аппараты для выгрузки: ценные — все, обычные — по паре на
    «модель + iOS + формат», иначе выгрузка зарастёт одинаковыми телефонами."""
    q = select(Evaluation).where(Evaluation.snapshot.is_not(None))
    evs = db.scalars(q.order_by(desc(Evaluation.created_at)).limit(1000)).all()
    if only_new:
        evs = [ev for ev in evs if ev.reference_at is None or сверка_позже_выгрузки(ev)]
    scored = sorted(((rank(ev), ev) for ev in evs), key=lambda t: (-t[0][0], -(t[1].id or 0)))
    # счёт ведём с учётом прошлых выгрузок: обычный аппарат уже знакомой комбинации больше
    # не нужен, иначе каждая следующая выгрузка привозила бы по паре тех же телефонов
    seen, chosen = {}, []
    if only_new:
        for ev in db.scalars(select(Evaluation).where(Evaluation.reference_at.is_not(None))
                             .order_by(desc(Evaluation.created_at)).limit(2000)).all():
            seen[combo(ev)] = seen.get(combo(ev), 0) + 1
    for (важн, почему), ev in scored:
        ключ = combo(ev)
        if важн == 0 and seen.get(ключ, 0) >= per_combo:
            continue
        seen[ключ] = seen.get(ключ, 0) + 1
        chosen.append((ev, важн, почему))
        if len(chosen) >= limit:
            break
    return chosen


def bundle(ev):
    """→ (имя, байты, причина_отказа). Обезличиваем ПЕРЕД укладкой: наружу уходит эталон
    без серийников и IMEI, и только если ни один вывод отчёта от замены не изменился."""
    clean, done, why = reference.pseudonymize(снимок(ev), report_mod.build)
    if not done:
        return None, None, why or "обезличить не удалось"
    rep = report_mod.build(clean)
    truth = _truth(ev)
    try:
        bad = reference.compare(rep, truth)
    except Exception as exc:                                      # noqa: BLE001
        bad = [f"сверка не выполнилась: {type(exc).__name__}: {exc}"]
    return (reference.bundle_name(rep, ev.created_at),
            reference.bundle_bytes(clean, rep, truth, raw=clean.get("repair_history_raw") or "",
                                   mismatches=bad, dumps=snap_mod.dumps), "")


def _summary(строки, пропущено):
    head = ("# Эталоны Pintel\n\n"
            f"Собрано автоматически из потока {now():%Y-%m-%d %H:%M}. Серийники, IMEI и MAC заменены;\n"
            "после замены отчёт пересобран и сверен с исходным — иначе аппарат в выгрузку не попал.\n"
            "«Правда» — отметки сотрудника с экрана телефона; где их нет, эталон ценен форматом журнала.\n\n"
            "| файл | заявка | модель | iOS | формат журнала | важность | почему взят |\n"
            "|---|---|---|---|---|---|---|\n")
    tail = ""
    if пропущено:
        tail = "\n## Не попали в выгрузку\n\n" + "\n".join(пропущено) + "\n"
    return head + "".join(строки) + tail


def export(db, user, only_new=True, limit=60):
    """Одна выгрузка: эталоны + сводка, что внутри. Выгруженные помечаем, чтобы в
    следующий раз ехало только новое."""
    chosen = pick(db, only_new=only_new, limit=limit)
    buf, строки, пропущено = io.BytesIO(), [], []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for ev, важн, почему in chosen:
            name, data, why = bundle(ev)
            if not data:
                пропущено.append(f"* заявка {ev.number or ev.id} ({ev.model_name or ev.model_code}): {why}")
                continue
            # два аппарата одной модели, снятые в одну секунду, дали бы одно имя: добавляем заявку
            name = f"{name[:-4]}_заявка{ev.number or ev.id}.zip"
            z.writestr("эталоны/" + name, data)
            строки.append(f"| {name} | {ev.number or ev.id} | {ev.model_name or ev.model_code or '?'} "
                          f"| {ev.ios or '?'} | {_fmt(ev) or '—'} | {важн} | {почему} |\n")
            ev.reference_at = now()
        z.writestr("сводка.md", _summary(строки, пропущено))
    db.commit()
    audit.log(db, user, "references.export",
              f"Выгрузка эталонов: {len(строки)} аппаратов" + (f", пропущено {len(пропущено)}" if пропущено else ""),
              entity="reference", details={"взято": len(строки), "пропущено": len(пропущено), "только_новое": only_new})
    db.commit()
    return f"эталоны_pintel_{now():%Y%m%d_%H%M}.zip", buf.getvalue(), len(строки)
