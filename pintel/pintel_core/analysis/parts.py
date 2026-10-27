# -*- coding: utf-8 -*-
"""Единый вердикт по подлинности деталей — всегда есть ответ, на любом iPhone и iOS.

Три источника по убыванию достоверности (см. docs/RESEARCH_apple_parts.md):
  1. Привязка модулей из IORegistry (сигналы сопряжения) — детерминированно, все iOS,
     без действий клиента. Это те же seal-данные, что Apple показывает как «Unknown Part».
  2. MobileGestalt: FDRSealingStatus / IsServicePart — печать цела? деталь сервисная?
  3. Журнал «Запчасти и история обслуживания» — даты замен и метка «б/у»; нужен клиент.

Главное: вердикт по деталям собирается из каналов 1–2 (кабель, без клиента). Канал 3
только обогащает датами. «Клиент не открыл раздел» больше НЕ значит «проверка неполная».
"""

# сигнал сопряжения → какой детали он касается (для склейки с журналом)
SIGNAL_PART = {
    "Face ID ↔ плата": "FaceID", "Taptic ↔ плата": "Taptic", "Экран: калибровка": "Display",
    "Экран: стекло ↔ панель": "Display", "Датчик приближения": "Proximity", "Тачскрин": "Display",
    "Основная камера": "Camera", "Сверхширокая": "Camera", "Телефото": "Camera",
}
PART_RU = {"FaceID": "Face ID", "Display": "Экран", "Camera": "Камера", "Taptic": "Taptic Engine",
           "Proximity": "Датчик приближения", "Battery": "Аккумулятор", "BackGlass": "Заднее стекло",
           "Enclosure": "Корпус", "MTUB": "Верхний модуль", "LogicBoard": "Плата",
           "FrontCamera": "Фронтальная камера"}

# Что телефон пишет напротив детали в разделе «Детали и обслуживание».
# Формулировки — официальные, со страницы Apple support.apple.com/ru-ru/102658,
# плюс короткие варианты, которые показывает iOS 26 на самом экране.
# Третий элемент — наш статус детали: bad (СТОП) > used > repaired > ok.
APPLE_STATES = {
    "genuine":    ("Оригинальная запасная часть", "на экране: «Оригинальная запасная часть» / «Оригинал»", "ok"),
    "serviced":   ("Сервисное обслуживание", "деталь меняли в сервисе Apple (iOS 26 пишет так)", "repaired"),
    "used":       ("Запасная часть использовалась", "деталь уже стояла в другом iPhone", "used"),
    "unverified": ("Непроверенная запасная часть", "плату уже ставили в другой iPhone; Apple Pay может не работать", "bad"),
    "unknown":    ("Неизвестная запасная часть", "на экране: «Неизвестная запасная часть» / «Неизвестно»", "bad"),
    "finish":     ("Завершение ремонта", "калибровка не завершена: Face ID или Touch ID работать не будут", "repaired"),
    "absent":     ("В списке нет", "Apple по этой детали ничего не пишет", None),
}
# Детали, которые Apple показывает в разделе, в порядке её же таблицы.
APPLE_PART_ORDER = (("Battery", "Аккумулятор"), ("Display", "Дисплей"), ("LogicBoard", "Материнская плата"),
                    ("FrontCamera", "Фронтальная камера"), ("Camera", "Задние камеры"),
                    ("FaceID", "Face ID"), ("BackGlass", "Заднее стекло"))


