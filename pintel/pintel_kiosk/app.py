# -*- coding: utf-8 -*-
"""Окно киоска: состояния «ожидание → проверка → результат», опрос кабеля,
связь с сервером в фоне. Запуск: pintel-kiosk (kiosk.toml рядом с exe)."""
import asyncio
import os
import sys
import time
import traceback
from datetime import datetime

from PySide6.QtCore import QRectF, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPalette, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsScene, QGraphicsView, QMainWindow, QStackedWidget

from pintel_core.devicelink import connect
from pintel_core.devicelink.connect import NO_DEVICE, NO_DRIVER, READY

from . import __version__, config, ui, ui_deal
from .client import Client, ServerError
from .config import data_dir
from .worker import Pipeline, log_line, убрать_старое


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
            if not self.client.enabled and time.time() - last_price > 900:
                try:                                            # автономно: прайс прямо из таблицы
                    g = self.client.price()
                    if g:
                        self.price.emit(g)
                except Exception:                               # noqa: BLE001
                    pass
                last_price = time.time()
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
    """Одноразовое сетевое действие вне UI-потока.

    Результат и ошибку отдаёт сигналами: сотруднику нужно видеть, чем кончилась
    отправка сделки, а не гадать, почему ничего не произошло."""
    ok = Signal(object)
    err = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.ok.emit(self.fn())
        except Exception as e:                                   # noqa: BLE001
            log_line("задача не выполнилась: " + traceback.format_exc())
            self.err.emit(f"{type(e).__name__}: {e}")


