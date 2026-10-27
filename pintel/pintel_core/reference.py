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

Слепок обезличивается: серийники, IMEI и MAC заменяются по постоянной подстановке —
одинаковые значения остаются одинаковыми (иначе сломались бы проверки сопряжения
деталей), IMEI сохраняет контрольную цифру. После замены отчёт пересобирается и
сверяется с исходным: если хоть один вывод изменился — обезличивание отменяется.
"""
import hashlib
import io
import json
import os
import random
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

# ---------------------------------------------------------------- обезличивание

_ALPHABETS = ("0123456789", "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
# Ключи, значения которых — идентификаторы аппарата (по имени ключа, без учёта регистра).
_ID_KEY = re.compile(r"serial|imei|udid|uniquedeviceid|uniquechipid|chipid|address|iccid|meid|"
                     r"snum|sn$|regionalinfo|mlbserial|equipmentident|circuitcard|subscriberident|"
                     r"phonenumber|uniqueid", re.I)
_IMEI_RE = re.compile(r"^\d{15}$")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]{8,}")


def _substitution(salt):
    """Постоянная подстановка по классам символов: цифра→цифра, буква→буква.
    Одинаковые строки дают одинаковый результат, разные остаются разными."""
    rnd = random.Random(hashlib.sha256(salt.encode("utf-8")).digest())
    table = {}
    for alphabet in _ALPHABETS:
        shuffled = list(alphabet)
        rnd.shuffle(shuffled)
        table.update(zip(alphabet, shuffled))
    return table


def _luhn_fix(digits):
    """Вернуть IMEI с правильной контрольной цифрой — иначе наш же код его отвергнет."""
    d = [int(c) for c in digits[:14]]
    total = 0
    for i, x in enumerate(d):
        if i % 2:
            x *= 2
            x = x - 9 if x > 9 else x
        total += x
    return digits[:14] + str((10 - total % 10) % 10)


def _sub_value(value, table):
    out = "".join(table.get(c, c) for c in value)
    return _luhn_fix(out) if _IMEI_RE.match(value) else out


def _as_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("latin-1")
    return None


def _collect_ids(obj, found, key_hit=False):
    """Значения под ключами-идентификаторами (SerialNumber, IMEI, rosaline-serial-num…).
    Они же встречаются внутри других значений — например, серийник Taptic лежит
    куском в калибровке платы, и проверка сопряжения сверяет именно вхождение."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            _collect_ids(v, found, key_hit or bool(_ID_KEY.search(str(k))))
    elif isinstance(obj, list):
        for v in obj:
            _collect_ids(v, found, key_hit)
    elif key_hit:
        text = _as_text(obj)
        if text:
            for token in _TOKEN_RE.findall(text):
                if len(token) >= 8:
                    found.add(token)
    return found


def _walk(obj, table, ids=(), key_hit=False):
    """Заменить идентификаторы. Берём значения под ключами-идентификаторами и любые
    значения, внутри которых такой идентификатор лежит куском (иначе разъехались бы
    проверки сопряжения). Модель, версия iOS, цвет, даты не трогаем."""
    if isinstance(obj, dict):
        return {k: _walk(v, table, ids, key_hit or bool(_ID_KEY.search(str(k)))) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(v, table, ids, key_hit) for v in obj]
    text = _as_text(obj)
    if text is None:
        return obj
    if not key_hit:
        if len(text) < 8 or not any(i in text for i in ids):
            return obj
    out = _sub_value(text, table)
    return out.encode("latin-1") if isinstance(obj, (bytes, bytearray)) else out


def _sub_log(text, table):
    """В журнале Apple заменяем только значения печати (…Using value X for key Y)
    и длинные буквенно-цифровые токены — имена ключей и формат строк нужны разбору."""
    def one(m):
        tok = m.group(0)
        if tok.isalpha() or tok.isdigit() and len(tok) < 14:
            return tok
        return _sub_value(tok, table)
    return _TOKEN_RE.sub(one, text or "")


