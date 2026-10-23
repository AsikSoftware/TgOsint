# -*- coding: utf-8 -*-
"""Окно киоска: состояния «ожидание → проверка → результат → талон», опрос кабеля,
связь с сервером в фоне. Запуск: pintel-kiosk (kiosk.toml рядом с exe)."""
import asyncio
import os
import sys
import time
import traceback

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from pintel_core.devicelink import connect
from pintel_core.devicelink.connect import NO_DEVICE, NO_DRIVER, READY

from . import __version__, config, ui
from .client import Client, ServerError
from .worker import Pipeline


class Poller(QThread):
    """Раз в полторы секунды: есть ли телефон на кабеле и жив ли драйвер."""
    tick = Signal(str, str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = False

    def run(self):
        while not self._stop:
            try:
                st, detail, devs = asyncio.run(connect.list_usb())
                self.tick.emit(st, detail or "", len(devs or []))
            except Exception as e:                               # noqa: BLE001
                self.tick.emit(NO_DRIVER, str(e), 0)
            for _ in range(15):
                if self._stop:
                    return
                time.sleep(0.1)

    def stop(self):
        self._stop = True


class NetThread(QThread):
    """Фон: пульс на сервер, досылка очереди, прайс раз в 15 минут."""
    status = Signal(bool, str)
    price = Signal(dict)

    def __init__(self, client, cfg, parent=None):
        super().__init__(parent)
        self.client, self.cfg = client, cfg
        self._stop = False
        self.device_state = "?"

    def run(self):
        last_price = 0
        while not self._stop:
            if self.client.enabled:
                try:
                    sent = self.client.flush_queue()
                    self.client.heartbeat({"драйвер": self.device_state != NO_DRIVER, "телефон": self.device_state,
                                           "в_очереди": self.client.queued(), "версия": __version__})
                    self.status.emit(True, "сервер на связи" + (f", дослано {sent}" if sent else ""))
                    if time.time() - last_price > 900:
                        g = self.client.price()
                        if g:
                            self.price.emit(g)
                        last_price = time.time()
                except ServerError as e:
                    self.status.emit(False, str(e))
                except Exception as e:                           # noqa: BLE001
                    self.status.emit(False, f"{type(e).__name__}: {e}")
            for _ in range(600):
                if self._stop:
                    return
                time.sleep(0.1)

    def stop(self):
        self._stop = True


class Task(QThread):
    """Одноразовое сетевое действие вне UI-потока."""
    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.fn()
        except Exception:                                        # noqa: BLE001
            pass


class KioskWindow(QMainWindow):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.client = Client(cfg)
        self.grid = None
        self.state = "idle"
        self.wait_unplug = False
        self.pipeline = None
        self.last = None
        self.tasks = []
        self.setWindowTitle("Pintel Kiosk")
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.s_main = ui.MainScreen(cfg.get("point") or "")
        self.s_scan = ui.ScanScreen()
        self.s_result = ui.ResultScreen(cfg.get("currency", "₸"))
        self.s_ticket = ui.TicketScreen()
        for s in (self.s_main, self.s_scan, self.s_result, self.s_ticket):
            self.stack.addWidget(s)
        self.s_scan.skip_requested.connect(self.on_skip_apple)
        self.s_result.sell.connect(self.on_sell)
        self.s_result.just_looking.connect(self.on_just_looking)
        self.return_timer = QTimer(self)
        self.return_timer.setSingleShot(True)
        self.return_timer.timeout.connect(self.go_home)
        self.poller = Poller(self)
        self.poller.tick.connect(self.on_tick)
        self.poller.start()
        self.net = NetThread(self.client, cfg, self)
        self.net.status.connect(self.on_net)
        self.net.price.connect(self.on_price)
        self.net.start()
        QShortcut(QKeySequence("Escape"), self, activated=self.toggle_fullscreen)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        try:
            g = self.client.price()
            if g:
                self.on_price(g)
        except Exception:                                        # noqa: BLE001
            pass
        if not self.client.enabled:
            self.s_main.set_status("Сервер не настроен: kiosk.toml", ok=False)
        self._try_server_config()

    # ---------- служебное ----------
    def _try_server_config(self):
        def job():
            try:
                c = self.client.config()
                if c.get("точка"):
                    self.s_main.point_label.setText(f"Выкуп iPhone · {c['точка']}")
                self.cfg["return_seconds"] = c.get("возврат_с") or self.cfg["return_seconds"]
                self.cfg["apple_history_seconds"] = c.get("история_apple_с") or self.cfg["apple_history_seconds"]
            except Exception:                                    # noqa: BLE001
                pass
        self._run(job)

    def _run(self, fn):
        t = Task(fn, self)
        self.tasks = [x for x in self.tasks if x.isRunning()] + [t]
        t.start()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def closeEvent(self, e):
        self.poller.stop()
        self.net.stop()
        if self.pipeline and self.pipeline.isRunning():
            self.pipeline.cancel.set()
        super().closeEvent(e)

    # ---------- события ----------
    def on_net(self, ok, text):
        if self.state == "idle" and self.client.enabled:
            self.s_main.set_status("Готов к работе" if ok else f"Автономно: {text}", ok=ok)

    def on_price(self, grid):
        self.grid = grid

    def on_tick(self, state, detail, count):
        self.net.device_state = state
        if self.state == "idle":
            if state == NO_DRIVER:
                self.s_main.set_status("Нет драйвера Apple — установите iTunes", ok=False)
            elif state == READY and count and not self.wait_unplug:
                self.start_check()
            elif state == NO_DEVICE:
                self.wait_unplug = False
                if self.client.enabled and self.client.online:
                    self.s_main.set_status("Готов к работе", ok=True)
        elif self.state == "scanning":
            if state == NO_DEVICE and self.pipeline:
                self.pipeline.cancel.set()
                self.s_scan.set_trouble("Телефон отключили. Подключите снова, и проверка начнётся заново.")
                self.state = "failed"
                QTimer.singleShot(3000, self.go_home)
        elif self.state in ("result", "ticket"):
            if state == NO_DEVICE:
                QTimer.singleShot(1500, self.go_home)

    def start_check(self):
        self.state = "scanning"
        self.wait_unplug = True
        self.s_scan.reset()
        self.stack.setCurrentWidget(self.s_scan)
        self.pipeline = Pipeline(self.cfg, self.client, self.grid, self)
        self.pipeline.status.connect(self.on_link_status)
        self.pipeline.step.connect(self.s_scan.set_step)
        self.pipeline.apple_prompt.connect(self.s_scan.show_prompt)
        self.pipeline.done.connect(self.on_done)
        self.pipeline.failed.connect(self.on_failed)
        self.pipeline.start()

    def on_link_status(self, state, human):
        if state != READY:
            self.s_scan.set_step("connect", "run", human)
            self.s_scan.set_trouble(human)
        else:
            self.s_scan.set_trouble("Не отключайте кабель. Обычно это занимает около минуты.")

    def on_skip_apple(self):
        if self.pipeline:
            self.pipeline.skip_apple.set()

    def on_done(self, result):
        if self.state != "scanning":
            return
        self.last = result
        self.s_result.fill(result["report"], result.get("server"))
        self.stack.setCurrentWidget(self.s_result)
        self.state = "result"
        self.return_timer.start(int(self.cfg.get("return_seconds", 60)) * 3000)

    def on_failed(self, text):
        if self.state != "scanning":
            return
        self.state = "failed"
        self.s_scan.set_step("connect", "fail", "не удалось")
        self.s_scan.set_trouble("Не получилось прочитать телефон: " + text + ". Подключите заново или подойдите к сотруднику.")
        QTimer.singleShot(8000, self.go_home)

    def on_sell(self):
        if not self.last:
            return
        server = self.last.get("server")
        if server and server.get("id"):
            self._run(lambda: self.client.decision(server["id"], "sell"))
        self.s_ticket.fill(self.last["report"], server, int(self.cfg.get("return_seconds", 60)))
        self.stack.setCurrentWidget(self.s_ticket)
        self.state = "ticket"
        self.return_timer.start(int(self.cfg.get("return_seconds", 60)) * 1000)

    def on_just_looking(self):
        if self.last:
            server = self.last.get("server")
            if server and server.get("id"):
                self._run(lambda: self.client.decision(server["id"], "viewed"))
        self.go_home()

    def go_home(self):
        self.return_timer.stop()
        self.state = "idle"
        self.last = None
        self.stack.setCurrentWidget(self.s_main)


def main(argv=None):
    cfg = config.load()
    app = QApplication(argv or sys.argv)
    app.setApplicationName("Pintel Kiosk")
    ui.load_fonts()
    app.setStyleSheet(ui.QSS)
    w = KioskWindow(cfg)
    w.resize(1920, 1080)
    if cfg.get("fullscreen", True):
        w.showFullScreen()
    else:
        w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