class IntakePoller(QThread):
    """Пока показан результат: раз в 2,5 с спрашиваем сервер, выдан ли номер заявки
    (его выдаёт сотрудник в кассе, записав имя и телефон клиента)."""
    state = Signal(dict)

    def __init__(self, client, ev_id, parent=None):
        super().__init__(parent)
        self.client, self.ev_id = client, ev_id
        self._stop = False

    def run(self):
        while not self._stop:
            try:
                self.state.emit(self.client.intake(self.ev_id))
            except Exception:                                    # noqa: BLE001 — нет связи: попробуем ещё
                pass
            for _ in range(25):
                if self._stop:
                    return
                time.sleep(0.1)

    def stop(self):
        self._stop = True


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
        self.intake = None
        self.last_intake = None
        self.last = None
        self.tasks = []
        self.setWindowTitle("Pintel Kiosk")
        self.stack = QStackedWidget()
        self.host = ScaledHost(self.stack)
        self.setCentralWidget(self.host)
        точка = cfg.get("point") or ""
        self.s_main = ui.MainScreen(точка)
        self.s_client = ui_deal.ClientScreen(точка)
        self.s_scan = ui.ScanScreen(точка)
        self.s_result = ui.ResultScreen()
        self.s_eval = ui_deal.EvalScreen(точка)
        self.s_done = ui_deal.DoneScreen()
        for s in (self.s_main, self.s_client, self.s_scan, self.s_result, self.s_eval, self.s_done):
            self.stack.addWidget(s)
        self.s_main.начать.connect(self.начать_сделку)
        self.s_client.дальше.connect(self.клиент_готов)
        self.s_client.назад.connect(self.go_home)
        self.s_scan.skip_requested.connect(self.on_skip_apple)
        self.s_result.just_looking.connect(self.go_home)   # «Готово» — вернуться к началу
        self.s_eval.отправить.connect(self.отправить_в_оценку)
        self.s_eval.назад.connect(self.go_home)
        self.s_eval.новый_код.connect(self.новый_код_медиа)
        self.код_медиа = ""
        self.s_done.печать.connect(self.напечатать_чек)
        self.s_done.заново.connect(self.go_home)
        self.клиент, self.сделка, self.кабель = {}, {}, NO_DEVICE
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
        if cfg.get("_ошибка"):
            # сломанный или недописанный kiosk.toml виден сразу, а не в виде «ничего не работает»
            self.s_main.set_status(cfg["_ошибка"], ok=False)
            log_line(cfg["_ошибка"])
        elif not self.client.enabled:
            if self.client.standalone_ready:
                self.s_main.set_status("Готов к работе (без сервера)", ok=True)
            else:
                self.s_main.set_status("Нет сервера и ключей: заполните kiosk.toml", ok=False)
        self._try_server_config()
        self._убрать_старое()

    # ---------- служебное ----------
    def show_screen(self, w):
        self.stack.setCurrentWidget(w)
        self.host.set_bg(ui.C["ground"] if w is self.s_result else "#FFFFFF")

    def _убрать_старое(self):
        """Старые оценки с диска — при запуске и в фоне: их бывает много, а экран ждать
        не должен. Кончившийся диск на точке останавливает приём совсем."""
        дней = self.cfg.get("keep_days", 90)

        def job():
            убрано = убрать_старое(дней)
            if убрано:
                log_line(f"уборка: удалено {убрано} старше {дней} дней")
            return убрано
        self._run(job)

    def _try_server_config(self):
        def job():
            try:
                c = self.client.config()
                if c.get("точка"):
                    self.s_main.set_point(c["точка"])
                    self.s_scan.set_point(c["точка"])
                self.cfg["return_seconds"] = c.get("возврат_с") or self.cfg["return_seconds"]
                self.cfg["apple_history_seconds"] = c.get("история_apple_с") or self.cfg["apple_history_seconds"]
            except Exception:                                    # noqa: BLE001
                pass
        self._run(job)

    def _run(self, fn):
        t = Task(fn, self)
        self.tasks = [x for x in self.tasks if x.isRunning()] + [t]
        t.start()
        return t

    def _stop_intake(self):
        if self.intake is not None:
            self.intake.stop()
            self.intake.wait(2000)
            self.intake = None
        self.last_intake = None

    def on_intake(self, state):
        """Сервер сообщил состояние заявки (номер после имени и телефона, ссылка на фото/видео)."""
        self.last_intake = state
        if self.state == "result":
            self.s_result.set_intake(state)

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
        if self.intake is not None:
            self.intake.stop()
        for t in (self.poller, self.net, self.pipeline, self.intake, *self.tasks):
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
        self.кабель = state
        if self.state == "idle":
            if state == NO_DRIVER:
                self.s_main.set_status("Нет драйвера Apple — установите iTunes", ok=False)
                self.s_main.set_device("nodriver")
            elif state == READY and count and not self.wait_unplug:
                self.s_main.set_device("found")
                if self.клиент:                        # сперва имя и телефон, потом проверка
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
        elif self.state == "result":
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
            if self.state == "result":
                self.s_result.fill(result["report"], result.get("server"))
                if self.last_intake:                       # не сбрасывать уже выданный номер
                    self.s_result.set_intake(self.last_intake)

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
        rep = result["report"]
        итог = (rep.get("детали_вердикт") or {}).get("итог")
        if итог == "родные" and self.клиент:
            self.state = "eval"                        # аппарат чистый — оформляем сделку
            self.s_eval.показать(rep, (rep.get("цена") or {}).get("цена"))
            self.show_screen(self.s_eval)
            self.новый_код_медиа()
            return
        self.s_result.fill(rep, result.get("server"))
        if self.клиент:
            # ремонт, замена или неподтверждённые детали — сделку не оформляем, но слепок уже
            # сохранён: именно на таких аппаратах учится разбор, и позже мы их добавим
            self.s_result.set_note(
                "Сделка не оформляется: "
                + ("Apple не подтвердила подлинность деталей" if итог in ("кабель", "неполно")
                   else "по данным Apple деталь меняли")
                + ". Слепок сохранён — передайте его разработчику.")
        self.show_screen(self.s_result)
        self.state = "result"
        self.return_timer.start(int(self.cfg.get("return_seconds", 60)) * 3000)
        # номер заявки сервер выдаст, когда сотрудник в кассе запишет имя и телефон клиента — опрашиваем
        self._stop_intake()
        srv = result.get("server") or {}
        if srv.get("id") and not srv.get("локально") and self.client.enabled:
            self.intake = IntakePoller(self.client, srv["id"], self)
            self.intake.state.connect(self.on_intake)
            self.intake.start()

    def on_failed(self, text):
        if self.state != "scanning":
            return
        self.state = "failed"
        self.s_scan.set_step("connect", "fail", "не удалось")
        self.s_scan.set_trouble("Не получилось прочитать телефон: " + text + ". Подключите заново или подойдите к сотруднику.")
        QTimer.singleShot(8000, self.go_home)

    # ---------- сделка ----------
    def начать_сделку(self):
        self.s_client.сбросить()
        self.state = "client"
        self.show_screen(self.s_client)

    def клиент_готов(self, имя, телефон):
        self.клиент = {"имя": имя, "телефон": телефон}
        self.state = "idle"
        self.wait_unplug = False
        self.s_scan.reset()
        self.s_scan.set_trouble("Подключите телефон кабелем и нажмите «Доверять».")
        self.show_screen(self.s_scan)
        if self.кабель == READY:
            self.start_check()

    def отправить_в_оценку(self, поля):
        """Сделку отправляем боту Оценки — создаёт её он. Сеть в отдельном потоке."""
        from pintel_core.external import ocenka, ocenka_tg
        rep = (self.last or {}).get("report") or {}
        пас, cfg = rep.get("паспорт") or {}, self.cfg
        if not (cfg.get("ocenka_bot_token") and cfg.get("ocenka_chat_id")):
            self.s_eval.ошибка.setText("В kiosk.toml не заданы ocenka_bot_token и "
                                       "ocenka_chat_id — отправлять некуда")
            return
        if not self.код_медиа:
            self.s_eval.ошибка.setText("Нет кода для медиа — нажмите «Другой код»")
            return
        клиент, код = dict(self.клиент), self.код_медиа
        self.s_eval.занято("Отправляем…")

        def job():
            данные = {
                "модель": пас.get("модель"), "код_модели": пас.get("код_модели"),
                "память": (rep.get("память") or {}).get("объём_гб"),
                "акб": (rep.get("батарея") or {}).get("здоровье_%"),
                "циклы": (rep.get("батарея") or {}).get("циклы"),
                "цвет": пас.get("цвет"), "sim": поля["sim"],
                "коробка": поля["коробка"], "шнур": поля["шнур"],
                # panic_full у Оценки — «есть ли ошибка Panic full»; это из crash-логов,
                # которых мы пока не читаем. Пустое поле честнее, чем «нет» без проверки.
                "panic_full": None,
                "статус_ремонта": ocenka.статус_ремонта((rep.get("детали_вердикт") or {}).get("итог")),
                "цена": поля["цена"], "комментарий": поля["комментарий"],
                "комментарий_оценщика": ocenka.комментарий_оценщика(
                    rep, откуда=f"Киоск {cfg.get('point') or ''} от {datetime.now():%Y-%m-%d}"),
                "имя_клиента": клиент.get("имя"), "телефон_клиента": клиент.get("телефон"),
                "imei": пас.get("imei"), "imei_все": [пас.get("imei2")],
                "замки": ocenka.замки(rep),
            }
            посылка = ocenka.посылка(данные, код, точка=cfg.get("point") or "")
            return ocenka_tg.отправить(cfg["ocenka_bot_token"], cfg["ocenka_chat_id"], посылка,
                                       валюта=cfg.get("currency", "₸"))

        t = self._run(job)
        t.ok.connect(self.сделка_ушла)
        t.err.connect(self.отправка_не_удалась)

    def новый_код_медиа(self):
        """Новый код обмена и ссылка на бота. Код придумываем на месте: в базу Оценки с
        точки хода нет, строку по этому коду заведёт сам бот, когда сотрудник откроет
        ссылку."""
        from pintel_core.external import ocenka_media
        if not self.cfg.get("ocenka_bot"):
            self.код_медиа = ""
            self.s_eval.показать_код("—", "")
            self.s_eval.медиа.setText("В kiosk.toml не задан ocenka_bot — медиа принять не от кого")
            return
        self.код_медиа = ocenka_media.новый_код()
        self.s_eval.показать_код(self.код_медиа,
                                 ocenka_media.ссылка(self.cfg["ocenka_bot"], self.код_медиа))
        self.s_eval.медиа.setText("Видео обязательно — без него бот не создаст сделку.")

    def отправка_не_удалась(self, текст):
        self.s_eval.занято("")
        self.s_eval.ошибка.setText("Не ушло: " + текст)

    def сделка_ушла(self, итог):
        поля = self.s_eval.данные()
        self.s_eval.занято("")
        self.сделка = {"номер": итог.get("код") or self.код_медиа, "цена": поля.get("цена"),
                       "валюта": self.cfg.get("currency", "₸"),
                       "клиент": self.клиент.get("имя"), "телефон": self.клиент.get("телефон"),
                       "сотрудник": self.cfg.get("staff_name") or "", "точка": self.cfg.get("point") or "",
                       "коробка": поля.get("коробка"), "шнур": поля.get("шнур")}
        self.s_done.показать(итог.get("код") or self.код_медиа,
                             "Оценка ушла в Telegram. Оценщик подтверждает её кнопкой — "
                             "там же появится номер сделки в Оценке.")
        self.state = "done"
        self.show_screen(self.s_done)

    def напечатать_чек(self):
        """Чек A4 клиенту: складываем страницу и открываем — печать из окна просмотра."""
        from pintel_core import receipt
        rep = (self.last or {}).get("report") or {}
        путь = os.path.join(data_dir(), "out", f"чек_{self.сделка.get('номер') or 'без-номера'}.html")
        with open(путь, "w", encoding="utf-8") as f:
            f.write(receipt.html(self.сделка, rep))
        try:
            if hasattr(os, "startfile"):
                os.startfile(путь)                     # Windows: откроется браузер, дальше Ctrl+P
            else:
                import webbrowser
                webbrowser.open("file://" + путь)
        except Exception as e:                         # noqa: BLE001
            log_line(f"чек не открылся: {e}")
        self.s_done.подпись.setText("Чек сохранён: " + путь)

    def go_home(self):
        self.return_timer.stop()
        self._stop_intake()
        if self.pipeline and self.pipeline.isRunning():
            self.pipeline.cancel.set()                 # слушатель истории больше не нужен
        self.state = "idle"
        self.last = None
        self.клиент, self.сделка, self.код_медиа = {}, {}, ""
        self.s_main.set_device("wait")
        self.show_screen(self.s_main)


def light_palette():
    """Киоск всегда светлый, какая бы тема ни стояла в Windows."""
    pal = QPalette()
    for role in (QPalette.Window, QPalette.Base, QPalette.AlternateBase, QPalette.Button, QPalette.ToolTipBase):
        pal.setColor(role, QColor("#FFFFFF"))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.ToolTipText):
        pal.setColor(role, QColor(ui.C["ink"]))
    pal.setColor(QPalette.Highlight, QColor(ui.C["action"]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.PlaceholderText, QColor(ui.C["muted"]))
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
    app.setFont(ui.app_font())
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
