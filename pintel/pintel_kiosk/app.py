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

from pintel_core import phonetest
from pintel_core.devicelink import connect
from pintel_core.devicelink.connect import NO_DEVICE, NO_DRIVER, READY
from pintel_core.external import ocenka

from . import phoneweb

from . import __version__, config, ui, ui_admin, ui_deal, ui_start
from .client import Client, ServerError
from .config import data_dir
from .worker import Pipeline, SealedPipeline, log_line, забрать_логи, убрать_старое


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
    """Фон: пульс на сервер и досылка очереди. Прайс киоску не нужен — цену считает бот."""
    status = Signal(bool, str)

    def __init__(self, client, cfg, parent=None):
        super().__init__(parent)
        self.client, self.cfg = client, cfg
        self._stop = False
        self.device_state = "?"

    def run(self):
        while not self._stop:
            if self.client.enabled:
                try:
                    sent = self.client.flush_queue()
                    self.client.heartbeat({"драйвер": self.device_state != NO_DRIVER, "телефон": self.device_state,
                                           "в_очереди": self.client.queued(), "версия": __version__})
                    # журнал и эталоны — туда же: раньше они лежали только на этой машине
                    строк = self.client.отправить_логи(забрать_логи())
                    эталоны = self.client.отправить_эталоны(
                        os.path.join(data_dir(), "эталоны"),
                        os.path.join(data_dir(), "cache", "эталоны_на_сервер.json"))
                    хвост = "".join([f", дослано {sent}" if sent else "",
                                     f", журнала {строк}" if строк else "",
                                     f", эталонов {эталоны['ушло']}" if эталоны["ушло"] else ""])
                    self.status.emit(True, "сервер на связи" + хвост)
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
    # результат теста с телефона клиента: приходит из потока мини-сервера
    тест_приехал = Signal(dict)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.client = Client(cfg)
        self.state = "idle"
        self.wait_unplug = False
        self.pipeline = None
        self.last = None
        self.tasks = []
        self.setWindowTitle("Pintel Kiosk")
        self.stack = QStackedWidget()
        self.host = ScaledHost(self.stack)
        self.setCentralWidget(self.host)
        точка = cfg.get("point") or ""
        # Три экрана на всю программу: ожидание, анкета (состояние и клиент — до кабеля, как
        # у продавца в боте Оценки) и рабочее окно. Проверка, сделка и медиа живут в одном
        # окне — за ним работает сотрудник, а не клиент.
        self.s_main = ui.MainScreen(точка)
        self.s_start = ui_start.StartScreen(точка)
        self.s_work = ui_deal.WorkScreen(точка)
        # Токен точки вводят здесь, а не в файле настроек: программа — внешняя часть, всё
        # остальное приходит с сервера. Меню администратора скрыто от клиента сочетанием клавиш.
        self.s_token = ui_admin.TokenScreen()
        self.s_admin = ui_admin.AdminScreen()
        for s in (self.s_main, self.s_start, self.s_work, self.s_token, self.s_admin):
            self.stack.addWidget(s)
        self.s_token.принят.connect(self.новый_токен)
        self.s_token.обновить_список.connect(self.спросить_точки)
        self.s_admin.закрыть.connect(self.закрыть_меню)
        self.s_admin.сменить_токен.connect(self.новый_токен)
        self.s_admin.обновить.connect(self._проверить_обновление)
        self.s_main.начать.connect(self.начать_сделку)
        self.s_main.обновить.connect(self.обновиться)
        self.s_start.далее.connect(self.анкета_готова)
        self.s_start.отмена.connect(self.go_home)
        self.анкета, self.статус_сделки, self.переклассификация = {}, None, None
        self.sealed = None
        self.обновление = None
        self.обновление_ставится = False
        self.s_work.отправить.connect(self.отправить_в_оценку)
        self.s_work.заново.connect(self.go_home)
        self.s_work.печать.connect(self.напечатать_чек)
        self.s_work.пропустить_apple.connect(self.on_skip_apple)
        self.s_work.новый_код.connect(self.новый_код_медиа)
        self.s_work.новый_тест.connect(self.новый_код_теста)
        self.s_work.пропустить_тест.connect(self.тест_не_будет)
        self.s_work.перепроверить.connect(self.перепроверить_телефон)
        # Результат теста приходит из потока мини-сервера, а не из потока окна: сигнал
        # переносит его в поток Qt сам, трогать виджеты из чужого потока нельзя.
        self.тест_приехал.connect(self._тест_с_телефона)
        self.код_медиа = ""
        self.код_теста = ""
        self.тест_телефона = {}
        self.тест_через_сервер = False
        self._тест_спрашиваем = False
        self.тест_опрос = QTimer(self)
        self.тест_опрос.timeout.connect(self._спросить_тест)
        # Фото и видео сотрудник шлёт боту, а не нам: в базу Оценки с точки хода нет.
        # Поэтому про них спрашиваем сервер — он стоит рядом с ней и видит их.
        self._медиа_спрашиваем = False
        self.медиа_опрос = QTimer(self)
        self.медиа_опрос.timeout.connect(self._спросить_медиа)
        self.веб_телефона = phoneweb.запустить(int(cfg.get("phone_test_port") or phoneweb.ПОРТ))
        if self.веб_телефона is None:
            log_line(f"тест на телефоне: порт {cfg.get('phone_test_port') or phoneweb.ПОРТ} занят")
        self.сделка, self.кабель = {}, NO_DEVICE
        self._ждём_сделку = False        # посылка у бота, ждём от него номер сделки
        self.return_timer = QTimer(self)
        self.return_timer.setSingleShot(True)
        self.return_timer.timeout.connect(self.go_home)
        self.poller = Poller(self)
        self.poller.tick.connect(self.on_tick)
        self.poller.start()
        self.net = NetThread(self.client, cfg, self)
        self.net.status.connect(self.on_net)
        self.net.start()
        QShortcut(QKeySequence("Escape"), self, activated=self.toggle_fullscreen)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+Shift+A"), self, activated=self.открыть_меню)
        if not self.client.enabled:
            # первый запуск: токена нет, и спрашиваем сразу — без него программа пустая
            self.show_screen(self.s_token)
            self.спросить_точки()
            log_line("токен точки не задан — ждём выбора точки на экране")
        elif not cfg.get("_настройки_с_сервера"):
            self.s_main.set_status("Настройки с сервера ещё не получены", ok=False)
        self._try_server_config()
        self._убрать_старое()
        self._выгрузить_архив()
        self._проверить_обновление()

    # ---------- служебное ----------
    def show_screen(self, w):
        self.stack.setCurrentWidget(w)
        self.host.set_bg(ui.C["ground"] if w in (self.s_work, self.s_start) else "#FFFFFF")

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

    def _выгрузить_архив(self):
        """Слепки — в закрытый чат Telegram: объезжать точки и собирать папки руками никто
        не станет. Уходят эталоны (обезличенные), полные слепки — только если включили."""
        from pintel_core.external import tg_upload
        cfg = self.cfg
        токен, чат = cfg.get("ocenka_bot_token"), cfg.get("archive_chat_id")
        if not (токен and чат):
            return
        точка = cfg.get("point") or ""

        def job():
            итог = tg_upload.догнать(токен, чат, os.path.join(data_dir(), "эталоны"),
                                     os.path.join(data_dir(), "cache", "архив_эталоны.json"),
                                     "эталон_*.zip", подпись=точка)
            if cfg.get("archive_snapshots"):
                полные = tg_upload.догнать(токен, чат, os.path.join(data_dir(), "out"),
                                           os.path.join(data_dir(), "cache", "архив_слепки.json"),
                                           os.path.join("*", "snapshot.json"), подпись=точка)
                итог["ушло"] += полные["ушло"]
                итог["ошибка"] = итог["ошибка"] or полные["ошибка"]
            if итог["ушло"] or итог["ошибка"]:
                log_line(f"архив: ушло {итог['ушло']}, осталось {итог['осталось']}"
                         + (f", {итог['ошибка']}" if итог["ошибка"] else ""))
            return итог
        self._run(job)

    def _проверить_обновление(self):
        """Есть ли свежая сборка. Проверяем один раз, при запуске — посреди сделки ничего
        подменять нельзя."""
        from . import updater
        cfg = self.cfg
        if not cfg.get("update_repo"):
            return
        self._run(lambda: updater.проверить(cfg["update_repo"], cfg["update_token"],
                                            cfg.get("update_asset") or ""),
                  ok=self._обновление_найдено)

    def _обновление_найдено(self, итог):
        """Нашлась новая сборка — ставим сразу, не спрашивая.

        Оценщику некогда следить за версиями, а работать на точке на старой сборке нельзя:
        именно из-за этого исправленная ошибка неделями жила на части точек. Проверка идёт
        при запуске, когда ни одна сделка не открыта, так что прервать нечего."""
        self.обновление = итог if (итог or {}).get("есть") else None
        if self.обновление:
            log_line("обновление: доступно " + str(итог.get("тег")) + " — ставим сразу")
            self.обновление_ставится = True
            self.s_main.set_status(f"Обновление {итог.get('тег')} — программа перезапустится",
                                   ok=True)
            self.обновиться()
        elif (итог or {}).get("почему"):
            log_line("обновление: " + str(итог["почему"]))

    def обновиться(self):
        """Скачать и подменить папку. Программа после этого закрывается — её запустит
        обратно сам сценарий подмены."""
        from . import updater
        if not self.обновление or self.state != "idle":
            return
        тег, cfg = self.обновление["тег"], self.cfg
        self.s_main.показать_обновление("Скачиваем…", занято=True)

        def job():
            архив = os.path.join(data_dir(), "update", f"{тег}.zip")
            updater.скачать(self.обновление["url"], cfg["update_token"], архив)
            новая = updater.распаковать(архив, os.path.join(data_dir(), "update", тег))
            установлена = config.app_dir()
            updater.перенести_своё(установлена, новая)   # kiosk.toml не теряем
            exe = sys.executable if getattr(sys, "frozen", False) else os.path.join(
                установлена, "pintel-kiosk.exe")
            return updater.применить(новая, установлена, exe, os.path.join(data_dir(), "update"))

        self._run(job, ok=self._обновление_готово, err=self._обновление_сорвалось)

    def _обновление_готово(self, путь):
        log_line("обновление: запущен сценарий подмены " + str(путь))
        self.s_main.показать_обновление("Перезапуск…", занято=True)
        QTimer.singleShot(1200, self.close)        # дать сценарию стартовать

    def _обновление_сорвалось(self, текст):
        """Сорвалось — работаем на текущей версии.

        Запирать точку нельзя: пропал интернет или прилёг GitHub — выкуп на всех точках
        встанет, а это дороже старой сборки. Кнопка остаётся: повторить можно руками."""
        self.обновление_ставится = False
        log_line("обновление не удалось: " + текст)
        self.s_main.показать_обновление("Обновить программу — не вышло, повторить")
        self.s_main.b_обновить.setEnabled(True)
        self.s_main.set_status("Обновиться не вышло — работаем на этой версии", ok=False)

    def _try_server_config(self):
        """Спросить сервер про точку и сроки. Заодно это первый выход на связь: если токена
        ещё нет, киоск здесь же привяжется сам.

        Виджеты трогаем только в слоте: раньше настройки сервера раскладывались прямо в
        рабочем потоке, а Qt этого не прощает. Пока сервер не был настроен ни на одной
        точке, ветка не выполнялась вовсе — теперь она выполняется при каждом запуске."""
        self._run(self.client.config, ok=self._настройки_сервера,
                  err=lambda e: log_line(f"сервер не ответил на запрос настроек: {e}"))

    def _настройки_сервера(self, c):
        """Сервер прислал настройки: кладём их в копию и раскладываем по экранам.

        Надпись в углу берётся отсюда же, из имени точки в базе: раньше её писали в файле
        на каждой машине, и совпадала она с базой только на честном слове."""
        c = c or {}
        новые = config.сохранить_настройки(c.get("настройки") or {})
        if c.get("точка_id"):
            # сервер говорит, какой точке принадлежит токен: это и есть id магазина в Оценке
            self.cfg["point_id"] = c["точка_id"]
            config.запомнить_токен(self.client.token, c["точка_id"])
        # Пустое значение с сервера — это «ещё не заполнили», а не «сотри то, что есть».
        # Иначе первая же точка, обновившись раньше, чем настройки завели в базе, осталась
        # бы без бота Оценки и не смогла отправить сделку.
        self.cfg.update({k: v for k, v in новые.items() if v not in ("", None)})
        точка = новые.get("point") or c.get("точка") or ""
        for экран in (self.s_main, self.s_start, self.s_work):
            экран.set_point(точка)
        self.s_main.set_status(f"Готов к работе · {точка}" if точка else "Готов к работе", ok=True)
        if self.stack.currentWidget() is self.s_token:
            self.show_screen(self.s_main)

    # ---------- токен точки и меню администратора ----------
    def спросить_точки(self):
        """Список точек для первого экрана. Точка — это магазин Оценки, список приходит с
        сервера с теми же id, поэтому сотрудник выбирает знакомое название."""
        self._run(self.client.точки, ok=self.s_token.показать_точки,
                  err=lambda e: (self.s_token.показать_точки([]), log_line(f"точки не пришли: {e}")))

    def новый_токен(self, point_id, токен=None):
        """Точку выбрали, токен ввели. Проверяем сразу: сказать «не подошёл» надо здесь, а
        не молчанием на первом же аппарате.

        Из меню администратора приходит только токен — точку там не меняют, она определяется
        самим токеном."""
        if токен is None:
            point_id, токен = self.cfg.get("point_id"), point_id
        токен = str(токен or "").strip()
        if not токен:
            return
        config.запомнить_токен(токен, point_id)
        self.client.сменить_токен(токен)
        self.cfg["token"], self.cfg["point_id"] = токен, point_id
        self._run(self.client.config, ok=self._токен_подошёл, err=self._токен_не_подошёл)

    def _токен_подошёл(self, c):
        log_line(f"токен принят, точка «{(c or {}).get('точка') or '—'}»")
        self._настройки_сервера(c)
        if self.stack.currentWidget() is self.s_admin:
            self.s_admin.ответ.setText("Токен принят: " + ((c or {}).get("точка") or "точка без имени"))
            self.s_admin.показать(self._сведения())

    def _токен_не_подошёл(self, текст):
        log_line(f"токен не подошёл: {текст}")
        if self.stack.currentWidget() is self.s_admin:
            self.s_admin.ответ.setText("Не подошёл: " + str(текст))
        else:
            self.s_token.сказать("Не подошёл: " + str(текст))

    def _сведения(self) -> dict:
        return {"Сервер": self.client.base or "—",
                "Точка": f"{self.cfg.get('point') or 'сервер ещё не ответил'}"
                         + (f" (id {self.cfg['point_id']})" if self.cfg.get("point_id") else ""),
                "Этот компьютер": self.client.машина(),
                "Токен": (self.client.token[:6] + "…") if self.client.token else "не задан",
                "Версия": __version__,
                "Оценок в очереди": self.client.queued(),
                "Бот Оценки": self.cfg.get("ocenka_bot") or "не задан"}

    def открыть_меню(self):
        if self.stack.currentWidget() is self.s_token:
            return                                   # сначала токен, меню потом
        self.s_admin.показать(self._сведения())
        self._экран_до_меню = self.stack.currentWidget()
        self.show_screen(self.s_admin)

    def закрыть_меню(self):
        назад = getattr(self, "_экран_до_меню", None) or self.s_main
        self.show_screen(назад if назад is not self.s_admin else self.s_main)

    def _run(self, fn, ok=None, err=None):
        """Сетевое действие в отдельном потоке.

        `ok` и `err` подключаются ДО запуска: быстрая задача успевает закончиться раньше,
        чем вызывающий успеет подписаться, и тогда результат теряется вовсе. На опросе
        теста это ловится сразу, на медленной отправке сделки — раз в сто прогонов."""
        t = Task(fn, self)
        if ok is not None:
            t.ok.connect(ok)
        if err is not None:
            t.err.connect(err)
        self.tasks = [x for x in self.tasks if x.isRunning()] + [t]
        t.start()
        return t

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
            self.pipeline.остановить_слушателя()
        for t in (self.poller, self.net, self.pipeline, self.sealed, *self.tasks):
            if t is not None and t.isRunning():
                t.wait(3000)                     # иначе Qt ругается «Destroyed while thread is still running»
        super().closeEvent(e)

    # ---------- события ----------
    def on_net(self, ok, text):
        if self.state == "idle" and self.client.enabled:
            self.s_main.set_status("Готов к работе" if ok else f"Автономно: {text}", ok=ok)

    def on_tick(self, state, detail, count):
        self.net.device_state = state
        self.кабель = state
        if self.state == "idle":
            if state == NO_DRIVER:
                self.s_main.set_status("Служба Apple не отвечает — перезапустите "
                                       "Apple Mobile Device Service", ok=False)
                self.s_main.set_device("nodriver")
            elif state == READY and count:
                self.s_main.set_device("found")
            elif state == NO_DEVICE:
                self.wait_unplug = False
                self.s_main.set_device("wait")
                if self.client.enabled and self.client.online:
                    self.s_main.set_status("Готов к работе", ok=True)
        elif self.state == "intake":
            # анкета ещё не заполнена: кабель подключили — ждём, читать телефон рано
            if state == NO_DEVICE:
                self.wait_unplug = False
        elif self.state == "work":
            # окно уже открыто: телефон подключили — начинаем читать, отключили — ждём следующий.
            # Запечатанный кабелем не читается вовсе.
            if state == NO_DEVICE:
                self.wait_unplug = False
            elif (state == READY and count and not self.wait_unplug and not self.last
                  and self.анкета.get("состояние") != "новый"):
                self.start_check()
        elif self.state == "scanning":
            if state == NO_DEVICE and self.pipeline:
                self.pipeline.cancel.set()
                self.pipeline.остановить_слушателя()   # телефона нет — ломиться к нему незачем
                self.s_work.set_trouble("Телефон отключили. Подключите снова — проверка начнётся заново.")
                self.state = "work"

    def start_check(self, заново=False):
        if self.pipeline and self.pipeline.isRunning():
            self.pipeline.cancel.set()
            self.pipeline.остановить_слушателя()       # канал к телефону освобождаем сразу
            self.pipeline.wait(3000)
        self.state = "scanning"
        self.wait_unplug = True
        self.s_work.set_trouble("Не отключайте кабель. Обычно это занимает около минуты."
                                if заново else
                                "Не отключайте кабель. Смотрим, не проверяли ли этот телефон "
                                "только что.")
        self.pipeline = Pipeline(self.cfg, self.client, self, заново=заново)
        self.pipeline.status.connect(self.on_link_status)
        self.pipeline.step.connect(self.s_work.set_step)
        self.pipeline.apple_prompt.connect(self.s_work.show_prompt)
        self.pipeline.прошлая.connect(self.прошлая_проверка)
        self.pipeline.done.connect(self.on_done)
        self.pipeline.history.connect(self.on_history)
        self.pipeline.failed.connect(self.on_failed)
        self.pipeline.start()

    def on_history(self, result):
        """История Apple пришла после результата — обновляем то, что уже на экране. Вердикт
        мог измениться, значит и состояние сделки пересчитываем."""
        if self.last and result.get("client_id") == self.last.get("client_id"):
            self.last = result
            if self.state == "work":
                self.s_work.показать(result["report"])
                self._классифицировать(result["report"])

    def прошлая_проверка(self, отметка):
        """Проверку взяли готовой: телефон кабелем не перечитывали.

        Писать об этом в журнал обязательно: по нему потом разбирают, почему у сделки
        отчёт получасовой давности, и была ли сверка с живым телефоном."""
        log_line("прошлая проверка: " + str(отметка.get("словами") or "")
                 + "; сверка: " + str(отметка.get("сверка") or "—"))
        self.s_work.set_trouble("Эту модель проверяли " + str(отметка.get("словами") or "недавно")
                                + " — взяли готовую проверку. Нужно перечитать — кнопка слева.")

    def перепроверить_телефон(self):
        """«Проверить телефон заново»: прошлой проверке не верим, читаем аппарат с нуля."""
        if self.state not in ("work", "scanning") or self.анкета.get("состояние") == "новый":
            return
        if self.кабель != READY:
            self.s_work.сказать("Телефона нет на кабеле — перечитывать нечего. Подключите его.")
            return
        log_line("сотрудник просит перечитать телефон заново")
        self.last = None
        self.s_work.снова_проверка()
        self.start_check(заново=True)

    def on_link_status(self, state, human):
        if state != READY:
            self.s_work.set_step("connect", "run", human)
            self.s_work.set_trouble(human)
        else:
            self.s_work.set_trouble("Не отключайте кабель. Обычно это занимает около минуты.")

    def on_skip_apple(self):
        if self.pipeline:
            self.pipeline.skip_apple.set()

    def on_done(self, result):
        if self.state != "scanning":
            return
        self.last = result
        rep = result["report"]
        self.state = "work"
        self.s_work.показать(rep)
        self._выгрузить_архив()                    # свежий эталон уедет в архив сам
        # Сделка оформляется при любом вердикте: замена или дефект не отказ, а другое
        # состояние — как у продавца в боте. Что нашёл кабель, видно на плашке и уйдёт
        # админу на ручную оценку вместо автоцены.
        self._классифицировать(rep)
        self.новый_код_медиа()

    def _классифицировать(self, rep):
        """Выбор сотрудника до диагностики + отчёт → состояние сделки (phone_status Оценки)."""
        состояние = self.анкета.get("состояние") or "норма"
        статус, почему = ocenka.переклассифицировать(состояние, rep)
        self.статус_сделки, self.переклассификация = статус, почему
        кнопка = ocenka.состояние_словами(состояние)
        if почему:
            итог = {ocenka.СТАТУС_РЕМОНТ: "ремонт", ocenka.СТАТУС_ДЕФЕКТ: "дефект"}.get(статус)
            кнопка = ocenka.состояние_словами(итог) if итог else кнопка
            log_line(f"состояние: {состояние} → {статус}: {почему}")
        self.s_work.set_состояние(кнопка, почему or "")

    def on_failed(self, text):
        if self.state != "scanning":
            return
        self.state = "work"
        self.s_work.set_step("connect", "fail", "не удалось")
        self.s_work.set_trouble("Не получилось прочитать телефон: " + text
                                + ". Отключите и подключите кабель заново.")

    # ---------- сделка ----------
    def начать_сделку(self):
        """Сделка начинается с анкеты — состояние и клиент до кабеля, как у продавца в боте
        Оценки. Телефон, подключённый раньше времени, ждёт."""
        if self.обновление_ставится:            # на старой сборке сделку не начинаем
            self.s_main.set_status("Идёт обновление — подождите, программа перезапустится",
                                   ok=False)
            return
        self.last = None
        self.сделка, self.анкета = {}, {}
        self._ждём_сделку = False
        self.статус_сделки = self.переклассификация = None
        self.новый_код_теста()                  # свой одноразовый код теста на каждую сделку
        self.s_start.начать()
        self.s_work.начать()
        self.state = "intake"
        self.show_screen(self.s_start)

    def анкета_готова(self, данные):
        """Состояние выбрано, клиент записан. Запечатанный — по IMEI с коробки, без кабеля;
        остальные — читаем телефон, имя уже стоит в окне сделки."""
        self.анкета = dict(данные or {})
        self.s_work.set_клиент(self.анкета.get("имя"), self.анкета.get("телефон"))
        self.s_work.set_состояние(ocenka.состояние_словами(self.анкета.get("состояние")))
        self.show_screen(self.s_work)
        if self.анкета.get("состояние") == "новый":
            self.s_work.режим(True, self.анкета.get("imei") or [])
            self.state = "work"
            self.start_sealed(self.анкета.get("imei") or [])
            return
        self.s_work.режим(False)
        self.state = "work"
        if self.кабель == READY and not self.wait_unplug:
            self.start_check()

    def start_sealed(self, имеи):
        """Запечатанный: Sickw (служба для запечатанных) и реестр РФС по IMEI с коробки."""
        if self.sealed and self.sealed.isRunning():
            self.sealed.wait(3000)
        self.last = None
        self.sealed = SealedPipeline(self.cfg, self.client, имеи, self)
        self.sealed.step.connect(self.s_work.set_step)
        self.sealed.done.connect(self.on_sealed_done)
        self.sealed.failed.connect(self.on_sealed_failed)
        self.sealed.start()

    def on_sealed_done(self, result):
        if self.state != "work" or self.анкета.get("состояние") != "новый":
            return
        self.last = result
        rep = result["report"]
        self.s_work.показать(rep)
        self.s_work.аппарат.setText("Запечатанный · " + self.s_work.аппарат.text())
        self._классифицировать(rep)
        self.новый_код_медиа()
        if not (rep.get("память") or {}).get("объём_гб") or not (rep.get("паспорт") or {}).get("модель"):
            self.s_work.сказать("База IMEI не назвала модель или объём — без них сделку не "
                                       "собрать. Проверьте IMEI и службу sickw_services_sealed.")

    def on_sealed_failed(self, text):
        if self.state != "work":
            return
        self.s_work.set_step("passport", "fail", "не удалось")
        self.s_work.set_trouble("Не получилось проверить по базе: " + text)

    def отправить_в_оценку(self, поля):
        """Сделку отправляем боту Оценки — создаёт её он. Сеть в отдельном потоке."""
        from pintel_core.external import ocenka_tg
        rep = (self.last or {}).get("report") or {}
        пас, cfg = rep.get("паспорт") or {}, self.cfg
        if not (cfg.get("ocenka_bot_token") and cfg.get("ocenka_chat_id")):
            self.s_work.сказать("В настройках точки не заданы ocenka_bot_token и "
                                       "ocenka_chat_id — отправлять некуда")
            return
        if not self.код_медиа:
            self.s_work.сказать("Нет кода для медиа — нажмите «Другой код»")
            return
        клиент, код = {"имя": поля["имя"], "телефон": поля["телефон"]}, self.код_медиа
        магазин = self.cfg.get("point_id")        # он же id магазина в Оценке
        тест = поля.get("тест") or self.тест_телефона
        тест_пропущен = поля.get("тест_пропущен") or ""
        ручная = поля.get("ручная") or {}
        тест_строкой = (f"Тест на телефоне пропущен: {тест_пропущен}" if тест_пропущен
                        else phonetest.словами(тест))
        состояние = self.анкета.get("состояние") or "норма"
        if self.статус_сделки is None:
            self._классифицировать(rep)
        статус, почему = self.статус_сделки, self.переклассификация
        откуда = f"Киоск {cfg.get('point') or ''} от {datetime.now():%Y-%m-%d}"
        self.s_work.занято("Отправляем…")

        def job():
            if состояние == "новый":
                данные = ocenka.данные_запечатанного(
                    rep.get("sickw") or {}, [пас.get("imei"), пас.get("imei2")], клиент,
                    sim=поля["sim"], коробка=поля["коробка"], шнур=поля["шнур"],
                    комментарий=поля["комментарий"], откуда=откуда, рфс=rep.get("рфс"),
                    отчёт=rep)
                данные["shop_id"] = магазин
            else:
                данные = {
                    "модель": пас.get("модель"), "код_модели": пас.get("код_модели"),
                    "память": (rep.get("память") or {}).get("объём_гб"),
                    "акб": (rep.get("батарея") or {}).get("здоровье_%"),
                    "циклы": (rep.get("батарея") or {}).get("циклы"),
                    "цвет": пас.get("цвет"), "sim": поля["sim"],
                    "коробка": поля["коробка"], "шнур": поля["шнур"],
                    # «Есть ли ошибка Panic full?» — тот же вопрос, что бот задаёт продавцу.
                    # Читаем сами из crash-логов; не прочитали — отдаём пусто, а не «нет».
                    "panic_full": (rep.get("паника") or {}).get("panic_full"),
                    # состояние — кнопка Оценки, выбранная до диагностики, с поправкой кабеля
                    "статус_ремонта": статус, "состояние": состояние, "переклассификация": почему,
                    "комментарий": поля["комментарий"],
                    "комментарий_оценщика": ocenka.комментарий_оценщика(
                        rep, откуда=откуда, состояние=ocenka.состояние_словами(состояние),
                        почему=почему or "", тест=тест_строкой),
                    "имя_клиента": клиент.get("имя"), "телефон_клиента": клиент.get("телефон"),
                    "imei": пас.get("imei"), "imei_все": [пас.get("imei2")],
                    "замки": ocenka.замки(rep), "рфс": rep.get("рфс"),
                    # что закрыть нечем — по этому списку бот не даёт автоцену; сверку
                    # деталей глазами закрывает пункт ручной диагностики в боте
                    "не_прочиталось": ocenka.незакрытое(rep),
                    "сверка_нужна": ocenka.сверка_нужна(rep),
                    "shop_id": магазин,
                }
            # тест на телефоне клиента: отметки едут в сделку как есть, их читает бот
            данные["тест_телефона"] = dict(тест)
            данные["тест_пропущен"] = тест_пропущен
            # ручные проверки сотрудника — оттуда же, с экрана кассы. Бот больше не
            # спрашивает их кнопками: он кладёт в карточку то, что отмечено здесь.
            данные["ручная_диагностика"] = dict(ручная)
            посылка = ocenka.посылка(данные, код, точка=cfg.get("point") or "")
            # Главный путь — через наш сервер: он кладёт посылку в таблицу обмена, бот
            # забирает её оттуда сам и сразу создаёт сделку. Подтверждать нечего, и чат
            # Telegram ни при чём — а он отказывал по-разному («bot was blocked by the
            # user», «chat not found»), и тогда сделку нельзя было создать вовсе.
            ответ = (self.client.отправить_посылку(код, посылка) if self.client.enabled
                     else {"принято": False, "почему": "касса не связана с сервером"})
            if ответ.get("принято"):
                return {"код": код, "через": "сервер", "сделка": ответ.get("сделка")}
            # Запасной путь — карточка с кнопкой в чат, как раньше. Им живут точки без
            # связи с сервером; подтверждает её оценщик нажатием.
            # имя своё: `почему` выше занято причиной переклассификации сделки
            отказ = str(ответ.get("почему") or "сервер не принял посылку")
            try:
                итог = ocenka_tg.отправить(cfg["ocenka_bot_token"], cfg["ocenka_chat_id"],
                                           посылка)
            except ocenka_tg.ОшибкаОтправки as exc:
                raise ocenka_tg.ОшибкаОтправки(
                    f"через сервер — {отказ}; через бота — {exc}") from None
            итог["через"] = "бота"
            return итог

        self._run(job, ok=self.сделка_ушла, err=self.отправка_не_удалась)

    def новый_код_медиа(self):
        """Новый код обмена и ссылка на бота. Код придумываем на месте: в базу Оценки с
        точки хода нет, строку по этому коду заведёт сам бот, когда сотрудник откроет
        ссылку."""
        from pintel_core.external import ocenka_media
        if not self.cfg.get("ocenka_bot"):
            self.код_медиа = ""
            self.s_work.показать_код("—", "")
            self.s_work.медиа.setText("В kiosk.toml не задан ocenka_bot — медиа принять не от кого")
            return
        self.код_медиа = ocenka_media.новый_код()
        self.s_work.показать_код(self.код_медиа,
                                 ocenka_media.ссылка(self.cfg["ocenka_bot"], self.код_медиа))
        # подсказку не переписываем: она стоит в самой карточке и выверена по месту
        self.s_work.медиа.setText(ui_deal.ПОДСКАЗКА_МЕДИА)
        self._медиа_спрашиваем = False
        if self.client.enabled:
            self.s_work.set_медиа({})           # ждём первого ответа сервера
            self.медиа_опрос.start(3000)        # что дошло до бота, видно на экране кассы
        else:
            # Без связи с сервером спросить некого. Держать из-за этого сделку нельзя:
            # касса должна работать и в одиночку, а бот всё равно не создаст её без видео.
            self.s_work.set_медиа({"известно": False, "почему": "касса не связана с сервером"})

    def _сделка_в_оценке(self, состояние):
        """Посылка у бота — ждём от него номер сделки или причину, почему её нет.

        Ответ «не знаю» (сервер не видит базу Оценки) не значит ничего: ждём дальше,
        сделка от этого не пропадает."""
        if состояние.get("сделка"):
            self._ждём_сделку = False
            self.медиа_опрос.stop()
            self.s_work.сделка_создана(состояние["сделка"])
            log_line(f"оценка {self.код_медиа}: сделка № {состояние['сделка']} создана")
            return
        if состояние.get("ошибка"):
            self._ждём_сделку = False
            self.медиа_опрос.stop()
            self.s_work.сделка_не_вышла(состояние["ошибка"])
            log_line(f"оценка {self.код_медиа}: сделка не создалась — {состояние['ошибка']}")

    def _спросить_медиа(self):
        """Пока сотрудник шлёт боту фото и видео, касса спрашивает сервер, что уже дошло.

        Иначе «Отправить в Оценку» нажималась бы вслепую: бот без видео сделку не создаёт,
        и отказ приходил бы, когда телефон клиента уже отдан. Запрос сетевой — в отдельном
        потоке и не больше одного зараз."""
        if not (self.client.enabled and self.код_медиа) or self._медиа_спрашиваем:
            return
        if self.state not in ("work", "intake", "scanning"):
            self.медиа_опрос.stop()
            return
        if self.s_work.отправлено and not self._ждём_сделку:
            self.медиа_опрос.stop()
            return
        self._медиа_спрашиваем = True
        код = self.код_медиа
        self._run(lambda: self.client.медиа(код), ok=self._медиа_спросили,
                  err=lambda e: self._медиа_спросили({"известно": False, "почему": str(e)[:80]}))

    def _медиа_спросили(self, состояние):
        self._медиа_спрашиваем = False
        if self._ждём_сделку:
            self._сделка_в_оценке(состояние or {})
            return
        self.s_work.set_медиа(состояние)
        # Сервер не видит базу Оценки — спрашивать каждые три секунды незачем: ответ не
        # изменится от того, что мы повторим его двадцать раз в минуту.
        self.медиа_опрос.setInterval(3000 if (состояние or {}).get("известно") else 15000)
        if (состояние or {}).get("готово"):
            self.медиа_опрос.stop()
            log_line(f"медиа по коду {self.код_медиа}: фото и видео собраны, диагностика пройдена")

    def _дослать_на_сервер(self, добавка: dict):
        """Дописать в сохранённую на сервере оценку то, что появилось ПОСЛЕ её создания:
        результат теста на телефоне и чек.

        Оценка уходит на сервер сразу после кабеля, а тест и чек случаются позже. Без этого
        в общей базе остался бы обрезанный аппарат: проверка есть, а чем кончилось — нет.
        Сервера нет — всё то же лежит в out/ на точке и уходит в Оценку карточкой."""
        import json as _json
        from pintel_core.devicelink import snapshot as _snap
        сервер = (self.last or {}).get("server") or {}
        ev_id = сервер.get("id")
        if not (self.client.enabled and ev_id) or сервер.get("локально"):
            return
        rep = dict((self.last or {}).get("report") or {})
        rep.update(добавка)
        self.last["report"] = rep
        тело = _json.loads(_snap.dumps(rep))
        self._run(lambda: self.client.update_evaluation(ev_id, тело),
                  err=lambda e: log_line(f"оценка на сервере не обновилась: {e}"))

    # ---------- тест на телефоне клиента ----------
    def новый_код_теста(self):
        """Новый одноразовый код и QR на страницу теста. Код свой на каждую сделку: другое
        устройство не подбросит результат в чужую сделку.

        Сначала пробуем наш домен: там HTTPS, а значит телефон пускает страницу к микрофону
        (по локальной сети Safari этого не разрешает) и работает он с любой сети, хоть с
        мобильного интернета. Сервер не настроен или не ответил — остаётся мини-сервер в
        самом киоске: шаг обязательный, он не может зависеть от чужой доступности.
        """
        from pintel_core.external import ocenka_media
        self.тест_телефона = {}
        self.тест_через_сервер = False
        self.тест_опрос.stop()
        self.код_теста = ocenka_media.новый_код(16)      # длиннее: этот код живёт в интернете
        phoneweb.открыть(self.код_теста, self._тест_из_сети)
        порт = int(self.cfg.get("phone_test_port") or phoneweb.ПОРТ)
        ссылка = phoneweb.ссылка(self.код_теста, порт) if self.веб_телефона else ""
        почему = ("" if self.веб_телефона
                  else f"Порт {порт} занят другой программой — тест на телефоне не открыть.")
        self.s_work.set_тест({})
        self.s_work.показать_тест(ссылка, почему)
        log_line(f"тест на телефоне: код {self.код_теста}, локальная сеть, ссылка {ссылка or 'нет'}")
        # Домен спрашиваем в отдельном потоке и показываем QR сразу: сделка начинается с
        # нажатия, и держать окно на время запроса к серверу нельзя. Ответит — заменим QR на
        # адрес домена, там HTTPS и микрофон. Оба адреса ведут на один и тот же код, так что
        # уже открытая страница не ломается.
        if self.client.enabled:
            токен = self.код_теста
            self._run(lambda: self.client.открыть_тест(токен),
                      ok=lambda ссылка_домена: self._тест_на_домене(токен, ссылка_домена),
                      err=lambda e: log_line(f"тест на телефоне: домен не ответил ({e}) — "
                                             "работаем по локальной сети"))

    def _тест_на_домене(self, токен, ссылка):
        """Сервер завёл сессию теста: показываем его адрес и начинаем спрашивать результат."""
        if not ссылка or токен != self.код_теста or self.s_work._тест_закрыт():
            return
        self.тест_через_сервер = True
        self.s_work.показать_тест(ссылка)
        self.тест_опрос.start(3000)
        log_line(f"тест на телефоне: домен, ссылка {ссылка}")

    def _спросить_тест(self):
        """Пока клиент проходит тест на домене, касса спрашивает сервер: не готов ли.

        По локальной сети результат приходит к нам сам, а через домен он ложится в базу —
        узнать о нём можно только спросив. Запрос сетевой, поэтому в отдельном потоке и не
        больше одного зараз."""
        if not (self.тест_через_сервер and self.код_теста) or self._тест_спрашиваем:
            return
        if self.s_work._тест_закрыт() or self.state not in ("work", "intake", "scanning"):
            self.тест_опрос.stop()
            return
        self._тест_спрашиваем = True
        токен = self.код_теста
        self._run(lambda: self.client.результат_теста(токен), ok=self._тест_спросили,
                  err=lambda _: setattr(self, "_тест_спрашиваем", False))

    def _тест_спросили(self, res):
        self._тест_спрашиваем = False
        if res:
            self.тест_опрос.stop()
            self._тест_с_телефона(res)

    def _тест_из_сети(self, данные):
        """Вызывается в потоке мини-сервера. Только переносим в поток окна."""
        self.тест_приехал.emit(dict(данные or {}))

    def _тест_с_телефона(self, данные):
        res = phonetest.разобрать(данные)
        if not phonetest.был(res):
            log_line("тест на телефоне: пришло пусто")
            return
        self.тест_телефона = res
        self.тест_опрос.stop()
        self.s_work.set_тест(res)
        # результат — часть оценки, а не только экрана: дописываем его в то, что хранится
        self._дослать_на_сервер({"тест_телефона": res})
        плох = [имя for _, имя in phonetest.плохие(res)]
        log_line("тест на телефоне: " + phonetest.словами(res))
        if плох:
            # найденное руками кабель не видит, и состояние сделки обязано это учесть
            self.s_work.сказать("Тест на телефоне не прошёл: " + ", ".join(плох)
                                       + ". Сделка уйдёт на оценку человеку.")

    def тест_не_будет(self):
        """Телефона нет в нашей сети (или тест не открывается). Пропуск возможен, но он
        записан и стоит автоцены: сделку будет оценивать человек."""
        кто = self.cfg.get("staff_name") or self.cfg.get("point") or "сотрудник"
        self.s_work.set_тест({}, пропущен=f"телефон не в сети кассы, проверил {кто}")
        self.s_work.правая.setCurrentIndex(ui_deal.СТР_РУЧНАЯ)
        log_line("тест на телефоне пропущен сотрудником")

    def отправка_не_удалась(self, текст):
        self.s_work.занято("")
        self.s_work.сказать("Не ушло: " + текст)

    def _чек_данные(self, номер: str = "") -> dict:
        """Что печатается в чеке клиенту — из того, что уже есть на экране.

        Собрано отдельным методом, потому что чек нужен ДО отправки в Оценку: клиент стоит
        у кассы и уходит с бумагой, а ждать создания сделки ради номера незачем — номер в
        чеке и так наш, это код обмена с того же экрана, по которому бот создаст сделку.
        """
        поля = self.s_work.данные()
        сервер = (self.last or {}).get("server") or {}
        return {"номер": номер or self.код_медиа,
                "клиент": поля.get("имя"), "телефон": поля.get("телефон"),
                "сотрудник": self.cfg.get("staff_name") or "", "точка": self.cfg.get("point") or "",
                "коробка": поля.get("коробка"), "шнур": поля.get("шнур"),
                "комментарий": поля.get("комментарий"), "фирма": self._фирма(),
                "состояние": ocenka.состояние_словами(self.анкета.get("состояние")),
                "статус": self.статус_сделки,
                # чек живёт и на домене: QR на бумаге ведёт на ту же страницу
                "ссылка": сервер.get("ссылка_чека") or ""}

    def сделка_ушла(self, итог):
        self.s_work.занято("")
        код = итог.get("код") or self.код_медиа
        self.сделка = self._чек_данные(код)
        self._дослать_на_сервер({"чек": dict(self.сделка)})
        if итог.get("через") == "сервер":
            # Сделку создаёт бот — через секунду-другую. Ждём её номер и показываем его
            # здесь же: иначе сотрудник не знает, дошло ли вообще.
            self._ждём_сделку = True
            self.s_work.ушло(код, "Сделка создаётся. Номер появится здесь.")
            self.медиа_опрос.start(2000)
        else:
            self._ждём_сделку = False
            self.медиа_опрос.stop()             # карточка ушла, дальше её подтверждают
            self.s_work.ушло(код, "Оценщик подтверждает сделку в Telegram — "
                                  "там появится её номер.")

    def _фирма(self):
        """Реквизиты для шапки чека — из настроек точки."""
        c = self.cfg
        return {"название": c.get("company_name"), "адрес": c.get("company_address"),
                "телефон": c.get("company_phone"), "сайт": c.get("company_site"),
                "бин": c.get("company_bin")}

    def напечатать_чек(self):
        """Чек A4 клиенту: складываем страницу и открываем — печать из окна просмотра.

        Печатать можно, как только фото и видео дошли до бота, — не дожидаясь отправки в
        Оценку: клиенту нужна бумага, а не наш порядок шагов. Если сделка ещё не ушла, тот
        же чек дописывается в оценку на сервере, чтобы он не остался только на бумаге."""
        from pintel_core import receipt
        rep = (self.last or {}).get("report") or {}
        сделка = self.сделка or self._чек_данные()
        путь = os.path.join(data_dir(), "out", f"чек_{сделка.get('номер') or 'без-номера'}.html")
        with open(путь, "w", encoding="utf-8") as f:
            f.write(receipt.html(сделка, rep))
        try:
            if hasattr(os, "startfile"):
                os.startfile(путь)                     # Windows: откроется браузер, дальше Ctrl+P
            else:
                import webbrowser
                webbrowser.open("file://" + путь)
        except Exception as e:                         # noqa: BLE001
            log_line(f"чек не открылся: {e}")
        self.s_work.итог_текст.setText("Чек сохранён: " + путь)
        if not self.s_work.отправлено:
            # Сделки ещё нет, а чек уже напечатан — пусть он будет и в оценке на сервере:
            # иначе в общей базе останется проверка без того, что клиент унёс с собой.
            self._дослать_на_сервер({"чек": dict(сделка)})
            self.s_work.сказать("Чек открыт для печати. Сделку в Оценку ещё не отправили.",
                                беда=False)
        log_line(f"чек напечатан до отправки: {путь}" if not self.s_work.отправлено
                 else f"чек напечатан: {путь}")

    def go_home(self):
        phoneweb.закрыть()                      # ссылка из прошлой сделки больше не работает
        self.тест_опрос.stop()
        self.медиа_опрос.stop()
        self.return_timer.stop()
        if self.pipeline and self.pipeline.isRunning():
            self.pipeline.cancel.set()                 # слушатель истории больше не нужен
            self.pipeline.остановить_слушателя()
        self.state = "idle"
        self.last = None
        self.сделка, self.код_медиа, self.анкета = {}, "", {}
        self.код_теста, self.тест_телефона = "", {}
        self.статус_сделки = self.переклассификация = None
        self.s_main.set_device("found" if self.кабель == READY else "wait")
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
