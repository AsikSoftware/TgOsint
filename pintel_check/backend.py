# -*- coding: utf-8 -*-
"""Мост между ядром (core/*) и киоск-интерфейсом (qml/Main.qml).

Киоск живёт сам: фоновый наблюдатель замечает телефон на проводе и запускает
приёмку без единого клика — снимает данные, сразу спрашивает Sickw (кэш по
IMEI, повторное подключение бесплатно) и непрерывно слушает журнал ради
вердикта Apple, пока телефон не отключат. Интерфейсу отдаются готовые к
показу строки: вся логика и суждения — здесь и в core, QML только рисует.
"""
import json, re, threading, time

from PySide6.QtCore import Property, QObject, Signal, Slot

from core import apple, device, gsheet, price, setup, sickw, store, verdict

MANUAL = [
    ("экран_пятна",    "Экран: пятна, засветы"),
    ("экран_битые",    "Битые пиксели"),
    ("тач_мертвые",    "Тач: мёртвые зоны"),
    ("корпус",         "Корпус: вмятины, сколы"),
    ("стекло_зад",     "Заднее стекло: трещины"),
    ("камеры_рабочие", "Камеры дают картинку"),
    ("динамик",        "Динамик и микрофон"),
    ("вибро",          "Вибрация"),
    ("кнопки",         "Кнопки и переключатель"),
    ("зарядка",        "Заряжается, держит кабель"),
    ("faceid_работ",   "Face ID разблокирует"),
    ("влага",          "Следы влаги / вскрытия"),
]


def tone(v):
    v = str(v or "")
    if re.search(r"ОРИГИНАЛ|ИСПРАВЕН|ИДЕАЛ|ХОРОШИЙ|не меняли", v):
        return "ok"
    if re.search(r"ЗАМЕН|НЕОРИГ|СБОИ|ПРОБЛЕМ|МЕНЯЛИ", v):
        return "bad"
    if re.search(r"ВОПРОС|НЕПОЛНАЯ|РЕМОНТ", v):
        return "warn"
    return ""


def money(n, cur="₸"):
    if n is None:
        return "—"
    return f"{n:,}".replace(",", " ") + " " + (cur or "₸")


