# -*- coding: utf-8 -*-
"""Запечатанный аппарат: отчёт без кабеля.

Коробку не вскрывают, значит по кабелю читать нечего. Всё, что знаем, — из базы IMEI
(Sickw, служба для запечатанных: модель, объём, цвет, активация, гарантия) и реестра
РФС РК по IMEI с коробки. Отчёт складывается в тех же ключах, что и обычный, чтобы экран,
чек и посылка в Оценку читали его одинаково; детали и батарея честно «не проверялись» —
отсутствие данных не превращается в вердикт.
"""
from ..external import rfs as rfs_mod

ИТОГ_ДЕТАЛЕЙ = "запечатан"


def build(sk, imeis, рфс=None):
    sk = dict(sk or {})
    имеи = [str(x or "").strip() for x in (imeis or []) if str(x or "").strip()]
    пас = {"модель": sk.get("модель") or "iPhone", "код_модели": None, "ios": None,
           "серийник": None, "imei": имеи[0] if имеи else None,
           "imei2": имеи[1] if len(имеи) > 1 else None,
           "цвет": sk.get("цвет"), "цвет_по_коду": None, "esim": None, "esim_only": None,
           "sim": None, "sim_в_лотке": None}
    бат = {"здоровье_%": None, "циклы": None, "подделка": [], "есть_данные": False, "сомнения": []}
    fmi = sk.get("fmi_включён")
    прав = {"найти_iphone": "включён" if fmi is True else ("выключен" if fmi is False else "не определился"),
            "каналы_сошлись": None, "активация": sk.get("активация"), "пароль": False,
            "mdm": None, "mdm_почему": "кабеля нет", "mdm_источник": None}
    stop, todo, warn, unknown = [], [], [], []
    if not sk:
        unknown.append("база IMEI не ответила — модель и объём не подтверждены")
    else:
        if not sk.get("модель") or not sk.get("объём_гб"):
            unknown.append("база IMEI не назвала модель или объём — сверить по коробке")
        if sk.get("в_чёрном_списке") is True:
            stop.append(f"IMEI в чёрном списке (Sickw): {sk.get('чёрный_список')}")
        if fmi is True:
            warn.append("«Найти iPhone» включён (по Sickw) — у запечатанного аппарата так не бывает, "
                        "проверьте коробку")
        if sk.get("активирован") is True:
            warn.append(f"аппарат уже активирован ({sk.get('активация')}) — коробку вскрывали")
        if sk.get("подменный") is True:
            stop.append("Sickw: подменный аппарат Apple (Loaner) — собственность Apple")
        if sk.get("демо") is True:
            warn.append("Sickw: демонстрационный образец (Demo Unit)")
        if sk.get("восстановленный") is True:
            warn.append("Sickw: восстановленный аппарат (Refurbished)")
        if sk.get("замена_по_гарантии") is True:
            warn.append("Sickw: аппарат выдан Apple по замене (Replaced Device)")
    s, w, u = rfs_mod.в_отчёт(рфс or [])
    stop.extend(s)
    warn.extend(w)
    unknown.extend(u)

    if stop:
        verdict = ("ПРОБЛЕМНЫЙ", "; ".join(stop[:3]))
    elif unknown:
        verdict = ("ПРОВЕРКА НЕПОЛНАЯ", "; ".join(unknown[:3]))
    elif warn:
        verdict = ("ХОРОШИЙ", "; ".join(warn[:3]))
    else:
        verdict = ("ИДЕАЛ", "запечатан: по базе IMEI чист" + (", в реестре РФС верифицирован" if рфс else ""))

    return {
        "паспорт": пас,
        "батарея": бат,
        "память": {"объём_гб": sk.get("объём_гб"), "свободно_гб": None, "объём_сошёлся": None},
        "правовой": прав,
        "сигналы": {},
        "детали": {},
        "детали_вердикт": {"итог": ИТОГ_ДЕТАЛЕЙ, "детали": [], "каналы": {"кабель": False, "журнал": False},
                           "apple_подтверждено": False, "почему": "коробка не вскрыта — детали не проверялись"},
        "sickw": sk or None,
        "рфс": list(рфс) if рфс else None,
        "джейлбрейк": None,
        "паника": {},
        "apple_подтверждение_возможно": False,
        "apple_история": None,
        "apple_история_источник": None,
        "apple_история_статус": "не поддерживается",
        "apple_история_почему": "запечатанный аппарат — кабелем не читался",
        "стоп": stop, "сделать": todo, "внимание": warn, "не_прочиталось": unknown,
        "служебное": [],
        "итог": {"вердикт": verdict[0], "почему": verdict[1]},
        "запечатанный": True,
    }