def _conclusions(rep):
    """Выводы, которые обезличивание не имеет права изменить."""
    return {"вердикт": (rep.get("итог") or {}).get("вердикт"),
            "детали": (rep.get("детали_вердикт") or {}).get("итог"),
            "сигналы": {k: v.get("ок") for k, v in (rep.get("сигналы") or {}).items()},
            "история": {k: (v.get("меняли"), v.get("бу"), v.get("неизвестная"))
                        for k, v in (rep.get("apple_история") or {}).items()},
            "стоп": len(rep.get("стоп") or []), "внимание": len(rep.get("внимание") or [])}


def pseudonymize(snap, build_report):
    """→ (слепок, заменено, причина_отказа). Отчёт после замены обязан совпасть
    с исходным, иначе возвращаем слепок как есть: правда важнее обезличивания."""
    table = _substitution(datetime.now().isoformat() + str(os.getpid()))
    out = _walk(snap, table, _collect_ids(snap, set()))
    if snap.get("repair_history_raw"):
        out["repair_history_raw"] = _sub_log(snap["repair_history_raw"], table)
    try:
        before, after = _conclusions(build_report(snap)), _conclusions(build_report(out))
    except Exception as exc:                                     # noqa: BLE001
        return snap, False, f"отчёт не пересобрался ({type(exc).__name__}: {exc})"
    if before != after:
        return snap, False, "после замены изменились выводы отчёта"
    return out, True, ""


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
    for key, state in marked.items():
        name = names.get(key, key)
        ours = status.get(key)
        if state == "serviced" and key == "Battery" and износ_батареи:
            continue            # «Сервисное обслуживание» у аккумулятора — износ, мы его уже назвали
        if state in NOT_ORIGINAL:
            if ours not in ("bad", "used", "repaired"):
                bad.append(f"{name}: телефон — «{STATES[state]}», мы — "
                           + ("«родная»" if ours == "ok" else "ничего не сказали"))
            elif state in MUST_STOP and ours != "bad":
                bad.append(f"{name}: телефон — «{STATES[state]}» (это СТОП), мы — «{ours}»")
        elif state == "genuine" and ours in ("bad", "used"):
            bad.append(f"{name}: телефон — «{STATES[state]}», мы — «{ours}»")
    if marked and all(v == "genuine" for v in marked.values()):
        if parts_v.get("итог") != "родные":
            bad.append(f"телефон: все детали оригинальные, наш вердикт по деталям — «{parts_v.get('итог')}»"
                       + ("" if parts_v.get("apple_подтверждено") else " (Apple не подтвердила — ждём разбора журнала)"))
    if any(v in NOT_ORIGINAL for v in marked.values()) and parts_v.get("итог") == "родные":
        bad.append("телефон показывает неоригинальные детали, а наш вердикт — «все детали родные»")
    if truth.get("раздел_открывали") and not hist and rep.get("apple_история_статус") != "не поддерживается":
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


# Запись журнала = строка, начинающаяся с метки времени; внутри записи бывают переводы строк
_ENTRY_RE = re.compile(r"\n(?=(?:#\s*похожее:\s*)?[A-Z][a-z]{2}\s+\d+\s+\d\d:\d\d:\d\d\s)")


def replay(raw):
    """Прогнать сырой журнал через слушатель заново — так же, как он шёл с телефона.
    → (записи, метаданные). Нужно, чтобы эталон проверял СЕГОДНЯШНИЙ разбор, а не тот,
    что был в момент сбора."""
    from .devicelink.repair_history import Listener
    lst = Listener(None)
    for entry in _ENTRY_RE.split(raw or ""):
        entry = re.sub(r"^#\s*похожее:\s*", "", entry)
        if entry.strip():
            lst._feed(entry)
    return lst.items, lst.meta


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
