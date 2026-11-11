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
    sto = storage.analyze(doms.get("com.apple.disk_usage"), nodes.get("nvme"))
    pas = passport.build(snap.get("root"))
    leg = legal.build(snap)
    sig = pairing.signals(snap)
    # История обслуживания Apple закрывает дыры там, где криптопривязка по кабелю
    # не читается (iPhone 17 Pro: нет FrontIRCameraSerialNumber), и даёт факты о заменах.
    from .capabilities import has_face_id
    from ..devicelink import repair_history as rh_mod
    hist = dict(snap.get("repair_history") or {})
    hist_meta = dict(snap.get("repair_history_meta") or {})
    # Разбор журнала правится задним числом, по эталону, когда живого телефона под рукой уже
    # нет. Значит правка обязана доходить и до собранных слепков: иначе аппарат, на котором
    # мы учились, навсегда остаётся с «формат не распознан», а эталон того же аппарата —
    # зелёным, потому что эталоны перечитываются, а слепок на точке нет. Так же ниже
    # перечитывается Sickw. Берём перечитанное ТОЛЬКО когда живое чтение не дало ни одной
    # записи: сырые строки в слепке обрезаны (ПРЕДЕЛ_СТРОК), и там, где телефон сказал
    # больше, перечитанное было бы беднее. Поэтому эта ветка умеет лишь добавить вердикт,
    # которого не было, и не умеет снять вердикт, который был.
    перечитан = False
    if not hist and snap.get("repair_history_raw"):
        записи, meta2 = rh_mod.перечитать(snap["repair_history_raw"])
        if записи:
            hist, перечитан = dict(записи), True
            hist_meta = {**hist_meta, **(meta2 or {})}
    # Батарею собираем ПОСЛЕ журнала: процент называет сам телефон (powerd пишет его в
    # журнал), и до перечитывания сырых строк этого числа ещё нет.
    bat = battery.analyze(nodes.get("AppleSmartBattery"), hist_meta.get("батарея_телефона"))
    if has_face_id(pas["код_модели"]) is False:            # у SE нет Face ID — сверка его не показывает
        hist.pop("FaceID", None)
    hist_ok, hist_why = rh_mod.supported(pas["код_модели"], pas["ios"])
    for sig_name, hist_key in (("Face ID ↔ плата", "FaceID"), ("Тачскрин", "Display")):
        h = hist.get(hist_key)
        # Закрыть дыру кабеля может только НАСТОЯЩЕЕ подтверждение Apple — сверка с заводской
        # печатью или проверка компонентов. Одни записи обслуживания с нулями подтверждением
        # не считаются: на демонстрационном iPhone 15 Pro они были нулевыми, а на экране
        # телефона деталь значилась неизвестной. Правило то же, что в parts.verdict, и стоять
        # оно обязано здесь: иначе сигнал с пометкой «источник: Apple» уходил дальше в вердикт.
        подтверждает = str((h or {}).get("источник") or "").startswith(("сверка", "проверка"))
        if sig_name in sig and sig[sig_name]["ок"] is None and h and h.get("меняли") is False \
                and подтверждает:
            sig[sig_name] = {"ок": True, "почему": "по кабелю не читается; Apple сверила: не меняли",
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
    # «Apple по этой модели историю не ведёт» — основание выдать зелёный по одному кабелю, и
    # основание законное: у iPhone X и старше раздела нет вовсе. Но ровно то же `supported()`
    # отвечает и когда модель НЕ РАСПОЗНАНА («не iPhone»): паспорт не прочитался, модель новая
    # или нестандартная — и аппарат получал «все детали родные» вообще без участия Apple, а
    # клиенту на экране писалось «у этой модели Apple историю деталей не ведёт», чего никто не
    # проверял. Не знаем модель — спрашиваем Apple строго, как со всех.
    модель_неясна = (hist_why == "не iPhone")       # так `supported()` называет и пустой паспорт
    parts_v = parts_mod.verdict(snap, sig, hist, bat, seal, hist_meta,
                                apple_supported=(hist_ok or модель_неясна))

    stop, todo, warn, unknown = [], [], [], []
    if модель_неясна:
        unknown.append(f"модель не распознана ({pas.get('код_модели') or 'паспорт пуст'}) — "
                       "что по ней ведёт Apple, сказать нельзя")
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
    elif leg["найти_iphone"] == "не определился":
        # Молчание обоих каналов — не «выключен». Блокировку активации видно только на
        # телефоне, и без неё аппарат перепродать нельзя.
        unknown.append("«Найти iPhone» не определился — посмотреть на телефоне: "
                       "Настройки → [имя] → Локатор")
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
    # Реестр IMEI РФС РК: оба IMEI. Заблокирован — стоп; не верифицирован — предупреждение
    # (после срока временного доступа телефон не будет работать в сетях Казахстана);
    # реестр не ответил — не превращаем в вердикт, но и молчать нельзя.
    рфс = snap.get("rfs")
    if рфс:
        from ..external import rfs as rfs_mod
        s, w, u = rfs_mod.в_отчёт(рфс)
        stop.extend(s)
        warn.extend(w)
        unknown.extend(u)
    # Заводская печать (FDR): вердикт по деталям она меняла, а в «стоп»/«внимание» не попадала
    # вовсе — заголовок отчёта мог остаться ИДЕАЛ «проверенные детали на месте» при вердикте
    # «замена». Отчёт и вердикт обязаны говорить одно и то же.
    if (seal or {}).get("печать_цела") is False:
        stop.append("заводская печать деталей нарушена (FDR) — детали меняли")
    if (seal or {}).get("сервисная_деталь") is True:
        warn.append("Apple: установлена сервисная деталь (IsServicePart)")
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
    # Эту строку закрывает не повторное чтение, а человек с телефоном в руках: подлинность
    # подтверждает только Apple и только с экрана. Держим её отдельным ключом, чтобы те, кто
    # решает про автоцену, могли отличить «сверит сотрудник» от «закрыть нечем» — по тексту
    # такие вещи различать нельзя.
    сверка_деталей = None
    if parts_v["итог"] in ("кабель", "неполно"):
        сверка_деталей = (
            # на iOS 15 телефон пишет только отказы, словаря состояния деталей там нет вовсе
            f"на iOS {pas['ios']} Apple подлинность не подтверждает в принципе — сверка сотрудником обязательна"
            if hist_ok and not подтверждение_возможно
            else "подлинность деталей не подтверждена Apple: " + parts_v["почему"])
        unknown.append(сверка_деталей)
    # Молчаливая потеря канала — худший случай: проверка выглядит целой, а часть данных
    # просто не пришла. На живом iPhone 14 Pro так и было: в сборке не оказалось wintun.dll,
    # туннель не поднялся, и по кабелю пропали цвет корпуса и серийники части модулей.
    # Это не про телефон, а про наш канал чтения, поэтому отдельной строкой: вердикт по
    # аппарату она не портит, но и молчать о ней нельзя. Причины разные, и лечатся они
    # по-разному — одна наша, остальные со стороны Apple.
    служебное = []
    кач = snap.get("quality") or {}
    # «пусто» — это «узла у модели нет» (так ведут себя AIDBus и датчик приближения на новых
    # аппаратах), а текст исключения — настоящий обрыв нашего канала. Раньше и то и другое
    # лежало в слепке и не доходило до экрана вовсе: проверка выглядела целой.
    сорвалось = {k: str(v) for k, v in (кач.get("не_прочиталось") or {}).items()
                 if str(v).strip() != "пусто"}
    if сорвалось:
        служебное.append("не прочитались узлы телефона: "
                         + ", ".join(f"{k} ({v[:40]})" for k, v in list(сорвалось.items())[:4]))
        unknown.append(f"часть данных по кабелю не прочиталась ({len(сорвалось)}) — "
                       "привязка модулей проверена не полностью")
    # Внешние базы: шаг мог не состояться вовсе (нет ключа, сеть, реестр молчит). Отдельно от
    # ответа «чисто»: непроверенный чёрный список — это не чистый чёрный список.
    for ключ, почему in (кач.get("не_проверено") or {}).items():
        unknown.append(f"{ключ}: {почему}")
    if hist_meta.get("канал_потерян"):
        служебное.append("журнал телефона оборвался и не переподключился — "
                         "вердикт Apple мог не успеть прийти")
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
                # Канал называем по самой записи: «не из печати» верно для сверки с заводской
                # печатью, но тот же вердикт приходит и от доверия к модулю (iOS 16 пишет
                # «untrusted component battery» прямо из UI Настроек), и от словаря состояния.
                # Отказ без своего канала оценщик проверить не может.
                канал = str(h.get("источник") or "").strip() or "сверка Apple"
                stop.append(f"по данным Apple ({канал}): {h['деталь']} — "
                            "деталь неизвестного происхождения")
            elif h.get("бу"):
                stop.append(f"по истории Apple: {h['деталь']} меняли, установлена б/у деталь{when}")
            else:
                warn.append(f"по истории Apple: {h['деталь']} меняли (новая деталь{when})")
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
    elif jb and not jb.get("проверено"):
        unknown.append("джейлбрейк не проверился: " + str(jb.get("ошибка") or "нет данных"))
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
        "рфс": list(рфс) if рфс else None,      # реестр IMEI РК, по каждому IMEI
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
        "apple_история_перечитана": перечитан,     # вердикт поднят из сырых строк слепка
        "apple_история_почему": hist_why or None,
        "apple_раздел_открыт": bool(hist_meta.get("раздел_открыт")) or bool(hist),
        "стоп": stop, "сделать": todo, "внимание": warn, "не_прочиталось": unknown,
        "сверка_деталей": сверка_деталей,       # строка из «не_прочиталось», которую закрывает сотрудник
        "служебное": служебное,                 # неисправности нашего оборудования, не телефона
        "итог": {"вердикт": verdict[0], "почему": verdict[1]},
        "качество_чтения": snap.get("quality") or {},
    }