class Backend(QObject):
    stateChanged = Signal()
    phoneSeenChanged = Signal()
    resultChanged = Signal()
    priceInfoChanged = Signal()
    appleInfoChanged = Signal()
    sickwInfoChanged = Signal()
    driversChanged = Signal()
    settingsInfoChanged = Signal()
    syncInfoChanged = Signal()

    def __init__(self, watch=True, parent=None):
        super().__init__(parent)
        self._state = "idle"          # idle | reading | result | done | error
        self._phone_seen = False
        self._result = {}
        self._price = {}
        self._apple = {"state": "off"}
        self._sickw = {"state": "off"}
        self._drivers = {"state": "off", "items": [], "итог": ""}
        self._sync = {"state": "off", "msg": ""}
        self._settings = {}
        self._error = ""

        self._session = 0             # номер приёмки: старые потоки замолкают
        self._udid = None
        self._cid = None
        self._res = None
        self._sickw_data = None
        self._apple_items = None
        self._refresh_settings()
        if watch:
            threading.Thread(target=self._watch, daemon=True).start()

    # ---------- свойства для QML ----------

    def _mk(name, signal_name):                       # noqa: N805
        def g(self):
            return getattr(self, "_" + name)
        return Property("QVariant", g, notify=vars()[signal_name]) if False else None

    @Property(str, notify=stateChanged)
    def state(self):
        return self._state

    @Property(str, notify=stateChanged)
    def errorText(self):
        return self._error

    @Property(bool, notify=phoneSeenChanged)
    def phoneSeen(self):
        return self._phone_seen

    @Property("QVariant", notify=resultChanged)
    def result(self):
        return self._result

    @Property("QVariant", notify=priceInfoChanged)
    def priceInfo(self):
        return self._price

    @Property("QVariant", notify=appleInfoChanged)
    def appleInfo(self):
        return self._apple

    @Property("QVariant", notify=sickwInfoChanged)
    def sickwInfo(self):
        return self._sickw

    @Property("QVariant", notify=driversChanged)
    def drivers(self):
        return self._drivers

    @Property("QVariant", notify=settingsInfoChanged)
    def settingsInfo(self):
        return self._settings

    @Property("QVariant", notify=syncInfoChanged)
    def syncInfo(self):
        return self._sync

    @Property("QVariant", constant=True)
    def manualChecks(self):
        return [{"key": k, "label": t} for k, t in MANUAL]

    def _set(self, attr, value, signal):
        setattr(self, attr, value)
        signal.emit()

    # ---------- наблюдатель за кабелем ----------

    def _present(self):
        try:
            return device.udid()
        except Exception:
            return None

    def _watch(self):
        while True:
            u = self._present()
            if bool(u) != self._phone_seen:
                self._set("_phone_seen", bool(u), self.phoneSeenChanged)
            if u and self._state == "idle":
                self._begin(u)
            elif not u and self._state in ("reading", "result", "done", "error"):
                self._reset()
            time.sleep(2.0)

    def _reset(self):
        self._session += 1            # все потоки старой приёмки замолкают
        self._udid = self._cid = self._res = None
        self._sickw_data = self._apple_items = None
        self._error = ""
        self._set("_result", {}, self.resultChanged)
        self._set("_price", {}, self.priceInfoChanged)
        self._set("_apple", {"state": "off"}, self.appleInfoChanged)
        self._set("_sickw", {"state": "off"}, self.sickwInfoChanged)
        self._set("_state", "idle", self.stateChanged)

    def _begin(self, u):
        self._session += 1
        s = self._session
        self._udid = u
        self._set("_state", "reading", self.stateChanged)
        threading.Thread(target=self._intake, args=(s,), daemon=True).start()

    # ---------- приёмка ----------

    def _intake(self, s):
        try:
            raw = device.collect()
            res = verdict.build(raw)
            cid = store.create(raw["udid"], res, raw)
            est = price.estimate(res)
            store.update(cid, цена=est["итого"] or 0)
        except Exception as e:
            if s == self._session:
                self._error = f"{type(e).__name__}: {e}"
                self._set("_state", "error", self.stateChanged)
            return
        if s != self._session:
            return
        self._cid, self._res = cid, res
        self._set("_result", self._render(res), self.resultChanged)
        self._push_price(est)
        self._set("_state", "result", self.stateChanged)

        # Sickw — сразу, без вопросов. Кэш по IMEI бережёт деньги.
        imei = str(res["паспорт"].get("imei") or "")
        if sickw.key_available() and sickw.luhn_ok(imei):
            self._set("_sickw", {"state": "wait"}, self.sickwInfoChanged)
            threading.Thread(target=self._sickw_job, args=(s, imei), daemon=True).start()
        elif not sickw.key_available():
            self._set("_sickw", {"state": "nokey"}, self.sickwInfoChanged)

        # Вердикт Apple — слушаем непрерывно, пока телефон на проводе.
        self._set("_apple", {"state": "wait"}, self.appleInfoChanged)
        threading.Thread(target=self._apple_job, args=(s,), daemon=True).start()

    def _render(self, res):
        p, b, ju = res["паспорт"], res["батарея"], res["юридический"]
        alerts = []
        for text in res["стоп"]:
            alerts.append({"kind": "bad", "text": text})
        for text in res["сделать"]:
            alerts.append({"kind": "warn", "text": text})
        for text in res["внимание"]:
            alerts.append({"kind": "info", "text": text})

        def row(k, v, t=""):
            return {"k": str(k), "v": str(v), "tone": t}

        parts = [row(k, v["вердикт"] + (f' · {v["почему"]}' if v.get("почему") else ""),
                     tone(v["вердикт"]))
                 for k, v in res["детали"].items() if v["вердикт"] != "НЕТ В МОДЕЛИ"]

        cards = [
            {"title": "Паспорт", "rows": [
                row("Модель", p["модель"]), row("Номер модели", p["номер_модели"]),
                row("Серийный", p["серийник"]), row("IMEI", p["imei"]),
                row("Память", f'{p["память_гб"]} ГБ (свободно {p["свободно_гб"]})'),
                row("iOS", p["ios"])]},
            {"title": "Батарея", "rows": [
                row("Износ", f'{b["износ"]}%' if b["износ"] is not None else "не определился",
                    "ok" if (b["износ"] or 0) >= 85 else ("warn" if b["износ"] else "")),
                row("Циклов", b["циклы"]),
                row("Ёмкость", f'{b["ёмкость"]} / {b["завод"]} мА·ч')] +
                [row("⚠", t, "bad") for t in b["подделка"]]},
            {"title": "Детали", "rows": parts},
            {"title": "Статус", "rows": [
                row("Найти iPhone", ju["найти_iphone"]),
                row("Активация", ju["активация"]),
                row("Пароль", "стоит — попросите снять" if ju["пароль"] else "нет",
                    "warn" if ju["пароль"] else "ok"),
                row("MDM-надзор", "ЕСТЬ" if ju["mdm"] else "нет",
                    "bad" if ju["mdm"] else "ok")]},
        ]
        return {
            "модель": p["модель"],
            "память": f'{p["память_гб"]} ГБ',
            "итог": {"вердикт": res["итог"]["вердикт"],
                     "почему": res["итог"]["почему"],
                     "tone": tone(res["итог"]["вердикт"]) or "ok"},
            "alerts": alerts,
            "cards": cards,
        }

    def _push_price(self, est):
        self._set("_price", {
            "ready": est["база_известна"],
            "итого": money(est["итого"], est["валюта"]),
            "база": money(est["база"], est["валюта"]),
            "вычеты": [{"k": d["за_что"], "v": money(d["сумма"], est["валюта"])}
                       for d in est["вычеты"]],
            "отказ": est["отказ"],
            "нехватка": est["чего_не_хватает"],
        }, self.priceInfoChanged)

    def _reprice(self):
        if not self._res:
            return
        try:
            est = price.estimate(self._res, self._sickw_data, self._apple_items)
            if self._cid:
                store.update(self._cid, цена=est["итого"] or 0)
            self._push_price(est)
        except Exception:
            pass

    def _sickw_job(self, s, imei):
        try:
            d = sickw.lookup(imei)
        except Exception as e:
            if s == self._session:
                self._set("_sickw", {"state": "error", "msg": str(e)},
                          self.sickwInfoChanged)
            return
        if s != self._session:
            return
        self._sickw_data = d
        if self._cid:
            store.update(self._cid, sickw=d)
        blk = (d.get("чёрный_список") or "").strip()
        bad = blk and blk.upper() not in ("CLEAN", "CLEAR")
        rows = [{"k": k, "v": v, "tone": t} for k, v, t in [
            ("Чёрный список", blk or "—", "bad" if bad else "ok"),
            ("Цвет с завода", d.get("цвет") or "—", ""),
            ("Объём с завода", f'{d["объём_гб"]} ГБ' if d.get("объём_гб") else "—", ""),
            ("iCloud", d.get("icloud") or "—",
             "warn" if (d.get("icloud") or "").upper() == "ON" else ""),
            ("SIM-lock", d.get("sim_lock") or "—", ""),
            ("Гарантия", d.get("гарантия") or "—", ""),
            ("Дата покупки", d.get("дата_покупки") or "—", ""),
        ]]
        alerts = []
        if bad:
            alerts.append({"kind": "bad", "text": f"ЧЁРНЫЙ СПИСОК: {blk} — не принимать"})
        if (d.get("icloud") or "").upper() == "ON":
            alerts.append({"kind": "warn", "text": "iCloud включён — клиент должен выйти из Apple ID"})
        self._set("_sickw", {"state": "got", "rows": rows, "alerts": alerts},
                  self.sickwInfoChanged)
        self._reprice()

    def _apple_job(self, s):
        """Слушаем журнал непрерывно, пока эта приёмка жива."""
        alive = lambda: s == self._session
        while alive():
            try:
                items, _ = apple.capture(self._udid, seconds=30, keep_going=alive)
            except Exception:
                items = {}
            if not alive():
                return
            if items:
                self._apple_items = items
                if self._cid:
                    store.update(self._cid, apple=items)
                rows = [{"k": v["деталь"],
                         "v": ("МЕНЯЛИ — " + ("б/у" if v["бу"] else "новая") +
                               (f' · {v["дата"]}' if v.get("дата") else ""))
                              if v["меняли"] else "не меняли",
                         "tone": "bad" if v["меняли"] else "ok"}
                        for v in sorted(items.values(), key=lambda x: x.get("код", 0))]
                self._set("_apple", {"state": "got", "rows": rows},
                          self.appleInfoChanged)
                self._reprice()
                return
            if self._apple.get("state") != "wait":
                return                      # пропустили кнопкой

    # ---------- команды из QML ----------

    @Slot()
    def skipApple(self):
        if self._apple.get("state") == "wait":
            self._set("_apple", {"state": "skip"}, self.appleInfoChanged)

    @Slot("QVariant", str, str)
    def saveStage2(self, checks, colour, notes):
        r = dict(checks.toVariant() if hasattr(checks, "toVariant") else (checks or {}))
        r["цвет"] = colour.strip()
        r["заметки"] = notes.strip()
        if self._cid:
            store.update(self._cid, этап=2, этап2=r)

    @Slot(str, str)
    def saveStage3(self, final_price, method):
        if self._cid:
            store.update(self._cid, этап=3,
                         этап3={"итоговая_цена": final_price.strip(), "способ": method})
        self._set("_state", "done", self.stateChanged)

    # ---------- настройки ----------

    def _refresh_settings(self):
        try:
            cfg = price.load()
        except Exception:
            cfg = {}
        self._set("_settings", {
            "sickw_tail": sickw.key_tail(),
            "sheet_url": cfg.get("гугл_таблица") or gsheet.DEFAULT_URL,
            "sa_email": gsheet.sa_email(),
            "обновлён": cfg.get("прайс_обновлён") or "",
            "моделей": len(cfg.get("база") or {}),
        }, self.settingsInfoChanged)

    @Slot(str)
    def saveSickwKey(self, key):
        if key.strip():
            sickw.save_key(key)
            self._refresh_settings()

    @Slot()
    def removeSickwKey(self):
        sickw.save_key("")
        self._refresh_settings()

    @Slot(str)
    def syncPrices(self, url):
        self._set("_sync", {"state": "wait", "msg": "Скачиваю таблицу…"},
                  self.syncInfoChanged)

        def job():
            try:
                r = gsheet.sync(url)
            except Exception as e:
                self._set("_sync", {"state": "error", "msg": str(e)},
                          self.syncInfoChanged)
                return
            msg = f'Готово: {r["моделей"]} моделей, {r["позиций"]} позиций.'
            if r["не_распознано"]:
                msg += "\nНе распозналось: " + "; ".join(r["не_распознано"][:4])
            self._set("_sync", {"state": "ok", "msg": msg}, self.syncInfoChanged)
            self._refresh_settings()
            self._reprice()
        threading.Thread(target=job, daemon=True).start()

    @Slot()
    def checkDrivers(self):
        self._set("_drivers", {"state": "wait", "items": [], "итог": ""},
                  self.driversChanged)

        def job():
            try:
                r = setup.check()
            except Exception as e:
                self._set("_drivers", {"state": "error", "items": [],
                                       "итог": str(e)}, self.driversChanged)
                return
            items = [{"k": ("✅ " if i["готово"] else
                            ("⚪ " if i.get("необязательно") else "⛔ ")) + i["что"],
                      "v": i["где"] or i["почему"] or "",
                      "fix": "" if i["готово"] else (i.get("как_починить") or ""),
                      "tone": "ok" if i["готово"] else
                              ("" if i.get("необязательно") else "bad")}
                     for i in r["пункты"]]
            self._set("_drivers", {
                "state": "ok", "items": items,
                "итог": "Всё готово." if r["всё_готово"]
                        else f'Осталось сделать: {r["осталось"]}.',
            }, self.driversChanged)
        threading.Thread(target=job, daemon=True).start()
