# -*- coding: utf-8 -*-
"""Эталоны: телефон, про который мы ТОЧНО знаем правду, → один файл.

Зачем. Автоматика ошибается ровно там, где мы не видели живого аппарата:
новая iOS пишет вердикт по-своему, а мы разбираем по старому образцу. Угадывать
бесполезно — нужен эталон: слепок по кабелю + сырой журнал Apple + то, что
в эту же минуту показывает экран телефона (вводит сотрудник).

Что даёт эталон:
  1. СРАЗУ — расхождение видно на месте: «телефон говорит «неизвестно», мы сказали
     «родная»». Это и есть проверка, работает ли система на этом аппарате.
  2. ПОТОМ — по сырым строкам дописывается разбор, а эталон ложится в тесты:
     вердикт обязан совпасть с правдой, иначе сборка не пройдёт.

Слепок кладётся КАК ЕСТЬ, с настоящими серийниками и IMEI (решение владельца,
24.11.2026). Подмена, которая была здесь раньше, портила сами данные: дата изготовления
детали закодирована в её серийнике и пропадала, коды заводов переставали совпадать — и
эталон врал ровно там, где по нему и разбираются. Защищать тут нечего: эталон едет с
нашего сервера разработчику и никуда больше.
"""
import io
import json
import os
import re
import zipfile
from datetime import datetime

from .analysis.parts import APPLE_PART_ORDER as PARTS, APPLE_STATES

# Что может быть написано напротив детали на экране телефона (формулировки Apple).
STATES = {k: v[0] for k, v in APPLE_STATES.items()}
# Состояния, при которых деталь НЕ оригинальная: наш вердикт обязан это поймать.
NOT_ORIGINAL = tuple(k for k, v in APPLE_STATES.items() if v[2] in ("bad", "used", "repaired"))
# Состояния, которые обязаны дать СТОП.
MUST_STOP = tuple(k for k, v in APPLE_STATES.items() if v[2] == "bad")

# ---------------------------------------------------------------- правда и сверка

def truth_template(**kw):
    t = {"детали": {}, "примечание": "", "раздел_открывали": None, "кто": "", "когда": datetime.now().isoformat()}
    t.update(kw)
    return t


def compare(rep, truth):
    """→ список расхождений между нашим отчётом и экраном телефона.
    Пусто — система на этом аппарате сработала верно."""
    parts_v = rep.get("детали_вердикт") or {}
    # сверяем по ключу детали: русские названия в таблицах Apple и в нашем отчёте разные
    # («Дисплей» против «Экран»), по ним сопоставлять нельзя
    status = {d.get("ключ") or d["деталь"]: d["статус"] for d in parts_v.get("детали") or []}
    hist = rep.get("apple_история") or {}
    names = dict(PARTS)
    износ_батареи = any("аккумулятор требует обслуживания" in str(w) for w in (rep.get("внимание") or []))
    bad = []
    marked = {k: v for k, v in (truth.get("детали") or {}).items() if v in STATES}
    # «Сервисное обслуживание» у аккумулятора — это износ, а не замена, и мы его уже
    # назвали. Исключение должно действовать и в общих проверках ниже: иначе один и тот
    # же разобранный случай всё равно числится расхождением.
    отметки = {k: v for k, v in marked.items()
               if not (v == "serviced" and k == "Battery" and износ_батареи)}
    for key, state in marked.items():
        name = names.get(key, key)
        ours = status.get(key)
        if key not in отметки:
            continue
        if state == "absent":
            # Apple эту деталь отслеживает, раздел на телефоне открывали — и в списке её
            # НЕТ. Значит замены Apple не видела, и наш «СТОП» по ней ложный. Ровно этим
            # ошибался iPhone 11: сигналы по кабелю кричали «экран меняли», а телефон про
            # дисплей не писал ничего, и выкуп срывался на каждом таком аппарате.
            if ours == "bad" and truth.get("раздел_открывали"):
                bad.append(f"{name}: Apple в списке её не показывает, а наш вердикт — «СТОП»")
            continue
        if state in NOT_ORIGINAL:
            if ours not in ("bad", "used", "repaired"):
                bad.append(f"{name}: телефон — «{STATES[state]}», мы — "
                           + ("«родная»" if ours == "ok" else "ничего не сказали"))
            elif state in MUST_STOP and ours != "bad":
                bad.append(f"{name}: телефон — «{STATES[state]}» (это СТОП), мы — «{ours}»")
        elif state == "genuine" and ours in ("bad", "used"):
            bad.append(f"{name}: телефон — «{STATES[state]}», мы — «{ours}»")
    if отметки and all(v == "genuine" for v in отметки.values()):
        if parts_v.get("итог") != "родные":
            bad.append(f"телефон: все детали оригинальные, наш вердикт по деталям — «{parts_v.get('итог')}»"
                       + ("" if parts_v.get("apple_подтверждено") else " (Apple не подтвердила — ждём разбора журнала)"))
    if any(v in NOT_ORIGINAL for v in отметки.values()) and parts_v.get("итог") == "родные":
        bad.append("телефон показывает неоригинальные детали, а наш вердикт — «все детали родные»")
    # Самое дорогое — пропустить ремонтный аппарат: его купят по цене чистого. Если про
    # аппарат точно известно, что ремонт был, «все детали родные» — ошибка, даже когда
    # поимённо на экране ничего не отмечено.
    if truth.get("ремонт_подтверждён") and parts_v.get("итог") == "родные":
        bad.append("аппарат подтверждён как ремонтный, а наш вердикт — «все детали родные»")
    # Записей может не быть, а вердикт быть: словарь доверия AuthCP у чистого аппарата не
    # даёт ни одной «плохой» детали. Такой журнал РАЗОБРАН, и числить его расхождением
    # нельзя — иначе сверка сама себе придумывает работу и прячет настоящие расхождения.
    разобран = bool(hist) or bool(parts_v.get("apple_подтверждено"))
    if truth.get("раздел_открывали") and not разобран \
            and rep.get("apple_история_статус") != "не поддерживается":
        bad.append("раздел на телефоне открывали, а журнал Apple мы не разобрали "
                   f"(статус «{rep.get('apple_история_статус')}») — нужны сырые строки")
    return bad


