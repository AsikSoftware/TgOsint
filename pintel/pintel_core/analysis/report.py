# -*- coding: utf-8 -*-
"""Слепок → отчёт. Главный принцип: отсутствие данных НЕ превращается в вердикт."""
from . import battery, legal, pairing, passport, serials, storage
from ..devicelink import nand


def build(snap):
    nodes = snap.get("nodes") or {}
    doms = snap.get("domains") or {}
    bat = battery.analyze(nodes.get("AppleSmartBattery"))
    sto = storage.analyze(doms.get("com.apple.disk_usage"), nodes.get("nvme"))
    pas = passport.build(snap.get("root"))
    leg = legal.build(snap)
    sig = pairing.signals(snap)
    disk = doms.get("com.apple.disk_usage") or {}
    if disk.get("NANDInfo"):
        from ..devicelink.nodes import deep as _deep, txt as _txt
        nd = nand.summarize(disk["NANDInfo"], _txt(_deep(nodes.get("nvme") or {}, "Firmware Revision")))
    else:
        nd = snap.get("nand_summary") or {}
    parts = serials.collect(snap, pas["код_модели"])
    sk = snap.get("sickw")
    if sk and sk.get("цвет") and not pas["цвет"]:
        pas["цвет"] = sk["цвет"]

    stop, todo, warn, unknown = [], [], [], []
    if bat["подделка"]:
        stop.append("батарея: " + bat["подделка"][0])
    if not bat["есть_данные"]:
        unknown.append("батарея не прочиталась")
    if leg["mdm"]:
        stop.append("аппарат под корпоративным надзором (MDM) — перепродать нельзя")
    if leg["каналы_сошлись"] is False:
        stop.append("статус «Найти iPhone» различается в двух источниках — данные подменены")
    if leg["найти_iphone"] == "включён":
        todo.append("«Найти iPhone» включён — клиент должен выйти из Apple ID")
    if leg["пароль"]:
        todo.append("на телефоне стоит пароль — попросить снять")
    if sk:
        if sk.get("в_чёрном_списке") is True:
            stop.append(f"IMEI в чёрном списке (Sickw): {sk.get('чёрный_список')}")
        fmi_sk = sk.get("fmi_включён")
        if fmi_sk is True and leg["найти_iphone"] == "выключен":
            warn.append("Sickw: «Найти iPhone» включён, телефон говорит выключен — "
                        "переподключить и перечитать (или Sickw отдал старое из кэша)")
        elif fmi_sk is True and leg["найти_iphone"] != "включён":
            todo.append("«Найти iPhone» включён (по Sickw) — клиент должен выйти из Apple ID")
        elif fmi_sk is False and leg["найти_iphone"] == "включён":
            warn.append("Sickw: «Найти iPhone» выключен, телефон говорит включён — верим телефону")
    if sto["объём_сошёлся"] is False:
        stop.append(f"объём памяти не сходится: диск {sto['объём_гб']} ГБ, контроллер "
                    f"{sto['nvme_объём_гб']} / {sto['nvme_модель_гб']} ГБ — возможна перепайка")
    if nd and nd.get("прошивка_совпала_с_nvme") is False:
        unknown.append("NANDInfo разобран неверно — объём по нему не сверяем")
    for name, s in sig.items():
        if s["ок"] is False:
            stop.append(f"{name}: {s['почему']}")
        elif s["ок"] is None and name in ("Face ID ↔ плата", "Taptic ↔ плата", "Тачскрин"):
            unknown.append(f"{name}: {s['почему']}")
    if bat["здоровье_%"] is not None and bat["здоровье_%"] < 80:
        warn.append(f"износ батареи: здоровье {bat['здоровье_%']}%")
    if bat["циклы"] and bat["циклы"] > 800:
        warn.append(f"{bat['циклы']} циклов — ресурс выработан")
    warn.extend(bat["сомнения"])

    if stop:
        verdict = ("ПРОБЛЕМНЫЙ", "; ".join(stop[:3]))
    elif unknown:
        verdict = ("ПРОВЕРКА НЕПОЛНАЯ", "; ".join(unknown[:3]))
    elif warn:
        verdict = ("ХОРОШИЙ", "; ".join(warn[:3]))
    else:
        verdict = ("ИДЕАЛ", "проверенные детали на месте, батарея в норме")

    return {
        "паспорт": pas,
        "батарея": bat,
        "память": sto,
        "правовой": leg,
        "сигналы": sig,
        "nand": nd,
        "детали": parts,
        "sickw": sk,
        "apple_история": snap.get("repair_history") or None,
        "стоп": stop, "сделать": todo, "внимание": warn, "не_прочиталось": unknown,
        "итог": {"вердикт": verdict[0], "почему": verdict[1]},
        "качество_чтения": snap.get("quality") or {},
    }
