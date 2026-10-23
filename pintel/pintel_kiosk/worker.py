# -*- coding: utf-8 -*-
"""Поток проверки: ждёт телефон → слепок → отчёт → история Apple (с подсказкой на
экране) → Sickw через сервер → цена → отправка. Всё на pintel_core, ничего не дублируем."""
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


class Pipeline(QThread):
    status = Signal(str, str)                 # состояние связи: state, текст
    step = Signal(str, str, str)              # шаг: ключ, состояние (wait|run|done|warn|fail), подпись
    apple_prompt = Signal(bool)               # показать/скрыть панель «один шаг на телефоне»
    done = Signal(dict)                       # результат
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
            self._log(traceback.format_exc())
            self.failed.emit(f"{type(e).__name__}: {e}")

    def _log(self, text):
        try:
            with open(os.path.join(data_dir(), "logs", "kiosk.log"), "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
        except Exception:                                        # noqa: BLE001
            pass

    async def _main(self):
        self.step.emit("connect", "run", "ждём «Доверять»")
        st = None
        while not self.cancel.is_set():
            st = await connect.wait_ready(on_status=lambda s: self.status.emit(s.state, s.human),
                                          deadline=time.monotonic() + 2.0)
            if st.state == READY:
                break
            if st.state in ("NO_DEVICE",):
                self.failed.emit("телефон отключили")
                return
            await asyncio.sleep(0.5)
        if self.cancel.is_set():
            return
        ld = st.lockdown
        self.serial = st.serial
        self.step.emit("connect", "done", "телефон на связи")

        diag, tries = await connect.open_diagnostics(ld)
        self.step.emit("passport", "run", "")
        snap = await snapshot.collect(ld, diag)
        snap["quality"]["диагностика_попыток"] = tries
        snap["quality"]["подключение"] = st.timings
        try:
            await diag.close()
        except Exception:                                        # noqa: BLE001
            pass
        rep = report_mod.build(snap)
        pas, bat = rep["паспорт"], rep["батарея"]
        self.step.emit("passport", "done", f"{pas['модель']} · {rep['память'].get('объём_гб') or '?'} ГБ")
        h = bat.get("здоровье_%")
        self.step.emit("battery", "done" if h is not None else "warn",
                       f"{h} %" if h is not None else "не прочиталась")
        leg = rep["правовой"]
        locks = [x for x, ok in (("Найти iPhone", leg["найти_iphone"] != "включён"),
                                 ("надзор MDM", leg["mdm"] is not True), ("пароль", not leg["пароль"])) if not ok]
        self.step.emit("locks", "done" if not locks else "warn", "чисто" if not locks else ", ".join(locks))

        # история обслуживания Apple — ждём шаг на телефоне
        secs = int(self.cfg.get("apple_history_seconds") or 90)
        self.apple_prompt.emit(True)
        self.step.emit("apple", "run", f"ждём один шаг на телефоне · {secs} с")
        items, raw, waited = await repair_history.capture(
            ld, seconds=secs, keep_going=lambda: not (self.skip_apple.is_set() or self.cancel.is_set()),
            on_tick=lambda s: self.step.emit("apple", "run", f"ждём один шаг на телефоне · {max(0, secs - s)} с"))
        self.apple_prompt.emit(False)
        snap["repair_history"], snap["repair_history_raw"] = items, raw
        rep = report_mod.build(snap)
        self.step.emit("apple", "done" if items else "warn",
                       "получена" if items else ("пропущена" if self.skip_apple.is_set() else "не открыли раздел"))
        if self.cancel.is_set():
            return

        # Sickw через сервер (ключ только там)
        imei = pas.get("imei") or ""
        if self.cfg.get("sickw", True) and self.client.enabled and sickw.luhn_ok(imei):
            self.step.emit("sickw", "run", "")
            try:
                snap["sickw"] = self.client.sickw(imei)
                rep = report_mod.build(snap)
                sk = rep.get("sickw") or {}
                self.step.emit("sickw", "done" if sk.get("в_чёрном_списке") is not True else "fail",
                               "чисто" if sk.get("в_чёрном_списке") is False else (sk.get("чёрный_список") or "проверено"))
            except ServerError as e:
                self.step.emit("sickw", "warn", "база недоступна")
                self._log(f"sickw: {e}")
        else:
            self.step.emit("sickw", "warn", "пропущена")

        # цена
        grid = self.grid or self.client.price()
        if grid:
            rep["цена"] = pricing.estimate(grid, pas["код_модели"], rep["память"].get("объём_гб"),
                                           bat.get("здоровье_%"), bat.get("циклы"), self.cfg.get("currency", "₸"))
        else:
            rep["цена"] = {"валюта": self.cfg.get("currency", "₸"), "цена": None,
                           "основание": "прайс не загружен", "нехватка": ["нет прайса"]}

        # сохраняем локально и отправляем
        cid = f"{self.serial or 'phone'}-{uuid.uuid4().hex[:12]}"
        out = os.path.join(data_dir(), "out", f"{datetime.now():%Y%m%d_%H%M%S}_{(self.serial or 'phone')[:12]}")
        os.makedirs(out, exist_ok=True)
        snap_json = snapshot.dumps(snap)
        rep_json = snapshot.dumps(rep)
        open(os.path.join(out, "snapshot.json"), "w", encoding="utf-8").write(snap_json)
        open(os.path.join(out, "report.json"), "w", encoding="utf-8").write(rep_json)
        payload = {"client_id": cid, "report": json.loads(rep_json), "snapshot": json.loads(snap_json)}
        self.step.emit("upload", "run", "")
        server = self.client.upload(payload) if self.client.enabled else None
        self.step.emit("upload", "done" if server else "warn", "отправлено" if server else "отправим позже")
        self.done.emit({"report": rep, "server": server, "client_id": cid, "serial": self.serial, "out": out})
