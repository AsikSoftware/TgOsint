# -*- coding: utf-8 -*-
"""Слепок → отчёт. Главный принцип: отсутствие данных НЕ превращается в вердикт."""
from . import battery, legal, pairing, parts as parts_mod, passport, serials, storage
from ..devicelink import jailbreak, nand
from ..devicelink import panic as panic_mod
from ..devicelink.nodes import ENCLOSURE_COLOURS, num
from ..external import sickw as sickw_mod


def build(snap):
    nodes = snap.get("nodes") or {}
    doms = snap.get("domains") or {}
    bat = battery.analyze(nodes.get("AppleSmartBattery"))
    sto = storage.analyze(doms.get("com.apple.disk_usage"), nodes.get("nvme"))
    pas = passport.build(snap.get("root"))
    leg = legal.build(snap)
    sig = pairing.signals(snap)
    # История обслуживания Apple закрывает дыры там, где криптопривязка по кабелю
    # не читается (iPhone 17 Pro: нет FrontIRCameraSerialNumber), и даёт факты о заменах.
    from .capabilities import has_face_id
    from ..devicelink import repair_history as rh_mod
    hist = dict(snap.get("repair_history") or {})
    if has_face_id(pas["код_модели"]) is False:            # у SE нет Face ID — сверка его не показывает
        hist.pop("FaceID", None)
    hist_ok, hist_why = rh_mod.supported(pas["код_модели"], pas["ios"])
    for sig_name, hist_key in (("Face ID ↔ плата", "FaceID"), ("Тачскрин", "Display")):
        h = hist.get(hist_key)
        if sig_name in sig and sig[sig_name]["ок"] is None and h and h.get("меняли") is False:
            sig[sig_name] = {"ок": True, "почему": "по кабелю не читается; история Apple: не меняли",
                             "источник": "Apple"}
    disk = doms.get("com.apple.disk_usage") or {}
    if disk.get("NANDInfo"):
        from ..devicelink.nodes import deep as _deep, txt as _txt
        nd = nand.summarize(disk["NANDInfo"], _txt(_deep(nodes.get("nvme") or {}, "Firmware Revision")))
    else:
        nd = snap.get("nand_summary") or {}
    parts = serials.collect(snap, pas["код_модели"])
    sk = snap.get("sickw")
    if sk and sk.get("все_поля"):
        # разбор Sickw пересчитываем из сохранённых полей — правки парсера
        # применяются и к старым слепкам
        sk = {**sk, **sickw_mod.normalize(sk["все_поля"])}
    mg = snap.get("mobilegestalt") or {}
    from ..devicelink import mobilegestalt as mg_mod
    seal = mg_mod.seal_summary(mg)
    raw_code = mg.get("DeviceEnclosureColor") if "недоступен" not in mg else None
    code = num(raw_code) if raw_code is not None else None
    pas["код_цвета_корпуса"] = int(code) if code is not None else None
    pas["цвет_по_коду"] = ENCLOSURE_COLOURS.get(pas["код_цвета_корпуса"]) if code is not None else None
    if sk and sk.get("цвет") and not pas["цвет"]:
        pas["цвет"] = sk["цвет"]
    if not pas["цвет"] and pas["цвет_по_коду"]:
        pas["цвет"] = pas["цвет_по_коду"]
    jb = snap.get("jailbreak")
    pan = snap.get("panic") or {}
    # Единый вердикт по деталям: кабель (привязка + печать Apple) — основа, журнал — обогащение.
    parts_v = parts_mod.verdict(snap, sig, hist, bat, seal, snap.get("repair_history_meta") or {},
                                apple_supported=hist_ok)

    stop, todo, warn, unknown = [], [], [], []
    if bat["подделка"]:
        stop.append("батарея: " + bat["подделка"][0])
    if not bat["есть_данные"]:
        unknown.append("батарея не прочиталась")
    if leg["mdm"] is True:
        stop.append("аппарат под корпоративным надзором (MDM) — перепродать нельзя")
    elif leg["mdm"] is None:
        todo.append("MDM по кабелю не определился — проверить на телефоне: "
                    "Настройки → Основные → VPN и управление устройством")
    if leg["каналы_сошлись"] is False:
        stop.append("статус «Найти iPhone» различается в двух источниках — данные подменены")
    if leg["найти_iphone"] == "включён":
        todo.append("«Найти iPhone» включён — клиент должен выйти из Apple ID")
    if leg["пароль"]:
        todo.append("на телефоне стоит пароль — попросить снять")
    if pas.get("sim_в_лотке"):
        todo.append("в лотке SIM-карта — вынуть и вернуть клиенту")
    if pas.get("esim"):
        todo.append("на телефоне eSIM-профиль — удалить при стирании (Настройки → Сотовая связь)")
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
        elif (s["ок"] is None and name in ("Face ID ↔ плата", "Taptic ↔ плата", "Тачскрин")
              and parts_v["итог"] == "неполно"):
            # «нет данных» портит вердикт, только если деталь не подтверждена НИ одним каналом
            unknown.append(f"{name}: {s['почему']}")
    подтверждение_возможно = rh_mod.подтверждение_возможно(pas["ios"])
    if parts_v["итог"] in ("кабель", "неполно"):
        unknown.append(
            # на iOS 15 телефон пишет только отказы, словаря состояния деталей там нет вовсе
            f"на iOS {pas['ios']} Apple подлинность не подтверждает в принципе — сверка сотрудником обязательна"
            if hist_ok and not подтверждение_возможно
            else "подлинность деталей не подтверждена Apple: " + parts_v["почему"])
    # Молчаливая потеря канала — худший случай: проверка выглядит целой, а часть данных
    # просто не пришла. На живом iPhone 14 Pro так и было: в сборке не оказалось wintun.dll,
    # туннель не поднялся, и по кабелю пропали цвет корпуса и серийники части модулей.
    # Это не про телефон, а про наш канал чтения, поэтому отдельной строкой: вердикт по
    # аппарату она не портит, но и молчать о ней нельзя. Причины разные, и лечатся они
    # по-разному — одна наша, остальные со стороны Apple.
    служебное = []
    if "недоступен" in mg:
        почему = str(mg.get("недоступен") or "")
        низ = почему.lower()
        if "wintun" in низ or "dynlib" in низ or "dll" in низ:
            текст = "в сборке нет wintun.dll — туннель CoreDevice не поднялся (чинится у нас)"
        elif "does not offer" in низ or "invalidservice" in низ:
            # Служба com.apple.coredevice.deviceinfo есть не на всех iOS: её набор зависит
            # от версии смонтированного DDI, а в новых iOS её, по словам сопровождающего
            # pymobiledevice3, убрали совсем. На телефоне клиента ни DDI, ни режим
            # разработчика включать нельзя, так что это не поломка, а граница канала.
            текст = ("MobileGestalt закрыт на этой iOS (телефон не предлагает службу) — "
                     "подлинность подтверждается журналом Apple")
        elif "deprecat" in низ:
            текст = "канал закрыт Apple с iOS 17.4 — подлинность подтверждается журналом"
        else:
            текст = почему[:120]
        служебное.append("MobileGestalt не прочитан: " + текст)
    if bat["здоровье_%"] is not None and bat["здоровье_%"] < 80:
        warn.append(f"износ батареи: здоровье {bat['здоровье_%']}%")
    if bat["циклы"] and bat["циклы"] > 800:
        warn.append(f"{bat['циклы']} циклов — ресурс выработан")
    warn.extend(bat["сомнения"])
    for h in hist.values():
        if h.get("меняли"):
            when = f", {h['дата']}" if h.get("дата") else ""
            if h.get("записи_без_деталей"):
                warn.append("у Apple есть записи о ремонте этого телефона — подробности на экране телефона "
                            "(Настройки → Основные → Об этом устройстве)")
            elif h.get("неизвестная"):
                stop.append(f"по сверке Apple: {h['деталь']} — деталь неизвестного происхождения (не из печати)")
            elif h.get("бу"):
                stop.append(f"по истории Apple: {h['деталь']} меняли, установлена б/у деталь{when}")
            else:
                warn.append(f"по истории Apple: {h['деталь']} меняли (новая деталь{when})")
    hist_meta = snap.get("repair_history_meta") or {}
    комп = hist_meta.get("компоненты") or {}
    if (комп.get("аккумулятор") or {}).get("IOPSBatteryHealthServiceState"):
        warn.append("Apple: аккумулятор требует обслуживания (износ, деталь при этом оригинальная)")
    hist_source = hist_meta.get("формат") or ("записи обслуживания" if hist else None)
    if hist:
        hist_status = "получена"
    elif not hist_ok:
        hist_status = "не поддерживается"
    elif hist_meta.get("раздел_открыт"):
        hist_status = "формат не распознан"
        if parts_v["итог"] == "неполно":                      # только если и кабель молчит
            warn.append("раздел Apple открыт, но этот формат iOS ещё не разобран — сырые строки в оценке")
    else:
        hist_status = "не открыт"
    if sk:
        if sk.get("подменный") is True:
            stop.append("Sickw: подменный аппарат Apple (Loaner) — собственность Apple")
        if sk.get("демо") is True:
            warn.append("Sickw: демонстрационный образец (Demo Unit)")
        if sk.get("восстановленный") is True:
            warn.append("Sickw: восстановленный аппарат (Refurbished)")
        if sk.get("замена_по_гарантии") is True:
            warn.append("Sickw: аппарат выдан Apple по замене (Replaced Device)")
    if jb and jb.get("проверено") and jb.get("признаки"):
        warn.append("джейлбрейк: " + jailbreak.verdict(jb) + " — сбросить до заводских перед выкупом")
    # Panic full — отчёт о панике ядра: на выкупе это признак проблемы платы, и спрашивают
    # о нём отдельным вопросом. Не стоп: решает оценщик, но знать он должен.
    if pan.get("panic_full"):
        warn.append(panic_mod.словами(pan) + " — обычно это плата, проверьте внимательнее")
    elif pan and not pan.get("проверено"):
        unknown.append("panic full: " + str(pan.get("ошибка") or "не прочитано"))

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
        "детали_вердикт": parts_v,
        "sickw": sk,
        "джейлбрейк": jailbreak.verdict(jb),
        "паника": pan,
        "apple_подтверждение_возможно": bool(hist_ok and подтверждение_возможно),
        "mobilegestalt": ("недоступен" if "недоступен" in mg else ("есть" if mg else "не запрашивался")),
        "mobilegestalt_канал": mg.get("_канал"),
        "mobilegestalt_диагностика": mg.get("_диагностика") or None,
        "печать_деталей": seal,
        "apple_история": hist or None,
        "apple_история_источник": hist_source,
        "apple_история_статус": hist_status,
        "apple_история_почему": hist_why or None,
        "apple_раздел_открыт": bool(hist_meta.get("раздел_открыт")) or bool(hist),
        "стоп": stop, "сделать": todo, "внимание": warn, "не_прочиталось": unknown,
        "служебное": служебное,                 # неисправности нашего оборудования, не телефона
        "итог": {"вердикт": verdict[0], "почему": verdict[1]},
        "качество_чтения": snap.get("quality") or {},
    }
