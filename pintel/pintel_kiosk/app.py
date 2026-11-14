# -*- coding: utf-8 -*-
"""Окно киоска: состояния «ожидание → проверка → результат», опрос кабеля,
связь с сервером в фоне. Запуск: pintel-kiosk (настройки приходят с сервера)."""
import asyncio
import os
import sys
import hashlib
import json
import time
import traceback
import uuid
from datetime import datetime

from PySide6.QtCore import QEasingCurve, QRectF, QThread, QTimer, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPalette, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsScene, QGraphicsView, QMainWindow, QStackedWidget

from pintel_core import phonetest
from pintel_core.devicelink import apple_service, connect
from pintel_core.devicelink.connect import NO_DEVICE, NO_DRIVER, READY
from pintel_core.external import ocenka

from . import phoneweb

from . import __version__, config, ui, ui_admin, ui_deal, ui_link, ui_start
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
        self._затемнение = 0.0
        self._переход = QVariantAnimation(self)
        self._переход.setStartValue(1.0)
        self._переход.setEndValue(0.0)
        self._переход.setDuration(340)
        self._переход.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._переход.valueChanged.connect(self._шаг_перехода)
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
        self.set_bg(ui.C["ground"])

    def set_bg(self, color):
        self.setBackgroundBrush(QColor(color))

    # Смена экрана — не щелчок, а короткое проявление из белого. Рисуется на переднем плане
    # самой сцены, а не отдельным виджетом поверх экранов: виджет-занавес был бы соседом
    # всего остального и мешал бы и мыши, и раскладке.
    def проявить(self):
        self._переход.stop()
        self._затемнение = 1.0
        self._переход.start()

    def _шаг_перехода(self, v):
        self._затемнение = float(v)
        self.viewport().update()

    def drawForeground(self, painter, rect):
        if self._затемнение <= 0.004:
            return
        цвет = QColor(ui.C["ground"])
        цвет.setAlphaF(min(1.0, self._затемнение))
        painter.fillRect(rect, цвет)

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
    связь_сказала = Signal(str)                 # ход починки службы Apple, из потока

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.client = Client(cfg)
        self.state = "idle"
        self.wait_unplug = False
        self.pipeline = None
        self.last = None
        self._вопрос_истории = 0                # номер последнего вопроса об истории телефона
        self.tasks = []
        # служба Apple: пробовали ли поднять её молча, идёт ли починка, наша ли это забота
        self._связь_пробовали = self._чиним_связь = self._связь_не_чиним = False
        # Кнопка «Починить связь» есть всегда, а не только когда служба Apple молчит: её жмут
        # как раз тогда, когда служба отвечает, а телефон не виден. Только на Windows — на
        # маке и линуксе службы Apple нет, и кнопка там была бы обманом.
        self._связь_всегда = sys.platform == "win32"
        self.setWindowTitle(ui.НАЗВАНИЕ)
        self.stack = QStackedWidget()
        self.host = ScaledHost(self.stack)
        self.setCentralWidget(self.host)
        точка = cfg.get("point") or ""
        # Три экрана на всю программу: ожидание, анкета (состояние и клиент — до кабеля, как
        # у продавца в боте Оценки) и рабочее окно. Проверка, сделка и медиа живут в одном
        # окне — за ним работает сотрудник, а не клиент.
        self.s_main = ui.MainScreen(точка)
        # Привязка — сразу после ожидания: сотрудник сканирует QR, и бот Оценки запоминает,
        # чья сделка. Дальше бот сам попросит у него фото и видео, второго QR нет.
        self.s_link = ui_link.LinkScreen(точка)
        self.s_start = ui_start.StartScreen(точка)
        self.s_work = ui_deal.WorkScreen(точка)
        # Токен точки вводят здесь, а не в файле настроек: программа — внешняя часть, всё
        # остальное приходит с сервера. Меню администратора скрыто от клиента сочетанием клавиш.
        self.s_token = ui_admin.TokenScreen()
        self.s_admin = ui_admin.AdminScreen()
        for s in (self.s_main, self.s_link, self.s_start, self.s_work, self.s_token, self.s_admin):
            self.stack.addWidget(s)
        self.s_link.готово.connect(self._привязка_готова)
        self.s_link.отмена.connect(self.go_home)
        self.s_link.новый_код.connect(self.новый_код_медиа)
        # привязан ли сотрудник к этой сделке и как его зовут в боте Оценки
        self.привязан, self.сотрудник = False, ""
        # автоцена: отпечаток данных, по которым её уже спросили, метка вопроса и когда
        self._цена_подпись = self._цена_запрос = ""
        self._цена_спросили_в = 0.0
        self.s_token.принят.connect(self.новый_токен)
        self.s_token.обновить_список.connect(self.спросить_точки)
        self.s_admin.закрыть.connect(self.закрыть_меню)
        self.s_admin.сменить_токен.connect(self.новый_токен)
        self.s_admin.обновить.connect(self._проверить_обновление)
        self.s_main.начать.connect(self.начать_сделку)
        self.s_main.обновить.connect(self.обновиться)
        self.s_main.починить_связь.connect(self.починить_связь)
        self.s_work.починить_связь.connect(self.починить_связь)
        self.s_work.напомнить.connect(self.напомнить_о_медиа)
        self.связь_сказала.connect(self._связь_идёт)
        self._кнопки_связи()
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
        self.s_work.перепроверить.connect(self.перепроверить_телефон)
        self.s_work.проверки_руками.connect(self._руками_отметили)
        # лоток — другая строка прайса («(Esim)»): сняли галочку — цену спрашиваем заново
        self.s_work.лоток.toggled.connect(lambda _=False: self._цена_пересчитать())
        # Результат теста приходит из потока мини-сервера, а не из потока окна: сигнал
        # переносит его в поток Qt сам, трогать виджеты из чужого потока нельзя.
        self.тест_приехал.connect(self._тест_с_телефона)
        self.код_медиа = ""
        self.код_теста = ""
        # Коды теста этой сделки. «Другой код» прежние не отменяет, пока результата нет:
        # клиент мог открыть страницу по прошлому QR, и пройденный на ней тест терять нельзя.
        self.коды_теста = []
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
        сменился = self.stack.currentWidget() is not w
        self.stack.setCurrentWidget(w)
        self.host.set_bg(ui.C["ground"])
        if сменился and self.isVisible():
            self.host.проявить()

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
            updater.перенести_своё(установлена, новая)   # чужое рядом с exe не теряем
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

    # ---------- связь с iPhone: служба Apple ----------
    def _связь_пропала(self):
        """Служба Apple молчит. Первый раз за сбой поднимаем её сами и молча — на запуск
        остановленной службы прав не нужно. Не вышло — показываем кнопку: дальше идёт
        установка или перезапуск, а это уже окно Windows «Разрешить?»."""
        if self._чиним_связь or self._связь_не_чиним:
            return
        if not self._связь_пробовали:
            self._связь_пробовали = True
            self._чиним_связь = True
            self._run(apple_service.починить, ok=self._связь_молча,
                      err=lambda текст: self._связь_молча(apple_service.НЕ_ВЫШЛО))
            return
        self._кнопки_связи("Починить связь с iPhone")

    def _связь_молча(self, итог):
        self._чиним_связь = False
        self._связь_не_чиним = итог == apple_service.НЕ_WINDOWS
        if self._связь_не_чиним:
            self._кнопки_связи()                       # не Windows — кнопке здесь не место
        log_line(f"связь: служба Apple молчит, попытка без прав — {итог}")

    def _связь_вернулась(self):
        if self._связь_пробовали and not self._чиним_связь:
            self._связь_пробовали = False
            self._кнопки_связи()

    def _кнопки_связи(self, текст="", занято=False):
        """Кнопка «Починить связь» на экране ожидания и на экране сделки. Без текста — её
        обычный вид: на Windows она есть всегда, в остальных случаях спрятана."""
        if not текст and self._связь_всегда and not self._связь_не_чиним:
            текст = "Починить связь с iPhone"
        self.s_main.показать_починку(текст, занято=занято)
        # на экране сделки кнопка стоит на странице шагов проверки: телефон прочитан — страница
        # сменилась, и кнопка ушла вместе с ней
        # и кнопка там узкая: в ней короткое «Чиним связь…», а что именно происходит —
        # строкой под колонками (см. _связь_идёт)
        self.s_work.показать_починку(bool(текст), занято=занято, текст="Чиним связь…" if занято else "")

    def _связь_идёт(self, текст):
        """Ход починки из потока: что происходит, сотрудник видит там, где нажал."""
        self._кнопки_связи(текст, занято=True)
        if self.state != "idle":
            self.s_work.сказать(текст, беда=False)

    def починить_связь(self):
        """Кнопка «Починить связь»: запустить службу Apple, нет её — скачать и поставить,
        отвечает, а телефон не виден — перезапустить. По кнопке служба перезапускается
        всегда: ответ «связь работает» человеку, у которого телефон не читается, — отказ."""
        if self._чиним_связь:
            return
        self._чиним_связь = True
        self._кнопки_связи("Чиним связь…", занято=True)
        self._run(lambda: apple_service.обеспечить(сказать=self.связь_сказала.emit, принудительно=True),
                  ok=self._связь_починили,
                  err=lambda текст: self._связь_починили((apple_service.НЕ_ВЫШЛО, текст)))

    def _связь_починили(self, пара):
        итог, текст = пара
        self._чиним_связь = False
        log_line(f"связь: починка по кнопке — {итог}: {текст}")
        готово = итог == apple_service.ГОТОВО
        self.s_main.set_status(текст, ok=готово)
        if self.state != "idle":
            self.s_work.сказать(текст, беда=not готово)
        self._кнопки_связи("" if готово else "Починить связь с iPhone — повторить")

    def on_tick(self, state, detail, count):
        self.net.device_state = state
        self.кабель = state
        if state == NO_DRIVER:
            self._связь_пропала()
        else:
            self._связь_вернулась()
        if self.state == "idle":
            if state == NO_DRIVER:
                if not self._чиним_связь:
                    self.s_main.set_status("Нет связи с iPhone — служба Apple не отвечает", ok=False)
                self.s_main.set_device("nodriver")
            elif state == READY and count:
                self.s_main.set_device("found")
            elif state == NO_DEVICE:
                self.wait_unplug = False
                self.s_main.set_device("wait")
                if self.client.enabled and self.client.online:
                    self.s_main.set_status("Готов к работе", ok=True)
        elif self.state in ("link", "intake"):
            # привязка и анкета ещё не пройдены: кабель подключили — ждём, читать телефон рано
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
        self._спросить_историю(rep, (result.get("server") or {}).get("id"))
        if not self.код_медиа:                  # код обмена заведён ещё на экране привязки
            self.новый_код_медиа()
        self._цена_пересчитать()
        # С этой секунды клиенту показывают QR теста. Опрос результата обязан идти, что бы
        # ни было с ним до сих пор: заглохший опрос — это тест, пройденный впустую.
        if self.тест_через_сервер and not self.s_work._тест_закрыт() and not self.тест_опрос.isActive():
            self.тест_опрос.start(3000)

    def _руками_отметили(self):
        """Отметку руками поменяли — состояние сделки пересчитываем сразу.

        Отказ по любому пункту (герметик, кнопки, вибрация) — это «Есть видимые дефекты», и
        видеть это сотрудник должен на плашке до отправки, а не узнавать из карточки бота."""
        if self.state == "work":
            self._классифицировать((self.last or {}).get("report") or {})
            self._цена_пересчитать()

    def _спросить_историю(self, rep, ev_id=None):
        """История по IMEI: сделки Оценки, заявки с сайта, наши прошлые проверки.

        Спрашиваем сразу после чтения телефона и в отдельном потоке: это подсказка у стойки,
        и ни ждать её, ни падать из-за неё проверка не должна. Молчание называем словами —
        пустой угол сотрудник прочитает как «аппарат у нас впервые»."""
        пас = (rep or {}).get("паспорт") or {}
        имеи = [x for x in (пас.get("imei"), пас.get("imei2")) if str(x or "").strip()]
        if not имеи:                                   # запечатанный: IMEI взяли с коробки
            имеи = [x for x in (self.анкета.get("imei") or []) if str(x or "").strip()]
        if not имеи:
            self.s_work.set_история({"почему": ["IMEI не прочитался — историю не искали"]})
            return
        if not self.client.enabled:
            self.s_work.set_история({"почему": ["нет токена точки — историю не спросили"]})
            return
        self.s_work.set_история(None)
        # Ответ принимаем только на последний вопрос. Раньше опоздавший ответ менял одну
        # плашку в углу; теперь записи встают окном посреди экрана, и история прошлого
        # телефона, пришедшая в новую сделку, остановила бы её чужими записями.
        self._вопрос_истории += 1
        вопрос = self._вопрос_истории

        def принять(данные, вопрос=вопрос):
            if вопрос == self._вопрос_истории:
                self.s_work.set_история(данные)

        self._run(lambda: self.client.история(имеи, ev_id),
                  ok=принять,
                  err=lambda текст: принять({"почему": [str(текст)]}))

    def _классифицировать(self, rep):
        """Выбор сотрудника до диагностики + отчёт → состояние сделки (phone_status Оценки)."""
        состояние = self.анкета.get("состояние") or "норма"
        статус, почему = ocenka.переклассифицировать(состояние, rep, self.s_work.ручная)
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
        self._вопрос_истории += 1               # ответ про прошлый телефон сюда не придёт
        self.статус_сделки = self.переклассификация = None
        self.коды_теста = []                    # коды прошлой сделки в эту не идут
        self.новый_код_теста()                  # свой одноразовый код теста на каждую сделку
        self.s_start.начать()
        self.s_work.начать()
        # Первым делом — чья сделка: QR на экране привязки. Код обмена заводим здесь же, он
        # один на всю сделку: по нему бот узнаёт сотрудника, называет цену и создаёт сделку.
        self.s_link.начать()
        self.state = "link"
        self.новый_код_медиа()
        self.show_screen(self.s_link)

    def _привязка_готова(self, имя):
        """Сотрудник отсканировал QR — сделка его. Идём на анкету."""
        if self.state != "link":
            return
        self.привязан, self.сотрудник = True, str(имя or "").strip()
        self.s_work.set_привязка(self.сотрудник)
        log_line(f"оценка {self.код_медиа}: привязана к сотруднику {self.сотрудник or '(без имени)'}")
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
        # Запечатанный тоже бывает не впервые: IMEI с коробки, а заявку по нему могли
        # оставить на сайте, и цену ему уже называли.
        self._спросить_историю(rep, (result.get("server") or {}).get("id"))
        if not self.код_медиа:                  # код обмена заведён ещё на экране привязки
            self.новый_код_медиа()
        self._цена_пересчитать()
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
        cfg = self.cfg
        if not (cfg.get("ocenka_bot_token") and cfg.get("ocenka_chat_id")):
            self.s_work.сказать("В настройках точки не заданы ocenka_bot_token и "
                                       "ocenka_chat_id — отправлять некуда")
            return
        if not self.код_медиа:
            self.s_work.сказать("Нет кода для медиа — нажмите «Другой код»")
            return
        код = self.код_медиа
        if self.статус_сделки is None:
            self._классифицировать(rep)
        self.s_work.занято("Отправляем…")

        def job():
            посылка = self._собрать_посылку(поля)
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

    def _собрать_посылку(self, поля) -> dict:
        """Сделка так, как её получит бот. Одна сборка на два дела: по этой посылке бот
        называет цену ДО сделки и из неё же потом создаёт сделку — разойтись им нельзя."""
        rep = (self.last or {}).get("report") or {}
        пас, cfg = rep.get("паспорт") or {}, self.cfg
        клиент, код = {"имя": поля["имя"], "телефон": поля["телефон"]}, self.код_медиа
        магазин = self.cfg.get("point_id")        # он же id магазина в Оценке
        тест = поля.get("тест") or self.тест_телефона
        тест_пропущен = поля.get("тест_пропущен") or ""
        ручная = поля.get("ручная") or {}
        тест_строкой = (f"Тест на телефоне пропущен: {тест_пропущен}" if тест_пропущен
                        else phonetest.словами(тест))
        состояние = self.анкета.get("состояние") or "норма"
        статус, почему = self.статус_сделки, self.переклассификация
        откуда = f"Киоск {cfg.get('point') or ''} от {datetime.now():%Y-%m-%d}"
        if состояние == "новый":
            данные = ocenka.данные_запечатанного(
                rep.get("sickw") or {}, [пас.get("imei"), пас.get("imei2")], клиент,
                sim=поля["sim"], коробка=поля["коробка"], шнур=поля["шнур"],
                комментарий=поля["комментарий"], откуда=откуда, рфс=rep.get("рфс"),
                отчёт=rep)
            данные["shop_id"] = магазин
            # база IMEI цвета не дала — тот, что сотрудник выбрал кнопкой
            данные["цвет"] = данные.get("цвет") or поля.get("цвет")
        else:
            данные = {
                "модель": пас.get("модель"), "код_модели": пас.get("код_модели"),
                "память": (rep.get("память") or {}).get("объём_гб"),
                "акб": (rep.get("батарея") or {}).get("здоровье_%"),
                "циклы": (rep.get("батарея") or {}).get("циклы"),
                # цвет из базы IMEI; не дала — тот, что сотрудник выбрал кнопкой
                "цвет": пас.get("цвет") or поля.get("цвет"), "sim": поля["sim"],
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
        # сумма, которую сотрудник назвал клиенту (автоцена — подсказка), и чек на домене:
        # бот кладёт сумму в сделку, а ссылку — в поле «Заключение» товара МойСклада
        данные["цена_клиенту"] = поля.get("сумма_клиенту")
        данные["ссылка_чека"] = ((self.last or {}).get("server") or {}).get("ссылка_чека")
        return ocenka.посылка(данные, код, точка=cfg.get("point") or "")

    # ---------- автооценка до сделки ----------
    def _цена_пересчитать(self):
        """Спросить у бота автоцену — когда проверки закрыты и данные с прошлого вопроса
        изменились. Цену считает только бот Оценки, своим прайсом: касса отдаёт ему ту же
        посылку, что потом станет сделкой, и показывает ответ."""
        if not (self.привязан and self.state == "work" and self.client.enabled and self.код_медиа):
            return
        if self.s_work.отправлено or not self.s_work.проверки_закрыты():
            return
        try:
            посылка = self._собрать_посылку(self.s_work.данные())
        except Exception as exc:                                 # noqa: BLE001
            # не хватает имени клиента или модели — посылку не собрать, спрашивать нечем
            log_line(f"автоцена: посылку не собрать ({exc})")
            return
        # От чего зависит цена. Заметка, коробка и шнур в неё не входят — иначе каждый
        # набранный в заметке символ спрашивал бы бота заново.
        важное = {k: посылка.get(k) for k in ("ручная_диагностика", "тест_телефона", "тест_пропущен",
                                              "не_прочиталось", "shop_id", "переклассификация")}
        важное["сделка"] = {k: v for k, v in (посылка.get("сделка") or {}).items()
                            if k in ("model", "ddr", "akb", "akb_exact", "sim", "phone_status")}
        подпись = hashlib.sha1(json.dumps(важное, sort_keys=True, ensure_ascii=False,
                                          default=str).encode("utf-8")).hexdigest()
        if подпись == self._цена_подпись:
            return
        self._цена_подпись, self._цена_запрос = подпись, uuid.uuid4().hex[:10]
        self._цена_спросили_в = time.monotonic()
        посылка["запрос_цены"] = self._цена_запрос
        # Эта касса цену из прайса клиенту не показывает: бот шлёт её подсказкой сотруднику и
        # спрашивает у него сумму. Бот прежней версии ключа не знает и отвечает как раньше.
        посылка["сумму_назовёт_сотрудник"] = True
        self.s_work.set_цена({"считаем": True})
        код, запрос = self.код_медиа, self._цена_запрос

        def ответили(res):
            if запрос != self._цена_запрос:          # уже спросили заново — этот ответ устарел
                return
            if not (res or {}).get("принято"):
                почему = str((res or {}).get("почему") or "сервер не ответил")
                self.s_work.set_цена({"готово": True, "цена": None, "почему": почему})
                log_line(f"автоцена {код}: спросить не вышло — {почему}")

        self._run(lambda: self.client.спросить_цену(код, посылка), ok=ответили,
                  err=lambda e: ответили({"принято": False, "почему": str(e)[:120]}))
        self.медиа_опрос.start(1200)             # ответ бота придёт тем же опросом, что и медиа

    def _цена_пришла(self, состояние):
        """Опрос принёс ответ бота о цене — показываем, если он на НАШ последний вопрос.

        Ответов по одному вопросу бывает два: сначала «посчитал, спросил сотрудника о сумме»
        (`ждём_сумму`), потом сама сумма. Пока сделка не отправлена, сотрудник может назвать
        в боте другую сумму — поэтому за ответом следим и после первой."""
        if not self._цена_запрос or self.s_work.отправлено:
            return
        было = self.s_work.цена
        оценка = (состояние or {}).get("оценка")
        if isinstance(оценка, dict) and оценка.get("запрос") == self._цена_запрос:
            if оценка.get("цена") and оценка.get("ждём_сумму") and not оценка.get("сумма"):
                стало = {"ждём_сумму": True, "цена": оценка["цена"],
                         "беда": str(оценка.get("беда") or "")}
            else:
                стало = {"готово": True, "цена": оценка.get("цена"),
                         "почему": оценка.get("почему") or ""}
                if оценка.get("цена") and оценка.get("сумма"):
                    стало["сумма"] = int(оценка["сумма"])
            if стало == было:
                return
            self.s_work.set_цена(стало)
            if стало.get("ждём_сумму"):
                if not было.get("ждём_сумму"):
                    log_line(f"автоцена {self.код_медиа}: {оценка['цена']} ₸ — ждём сумму от сотрудника в боте")
            elif стало.get("сумма"):
                log_line(f"автоцена {self.код_медиа}: {оценка['цена']} ₸, сумма клиенту {стало['сумма']} ₸")
            else:
                log_line(f"автоцена {self.код_медиа}: "
                         + (f"{оценка['цена']} ₸" if оценка.get("цена") else f"нет — {оценка.get('почему')}"))
        elif было.get("готово") or было.get("ждём_сумму"):
            return                               # ответ уже есть; молчание бота — не про него
        elif time.monotonic() - self._цена_спросили_в > 30:
            # Бот молчит полминуты: он выключен или ещё не умеет называть цену до сделки.
            # Сделку это не держит — цену назовёт оценщик, как и раньше.
            self.s_work.set_цена({"готово": True, "цена": None,
                                  "почему": "бот Оценки не ответил о цене"})
            log_line(f"автоцена {self.код_медиа}: бот не ответил за 30 с")

    def новый_код_медиа(self):
        """Новый код обмена и ссылки на бота. С кода начинается сделка: он показан на экране
        привязки, по нему бот узнаёт сотрудника, называет цену и создаёт сделку. Придумываем
        его на месте: в базу Оценки с точки хода нет, строку по коду заведёт сам бот."""
        from pintel_core.external import ocenka_media
        self.привязан, self.сотрудник = False, ""
        self._цена_подпись = self._цена_запрос = ""
        self.s_work.set_привязка(None)
        self.s_work.set_цена({})
        if not self.cfg.get("ocenka_bot"):
            self.код_медиа = ""
            self.s_work.показать_код("—", "")
            self.s_work.медиа.setText("В кассе не задан ocenka_bot — медиа принять не от кого")
            self.s_link.показать_код("", "")
            return
        self.код_медиа = ocenka_media.новый_код()
        # два адреса на один код: «k» — привязка (первый экран), «p» — прежний приём медиа
        # по QR, он нужен только сделке без привязки
        self.s_link.показать_код(self.код_медиа,
                                 ocenka_media.ссылка_привязки(self.cfg["ocenka_bot"], self.код_медиа))
        self.s_work.показать_код(self.код_медиа,
                                 ocenka_media.ссылка(self.cfg["ocenka_bot"], self.код_медиа))
        self._медиа_спрашиваем = False
        if self.client.enabled:
            self.s_work.set_медиа({})           # ждём первого ответа сервера
            self.медиа_опрос.start(1500 if self.state == "link" else 3000)
        else:
            # Без связи с сервером спросить некого, и привязку увидеть нечем. Экран привязки
            # говорит это словами; обхода нет — без привязки сделка не начинается.
            слепо = {"известно": False, "почему": "касса не связана с сервером"}
            self.s_work.set_медиа(слепо)
            self.s_link.set_состояние(слепо)

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
        if self.state not in ("link", "work", "intake", "scanning"):
            self.медиа_опрос.stop()
            return
        if self.s_work.отправлено and not self._ждём_сделку:
            self.медиа_опрос.stop()
            return
        self._цена_пересчитать()                 # данные могли поменяться с прошлого круга
        self._медиа_спрашиваем = True
        код = self.код_медиа
        self._run(lambda: self.client.медиа(код), ok=self._медиа_спросили,
                  err=lambda e: self._медиа_спросили({"известно": False, "почему": str(e)[:80]}))

    def _медиа_спросили(self, состояние):
        self._медиа_спрашиваем = False
        состояние = состояние or {}
        if self.state == "link":
            # экран привязки ждёт одного: открыл ли сотрудник ссылку
            self.s_link.set_состояние(состояние)
            self.медиа_опрос.setInterval(1500 if состояние.get("известно") else 5000)
            return
        self._цена_пришла(состояние)
        if self._ждём_сделку:
            # посылка у бота: привязанный сотрудник шлёт ему медиа — показываем, что дошло
            self.s_work.set_медиа(состояние)
            self._сделка_в_оценке(состояние)
            return
        self.s_work.set_медиа(состояние)
        # Сервер не видит базу Оценки — спрашивать каждые три секунды незачем: ответ не
        # изменится от того, что мы повторим его двадцать раз в минуту.
        считаем = bool(self.s_work.цена.get("считаем") or self.s_work.цена.get("ждём_сумму"))
        self.медиа_опрос.setInterval(1200 if считаем else
                                     (3000 if состояние.get("известно") else 15000))
        if состояние.get("готово") and not self.привязан:
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

        Адрес — на нашем домене: там HTTPS, а значит телефон пускает страницу к микрофону
        (по локальной сети Safari этого не разрешает) и открывается она с любой сети, хоть
        с мобильного интернета. Пока сервер не ответил, QR не показываем вовсе: адрес кассы
        в локальной сети открывается только с её же Wi-Fi, и телефон, успевший его считать,
        грузил бы страницу без конца. Сервер не настроен или не ответил — остаётся
        мини-сервер в самом киоске, и на экране сказано, что нужен Wi-Fi точки.

        «Другой код», пока результата нет, прежние коды сделки не отменяет (`коды_теста`):
        тест, который клиент прошёл по прошлому QR, касса примет тоже. Результат уже был —
        значит, сотрудник хочет тест заново, и старые коды в счёт не идут.
        """
        from pintel_core.external import ocenka_media
        прежние = [] if (self.тест_телефона or self.s_work._тест_закрыт()) else self.коды_теста
        self.тест_телефона = {}
        self.тест_через_сервер = False
        self.тест_опрос.stop()
        self.код_теста = ocenka_media.новый_код(16)      # длиннее: этот код живёт в интернете
        self.коды_теста = (прежние + [self.код_теста])[-3:]
        phoneweb.открыть(self.код_теста, self._тест_из_сети, ещё=self.коды_теста[:-1])
        self.s_work.set_тест({})
        токен = self.код_теста
        if not self.client.enabled:
            self._тест_по_локальной_сети(токен, "касса без сервера")
            return
        log_line(f"тест на телефоне: код {токен}, спрашиваем адрес на домене")
        self.s_work.показать_тест("", "Готовим код…")
        # Домен спрашиваем в отдельном потоке: сделка начинается с нажатия, и держать окно
        # на время запроса к серверу нельзя.
        self._run(lambda: self.client.открыть_тест(токен),
                  ok=lambda ссылка_домена: self._тест_на_домене(токен, ссылка_домена),
                  err=lambda e: self._тест_по_локальной_сети(токен, f"домен не ответил ({e})"))

    def _тест_на_домене(self, токен, ссылка):
        """Сервер завёл сессию теста: показываем его адрес и начинаем спрашивать результат."""
        if токен != self.код_теста or self.s_work._тест_закрыт():
            return
        if not ссылка:
            self._тест_по_локальной_сети(токен, "сервер не дал адрес")
            return
        self.тест_через_сервер = True
        self.s_work.показать_тест(ссылка)
        self.тест_опрос.start(3000)
        log_line(f"тест на телефоне: домен, ссылка {ссылка}")

    def _тест_по_локальной_сети(self, токен, почему_так=""):
        """Запасной путь: страницу отдаёт мини-сервер в самом киоске. Открывается она только
        с Wi-Fi точки, и это сказано на экране — иначе телефон на мобильном интернете грузит
        её без конца, а сотрудник не знает почему."""
        if токен != self.код_теста or self.s_work._тест_закрыт():
            return
        порт = int(self.cfg.get("phone_test_port") or phoneweb.ПОРТ)
        ссылка = phoneweb.ссылка(токен, порт) if self.веб_телефона else ""
        if not self.веб_телефона:
            подсказка = f"Порт {порт} занят другой программой — тест на телефоне не открыть."
        elif not ссылка:
            подсказка = ""                       # сети нет вовсе — окно скажет это само
        elif self.client.enabled:
            подсказка = ("Сервер не ответил — этот код откроется только с Wi-Fi точки. "
                         "Подключите телефон к нему или нажмите «Другой код».")
        else:
            подсказка = "Код откроется только с Wi-Fi точки — подключите телефон к нему."
        self.s_work.показать_тест(ссылка, подсказка)
        log_line(f"тест на телефоне: код {токен}, {почему_так + ' — ' if почему_так else ''}"
                 f"локальная сеть, ссылка {ссылка or 'нет'}")

    def _спросить_тест(self):
        """Пока клиент проходит тест на домене, касса спрашивает сервер: не готов ли.

        По локальной сети результат приходит к нам сам, а через домен он ложится в базу —
        узнать о нём можно только спросив. Запрос сетевой, поэтому в отдельном потоке и не
        больше одного зараз.

        Опрос идёт всю сделку, начиная с экрана привязки. Раньше «link» в списке не было, и
        первый же круг опроса глушил его насовсем: код теста заводится в начале сделки, а
        сотрудник в это время ещё сканирует QR привязки. Клиент потом проходил тест, телефон
        отдавал результат серверу, а касса его не спрашивала — выручала только кнопка
        «Другой код», которая запускала опрос заново.

        Спрашиваем по всем кодам сделки: клиент мог пройти тест по QR, который был на
        экране до «Другой код»."""
        if not (self.тест_через_сервер and self.код_теста) or self._тест_спрашиваем:
            return
        if self.s_work._тест_закрыт() or self.state not in ("link", "intake", "scanning", "work"):
            self.тест_опрос.stop()
            return
        self._тест_спрашиваем = True
        коды = list(reversed(self.коды_теста)) or [self.код_теста]

        def спросить():
            for n, токен in enumerate(коды):     # свежий код первым
                try:
                    res = self.client.результат_теста(токен)
                except Exception:                # noqa: BLE001
                    if n == 0:
                        raise
                    continue                     # прежний код сервер мог и не знать
                if res:
                    return res
            return {}

        self._run(спросить, ok=self._тест_спросили,
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
                # Оценку провёл тот, к кому сделка привязана через бота. Имя из настроек
                # точки — запасное: его вписывали на точках до привязки, и там оно пустое
                # или общее на всех, поэтому в чеке стоял прочерк.
                "сотрудник": self.сотрудник or self.cfg.get("staff_name") or "",
                "точка": self.cfg.get("point") or "",
                "коробка": поля.get("коробка"), "шнур": поля.get("шнур"),
                "комментарий": поля.get("комментарий"), "фирма": self._фирма(),
                "цвет": поля.get("цвет"),          # выбран сотрудником, когда база его не дала
                # что назвали клиенту и что подсказал прайс — в чеке не печатается, лежит
                # при оценке на сервере, чтобы расхождение было видно и без базы Оценки
                "сумма_клиенту": поля.get("сумма_клиенту"), "автоцена": поля.get("автоцена"),
                # отчёт по тестам внизу чека: тест на телефоне клиента и проверки руками
                "тест": dict(поля.get("тест") or self.тест_телефона or {}),
                "тест_пропущен": поля.get("тест_пропущен") or "",
                "ручная": dict(поля.get("ручная") or {}),
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
            if self.привязан:
                # бот сейчас напишет сотруднику и попросит фото и видео; сделка — после них
                self.s_work.ушло(код, "", ждём_медиа=True)
                log_line(f"оценка {код}: отправлена, бот просит медиа у {self.сотрудник or 'сотрудника'}")
            else:
                self.s_work.ушло(код, "Сделка создаётся. Номер появится здесь.")
            self.медиа_опрос.start(2000)
        else:
            self._ждём_сделку = False
            self.медиа_опрос.stop()             # карточка ушла, дальше её подтверждают
            self.s_work.ушло(код, "Оценщик подтверждает сделку в Telegram — "
                                  "там появится её номер.")

    def напомнить_о_медиа(self):
        """Кнопка «Напомнить в боте»: сотрудник потерял запрос фото и видео — сервер пишет
        ему от имени бота ещё раз. Сама сделка цела и без этого."""
        код = self.код_медиа
        if not код:
            return
        self.s_work.напоминание(None)
        log_line(f"оценка {код}: просим бот напомнить сотруднику про медиа")
        self._run(lambda: self.client.напомнить_о_медиа(код),
                  ok=self.s_work.напоминание,
                  err=lambda текст: self.s_work.напоминание({"отправлено": False, "почему": текст}))

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
        self._вопрос_истории += 1               # сделку бросили — ответ по ней уже не нужен
        self.сделка, self.код_медиа, self.анкета = {}, "", {}
        self.привязан, self.сотрудник = False, ""
        self._цена_подпись = self._цена_запрос = ""
        self._ждём_сделку = False
        self.код_теста, self.коды_теста, self.тест_телефона = "", [], {}
        self.статус_сделки = self.переклассификация = None
        self.s_main.set_device("found" if self.кабель == READY else "wait")
        self.show_screen(self.s_main)


def light_palette():
    """Программа всегда светлая, какая бы тема ни стояла в Windows."""
    pal = QPalette()
    for role in (QPalette.Window, QPalette.Base, QPalette.AlternateBase, QPalette.Button, QPalette.ToolTipBase):
        pal.setColor(role, QColor(ui.C["ground"]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.ToolTipText):
        pal.setColor(role, QColor(ui.C["ink"]))
    pal.setColor(QPalette.Highlight, QColor(ui.C["action"]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.PlaceholderText, QColor(ui.C["muted"]))
    return pal


def main(argv=None):
    # повышенный запуск «поставить службу Apple»: без окна, сделал — вышел (apple_service)
    код = apple_service.точка_входа(list(argv or sys.argv))
    if код is not None:
        return код
    cfg = config.load()
    if sys.platform == "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "windows:darkmode=0")   # не следовать тёмной теме Windows
    if sys.platform == "win32":
        # своя метка приложения: без неё Windows держит на панели задач значок-заглушку
        # и не знает, что окно и ярлык — одна программа
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Pintel.Diagnostics")
        except Exception:                                    # noqa: BLE001 — значок не повод не запуститься
            pass
    app = QApplication(argv or sys.argv)
    app.setApplicationName(ui.НАЗВАНИЕ)
    app.setWindowIcon(QIcon(os.path.join(ui.ASSETS, "icon.ico")))   # окно и панель задач
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