# ---------------------------------------------------------------- файл эталона

def bundle_name(rep, when=None):
    p = rep.get("паспорт") or {}
    model = re.sub(r"[^\w]+", "-", str(p.get("модель") or "iPhone")).strip("-")
    ios = re.sub(r"[^\d.]+", "", str(p.get("ios") or "")) or "ios"
    return f"эталон_{model}_iOS{ios}_{(when or datetime.now()):%Y%m%d_%H%M%S}.zip"


def _fill(z, snap, rep, truth, raw, mismatches, dumps):
    z.writestr("snapshot.json", dumps(snap))
    z.writestr("report.json", json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    z.writestr("правда.json", json.dumps(truth, ensure_ascii=False, indent=1))
    z.writestr("apple_raw.txt", raw or (snap.get("repair_history_raw") or ""))
    z.writestr("расхождения.txt", "\n".join(mismatches) or "расхождений нет")


def save_bundle(path, snap, rep, truth, raw="", mismatches=(), dumps=json.dumps):
    """Собрать один файл: слепок, отчёт, сырой журнал Apple, правда, расхождения."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        _fill(z, snap, rep, truth, raw, mismatches, dumps)
    return path


def bundle_bytes(snap, rep, truth, raw="", mismatches=(), dumps=json.dumps):
    """Тот же эталон, но в память: сервер складывает десятки таких в одну выгрузку."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        _fill(z, snap, rep, truth, raw, mismatches, dumps)
    return buf.getvalue()


def auto_truth(staff=None, раздел_открывали=None):
    """Правда для эталона, собранного автоматически, из отметок сотрудника на кассе:
    он смотрит на тот же экран телефона, что и опрос в докторе, поэтому это та же правда.
    Отметок нет — правды нет, но аппарат всё равно ценен форматом журнала."""
    s = dict(staff or {})
    return truth_template(детали={k: v for k, v in s.items() if v in STATES},
                          примечание=str(s.get("примечание") or ""),
                          раздел_открывали=раздел_открывали,
                          кто=str(s.get("кто") or "автосбор"),
                          когда=str(s.get("когда") or datetime.now().isoformat()))


def replay(raw):
    """Прогнать сырой журнал через слушатель заново — так же, как он шёл с телефона.
    → (записи, метаданные). Нужно, чтобы эталон проверял СЕГОДНЯШНИЙ разбор, а не тот,
    что был в момент сбора.

    Сам прогон живёт рядом со слушателем (`repair_history.перечитать`): тем же перечитыванием
    отчёт поднимает вердикт из слепка, у которого разобранных записей нет."""
    from .devicelink.repair_history import перечитать
    return перечитать(raw)


def load_bundle(path, loads=json.loads):
    """→ (слепок, правда). Журнал Apple разбирается заново текущим кодом: эталон обязан
    ловить регрессию разбора, а не хранить вчерашний вывод."""
    with zipfile.ZipFile(path) as z:
        snap = loads(z.read("snapshot.json").decode("utf-8"))
        truth = json.loads(z.read("правда.json").decode("utf-8"))
        raw = z.read("apple_raw.txt").decode("utf-8") if "apple_raw.txt" in z.namelist() else ""
    if raw:
        items, meta = replay(raw)
        snap["repair_history"], snap["repair_history_raw"] = items, raw
        snap["repair_history_meta"] = {**(snap.get("repair_history_meta") or {}), **meta}
    return snap, truth
