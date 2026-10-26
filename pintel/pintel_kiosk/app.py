# -*- coding: utf-8 -*-
"""Окно киоска: состояния «ожидание → проверка → результат → талон», опрос кабеля,
связь с сервером в фоне. Запуск: pintel-kiosk (kiosk.toml рядом с exe)."""
import asyncio
import os
import sys
import time
import traceback

from PySide6.QtCore import QRectF, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPalette, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsScene, QGraphicsView, QMainWindow, QStackedWidget

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


DESIGN_W, DESIGN_H = 1920, 1080


class ScaledHost(QGraphicsView):
    """Экраны свёрстаны на 1920×1080 и масштабируются целиком под любой монитор
    (как вектор), ничего не съезжает. Поля по краям — в цвет текущего экрана."""

    def __init__(self, inner):
        super().__init__()
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        inner.setFixedSize(DESIGN_W, DESIGN_H)
        self.proxy = self.scene_.addWidget(inner)
        self.scene_.setSceneRect(QRectF(0, 0, DESIGN_W, DESIGN_H))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setAlignment(Qt.AlignCenter)
        self.set_bg("#FFFFFF")

    def set_bg(self, color):
        self.setBackgroundBrush(QColor(color))

    def _fit(self):
        if self.width() < 10 or self.height() < 10:
            return
        k = min(self.width() / DESIGN_W, self.height() / DESIGN_H)
        self.resetTransform()
        self.scale(k, k)
        self.centerOn(DESIGN_W / 2, DESIGN_H / 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def showEvent(self, e):
        super().showEvent(e)
        self._fit()


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
        self.host = ScaledHost(self.stack)
        self.setCentralWidget(self.host)
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
    def show_screen(self, w):
        self.stack.setCurrentWidget(w)
        self.host.set_bg("#F3F6FA" if w is self.s_result else "#FFFFFF")

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
        for t in (self.poller, self.net, self.pipeline, *self.tasks):
            if t is not None and t.isRunning():
                t.wait(3000)                     # иначе Qt ругается «Destroyed while thread is still running»
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
                self.s_main.set_device("nodriver")
            elif state == READY and count and not self.wait_unplug:
                self.s_main.set_device("found")
                self.start_check()
            elif state == NO_DEVICE:
                self.wait_unplug = False
                self.s_main.set_device("wait")
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
        if self.pipeline and self.pipeline.isRunning():
            self.pipeline.cancel.set()
            self.pipeline.wait(3000)
        self.state = "scanning"
        self.wait_unplug = True
        self.s_scan.reset()
        self.show_screen(self.s_scan)
        self.pipeline = Pipeline(self.cfg, self.client, self.grid, self)
        self.pipeline.status.connect(self.on_link_status)
        self.pipeline.step.connect(self.s_scan.set_step)
        self.pipeline.apple_prompt.connect(self.s_scan.show_prompt)
        self.pipeline.done.connect(self.on_done)
        self.pipeline.history.connect(self.on_history)
        self.pipeline.failed.connect(self.on_failed)
        self.pipeline.start()

    def on_history(self, result):
        """История Apple пришла после результата — обновляем карточку."""
        if self.last and result.get("client_id") == self.last.get("client_id"):
            self.last = result
            if self.state in ("result", "ticket"):
                self.s_result.fill(result["report"], result.get("server"))

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
        self.show_screen(self.s_result)
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
        self.show_screen(self.s_ticket)
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
        if self.pipeline and self.pipeline.isRunning():
            self.pipeline.cancel.set()                 # слушатель истории больше не нужен
        self.state = "idle"
        self.last = None
        self.s_main.set_device("wait")
        self.show_screen(self.s_main)


def light_palette():
    """Киоск всегда светлый, какая бы тема ни стояла в Windows."""
    pal = QPalette()
    for role in (QPalette.Window, QPalette.Base, QPalette.AlternateBase, QPalette.Button, QPalette.ToolTipBase):
        pal.setColor(role, QColor("#FFFFFF"))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.ToolTipText):
        pal.setColor(role, QColor("#0B1B33"))
    pal.setColor(QPalette.Highlight, QColor("#1A549D"))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.PlaceholderText, QColor("#5B7392"))
    return pal


def main(argv=None):
    cfg = config.load()
    if sys.platform == "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "windows:darkmode=0")   # не следовать тёмной теме Windows
    app = QApplication(argv or sys.argv)
    app.setApplicationName("Pintel Kiosk")
    app.setStyle("Fusion")
    app.setPalette(light_palette())
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