def verdict(snap, signals, hist, battery, seal, hist_meta=None, apple_supported=True):
    """→ {итог, детали:[...], каналы:{...}, apple_подтверждено, почему}.

    итог: 'замена' (нарушена привязка / неизвестная деталь) — СТОП;
          'ремонт' (меняли на новую оригинал / б/у / есть записи) — внимание;
          'родные' — по кабелю чисто И Apple подтвердила: раздел «Детали и обслуживание»
                     прочитан вместе со сверкой деталей (или у модели раздела нет вовсе);
          'кабель' — по кабелю замен не видно, но подтверждения Apple нет: сверить на телефоне;
          'неполно' — ни один канал не дал ни одного факта.
    Зелёный вердикт без подтверждения Apple НЕ выдаётся: кабель не видит пересаженный
    оригинальный экран, а Apple видит (iPhone 15 Pro на демо показал «неизвестно»)."""
    parts = {}

    def note(key, status, why, source):
        """status: bad(подделка/чужая) > used(б/у) > repaired(новая оригинал) > ok(родная)."""
        rank = {"bad": 3, "used": 2, "repaired": 1, "ok": 0}
        cur = parts.get(key)
        if cur is None or rank[status] > rank[cur["статус"]]:
            parts[key] = {"деталь": PART_RU.get(key, key), "статус": status, "почему": why, "источник": source}

    had_cable = False
    # Канал 1: привязка модулей
    for name, s in (signals or {}).items():
        part = SIGNAL_PART.get(name)
        if not part:
            continue
        if s["ок"] is False:
            note(part, "bad", s["почему"], "привязка (кабель)")
            had_cable = True
        elif s["ок"] is True:
            note(part, "ok", s["почему"], "привязка (кабель)")
            had_cable = True
    # батарея: подделка/аутентификация
    if battery and battery.get("есть_данные"):
        had_cable = True
        if battery.get("подделка"):
            note("Battery", "bad", battery["подделка"][0], "батарея (кабель)")
        else:
            note("Battery", "ok", "ёмкость в норме заводской", "батарея (кабель)")
    # Канал 2: печать Apple (seal)
    if seal:
        if seal.get("печать_цела") is False:
            note("LogicBoard", "bad", "заводская печать нарушена (FDR)", "печать Apple")
            had_cable = True
        if seal.get("сервисная_деталь") is True:
            note("LogicBoard", "repaired", "установлена сервисная деталь (IsServicePart)", "печать Apple")
            had_cable = True

    # Канал 3: журнал — обогащаем датами и метками «б/у»/«неизвестная»
    had_log = False
    for comp, h in (hist or {}).items():
        if comp == "RepairRecords":
            had_log = True
            parts.setdefault("_records", {"деталь": "Записи о ремонте Apple", "статус": "repaired",
                                          "почему": "у Apple есть записи — подробности на экране телефона",
                                          "источник": "журнал Apple"})
            continue
        key = comp
        had_log = True
        d = h.get("дата") or ""
        if h.get("неизвестная"):
            note(key, "bad", "деталь неизвестного происхождения" + (f", {d}" if d else ""), "журнал Apple")
        elif h.get("бу"):
            note(key, "used", "б/у деталь" + (f", {d}" if d else ""), "журнал Apple")
        elif h.get("меняли"):
            note(key, "repaired", "меняли на новую оригинальную" + (f", {d}" if d else ""), "журнал Apple")
        else:
            note(key, "ok", "не меняли" + (f" (журнал, {d})" if d else " (журнал)"), "журнал Apple")

    # Подтверждение Apple: сверка с заводской печатью прочитана (iOS 18 — сама сверка;
    # iOS 26 — записи вместе со строками сверки). Одни записи с нулями подтверждением
    # не считаются: на демо они были нулевыми при «неизвестной» детали на экране телефона.
    meta = hist_meta or {}
    fmt = str(meta.get("формат") or "")
    apple_ok = bool(hist) and (fmt.startswith("сверка") or meta.get("дельта") is not None
                               or any(str(h.get("источник") or "").startswith("сверка") for h in hist.values()))

    details = [v for k, v in parts.items()]
    statuses = {p["статус"] for p in details}
    if "bad" in statuses:
        итог = "замена"
    elif "used" in statuses or "repaired" in statuses:
        итог = "ремонт"
    elif had_cable or had_log:
        итог = "родные" if (apple_ok or not apple_supported) else "кабель"
    else:
        итог = "неполно"
    why = ""
    if итог == "кабель":
        why = ("по кабелю замен не видно, но Apple подлинность не подтвердила: "
               + ("записи получены, а сверка деталей не прочиталась" if hist
                  else "раздел «Детали и обслуживание» на телефоне не открыт")
               + " — сверить на экране телефона")
    elif итог == "неполно":
        why = "ни один канал не дал данных — сверить на экране телефона"
    return {"итог": итог, "детали": details, "каналы": {"кабель": had_cable, "журнал": had_log},
            "apple_подтверждено": apple_ok, "почему": why}
