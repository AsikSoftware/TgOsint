# -*- coding: utf-8 -*-
"""Поток проверки: ждёт телефон → слушатель журнала стартует СРАЗУ → слепок →
отчёт → ждём историю Apple (подсказка на экране) → Sickw через сервер → цена →
отправка → `done`. Дальше поток не умирает: слушатель живёт, пока телефон на
кабеле, и если клиент открыл раздел позже — приходит `history`, карточка и
сервер обновляются. Всё на pintel_core, ничего не дублируем."""
import asyncio
import json
import os
import threading
import time
import traceback
import uuid
from datetime import datetime

from PySide6.QtCore import QThread, Signal

from pintel_core.analysis import report as report_mod
from pintel_core.devicelink import connect, repair_history, snapshot
from pintel_core.devicelink.connect import READY
from pintel_core.external import pricing, sickw

from .client import ServerError
from .config import data_dir


def log_line(text):
    try:
        with open(os.path.join(data_dir(), "logs", "kiosk.log"), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
    except Exception:                                            # noqa: BLE001
        pass


class Pipeline(QThread):
    status = Signal(str, str)                 # состояние связи: state, текст
    step = Signal(str, str, str)              # шаг: ключ, состояние (wait|run|done|warn|fail), подпись
    apple_prompt = Signal(bool)               # показать/скрыть панель «один шаг на телефоне»
    done = Signal(dict)                       # результат (отчёт, ответ сервера, …)
    history = Signal(dict)                    # история Apple пришла позже: обновлённый результат
    failed = Signal(str)                      # человеческий текст ошибки

    def __init__(self, cfg, client, grid=None, parent=None):
        super().__init__(parent)
        self.cfg, self.client, self.grid = cfg, client, grid
        self.skip_apple = threading.Event()
        self.cancel = threading.Event()
        self.serial = None

    def run(self):
        try:
            asyncio.run(self._main())
        except Exception as e:                                   # noqa: BLE001
            log_line(traceback.format_exc())
            self.failed.emit(f"{type(e).__name__}: {e}")

    def _step(self, key, state, text=""):
        log_line(f"шаг {key}: {state} {text}".rstrip())
        self.step.emit(key, state, text)

    async def _main(self):
        self._step("connect", "run", "ждём «Доверять»")
        st = None
        while not self.cancel.is_set():
            st = await connect.wait_ready(on_status=lambda s: (log_line(f"связь: {s.state} {s.human}"),
                                                               self.status.emit(s.state, s.human)),
                                          deadline=time.monotonic() + 2.0)
            if st.state == READY:
                break
            if st.state == "NO_DEVICE":
                self.failed.emit("телефон отключили")
                return
            await asyncio.sleep(0.5)
        if self.cancel.is_set():
            return
        ld = st.lockdown
        self.serial = st.serial
        self._step("connect", "done", "телефон на связи")

        # Слушатель журнала — с первой секунды: если клиент откроет раздел, пока идёт
        # слепок, записи не пропадут.
        listener = repair_history.Listener(ld, log=log_line)
        await listener.start()
        self.apple_prompt.emit(True)
        try:
            await self._flow(ld, st, listener)
        finally:
            await listener.stop()

    async def _flow(self, ld, st, listener):
        diag, tries = await connect.open_diagnostics(ld)
        self._step("passport", "run")
        snap = await snapshot.collect(ld, diag)
        snap["quality"]["диагностика_попыток"] = tries
        snap["quality"]["подключение"] = st.timings
        try:
            await diag.close()
        except Exception:                                        # noqa: BLE001
            pass
        rep = report_mod.build(snap)
        pas, bat = rep["паспорт"], rep["батарея"]
        self._step("passport", "done", f"{pas['модель']} · {rep['память'].get('объём_гб') or '?'} ГБ")
        h = bat.get("здоровье_%")
        self._step("battery", "done" if h is not None else "warn", f"{h} %" if h is not None else "не прочиталась")
        leg = rep["правовой"]
        locks = [x for x, ok in (("Найти iPhone", leg["найти_iphone"] != "включён"),
                                 ("надзор MDM", leg["mdm"] is not True), ("пароль", not leg["пароль"])) if not ok]
        self._step("locks", "done" if not locks else "warn", "чисто" if not locks else ", ".join(locks))

        # история Apple: ждём шаг на телефоне (слушатель уже работает)
        secs = int(self.cfg.get("apple_history_seconds") or 90)
        self._step("apple", "run", f"ждём один шаг на телефоне · {secs} с")
        items, raw, waited = await listener.wait(
            secs, keep_going=lambda: not (self.skip_apple.is_set() or self.cancel.is_set()),
            on_tick=lambda s: self.step.emit("apple", "run", f"ждём один шаг на телефоне · {max(0, secs - s)} с"))
        self.apple_prompt.emit(False)
        snap["repair_history"], snap["repair_history_raw"] = items, raw
        rep = report_mod.build(snap)
        self._step("apple", "done" if items else "warn",
                   "получена" if items else ("пропущена" if self.skip_apple.is_set() else "раздел пока не открыт"))
        log_line(f"история Apple: {'есть' if items else 'нет'} за {waited} с, строк журнала {listener.lines}, "
                 f"подключений {listener.connects}, обрывов {listener.reconnects}")
        if self.cancel.is_set():
            return

        # Sickw через сервер (ключ только там)
        imei = pas.get("imei") or ""
        if self.cfg.get("sickw", True) and self.client.enabled and sickw.luhn_ok(imei):
            self._step("sickw", "run")
            try:
                snap["sickw"] = self.client.sickw(imei)
                rep = report_mod.build(snap)
                sk = rep.get("sickw") or {}
                self._step("sickw", "done" if sk.get("в_чёрном_списке") is not True else "fail",
                           "чисто" if sk.get("в_чёрном_списке") is False else (sk.get("чёрный_список") or "проверено"))
            except ServerError as e:
                self._step("sickw", "warn", "база недоступна")
                log_line(f"sickw: {e}")
        else:
            self._step("sickw", "warn", "пропущена")

        rep["цена"] = self._price(rep)

        # сохраняем локально и отправляем
        cid = f"{self.serial or 'phone'}-{uuid.uuid4().hex[:12]}"
        out = os.path.join(data_dir(), "out", f"{datetime.now():%Y%m%d_%H%M%S}_{(self.serial or 'phone')[:12]}")
        os.makedirs(out, exist_ok=True)
        self._save(out, snap, rep)
        payload = {"client_id": cid, "report": json.loads(snapshot.dumps(rep)),
                   "snapshot": json.loads(snapshot.dumps(snap))}
        self._step("upload", "run")
        server = self.client.upload(payload) if self.client.enabled else None
        self._step("upload", "done" if server else "warn", "отправлено" if server else "отправим позже")
        result = {"report": rep, "server": server, "client_id": cid, "serial": self.serial, "out": out}
        self.done.emit(result)
        if items or self.cancel.is_set():
            return

        # Раздел так и не открыли — слушаем дальше, пока телефон на кабеле
        self._step("apple", "run", "ждём историю Apple")
        items, raw, waited = await listener.wait(6 * 3600, keep_going=lambda: not self.cancel.is_set(), grace=2.0)
        if not items:
            return
        snap["repair_history"], snap["repair_history_raw"] = items, raw
        rep = report_mod.build(snap)
        rep["цена"] = self._price(rep)
        self._save(out, snap, rep)
        log_line(f"история Apple пришла позже, через {waited} с")
        if server and server.get("id") and self.client.enabled:
            try:
                self.client.update_evaluation(server["id"], json.loads(snapshot.dumps(rep)),
                                              {"repair_history": items, "repair_history_raw": raw})
            except ServerError as e:
                log_line(f"обновление оценки не ушло: {e}")
        self._step("apple", "done", "получена")
        self.history.emit({**result, "report": rep})

    def _price(self, rep):
        pas, bat = rep["паспорт"], rep["батарея"]
        grid = self.grid or self.client.price()
        if grid:
            return pricing.estimate(grid, pas["код_модели"], rep["память"].get("объём_гб"),
                                    bat.get("здоровье_%"), bat.get("циклы"), self.cfg.get("currency", "₸"))
        return {"валюта": self.cfg.get("currency", "₸"), "цена": None, "основание": "прайс не загружен",
                "нехватка": ["нет прайса"]}

    @staticmethod
    def _save(out, snap, rep):
        open(os.path.join(out, "snapshot.json"), "w", encoding="utf-8").write(snapshot.dumps(snap))
        open(os.path.join(out, "report.json"), "w", encoding="utf-8").write(snapshot.dumps(rep))
