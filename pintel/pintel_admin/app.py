# -*- coding: utf-8 -*-
"""Окно административной программы: вход, меню, разделы.

Устройство простое и намеренно такое: одно окно, слева меню, справа раздел. Разделы ничего
не считают — всё считает сервер (`/api/admin/…`), здесь только показ. Это не лень, а
правило: число на экране владельца и число в выгрузке обязаны совпадать, а совпадают они
только если считаются в одном месте.

Сеть — в отдельном потоке: окно не должно замирать, пока сервер думает. Ошибка связи это
строка на экране, а не пустой раздел: «сервер не ответил» человеку понятнее, чем таблица,
которая просто не появилась.
"""
import sys

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from . import __version__, config
from .client import Клиент, НетСвязи, НуженВход
from .ui import (C, FONT_HEAD, Карта, Меню, Плитка, QSS, Фон, W, давно, деньги, font, load_fonts,
                 миллионы, надпись, тень)

# Как часто обновлять то, что на экране. Минута: владелец смотрит на сеть, а не на секундомер,
# а сервер не должен отвечать на лишние вопросы с десятка окон.
ОБНОВЛЯТЬ_СЕК = 60


class Задача(QThread):
    """Один запрос к серверу вне окна. Результат и беда приходят сигналами."""

    готово = Signal(object)
    беда = Signal(str)

    def __init__(self, работа, parent=None):
        super().__init__(parent)
        self.работа = работа

    def run(self):
        try:
            self.готово.emit(self.работа())
        except (НетСвязи, НуженВход) as сбой:
            self.беда.emit(str(сбой))
        except Exception as сбой:                        # noqa: BLE001 — показываем, а не молчим
            self.беда.emit(f"{type(сбой).__name__}: {сбой}")


def таблица(колонки) -> QTableWidget:
    т = QTableWidget(0, len(колонки))
    т.setHorizontalHeaderLabels(колонки)
    т.verticalHeader().setVisible(False)
    т.setShowGrid(False)
    т.setSelectionBehavior(QTableWidget.SelectRows)
    т.setEditTriggers(QTableWidget.NoEditTriggers)
    т.setAlternatingRowColors(False)
    т.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    т.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
    return т


def заполнить(т: QTableWidget, строки, цвет_строки=None):
    """Строки в таблицу. `цвет_строки(строка)` → цвет или None: красим беду, а не всё подряд."""
    т.setRowCount(len(строки))
    for i, строка in enumerate(строки):
        цвет = цвет_строки(строка) if цвет_строки else None
        for j, значение in enumerate(строка):
            ячейка = QTableWidgetItem("" if значение is None else str(значение))
            if j == 0:
                шрифт = ячейка.font()
                шрифт.setWeight(W.DemiBold)
                ячейка.setFont(шрифт)
            if цвет:
                from PySide6.QtGui import QColor
                ячейка.setForeground(QColor(цвет))
            т.setItem(i, j, ячейка)


# ---------------------------------------------------------------- разделы


class Раздел(QWidget):
    """Общее у всех разделов: заголовок, подпись и строка беды."""

    def __init__(self, заголовок, подпись=""):
        super().__init__()
        self.корень = QVBoxLayout(self)
        self.корень.setContentsMargins(22, 18, 22, 18)
        self.корень.setSpacing(14)
        шапка = QVBoxLayout()
        шапка.setSpacing(2)
        шапка.addWidget(надпись(заголовок, "h1", шрифт=font(FONT_HEAD, 24, W.Bold)))
        self.подпись = надпись(подпись, "sub")
        шапка.addWidget(self.подпись)
        обёртка = QWidget()
        обёртка.setLayout(шапка)
        self.корень.addWidget(обёртка)
        self.беда = надпись("", "muted", цвет=C["badtext"])
        self.беда.setVisible(False)
        self.корень.addWidget(self.беда)

    def сказать_беду(self, текст):
        self.беда.setText(текст or "")
        self.беда.setVisible(bool(текст))


class Обзор(Раздел):
    """Первый экран: день целиком и точки сегодня."""

    def __init__(self):
        super().__init__("Обзор", "")
        ряд = QHBoxLayout()
        ряд.setSpacing(12)
        self.плитки = {}
        for ключ, подпись in (("проверок", "проверено телефонов"), ("выкуплено", "выкуплено"),
                              ("выдано", "выдано клиентам"), ("оценил_человек", "оценил человек")):
            п = Плитка(подпись)
            self.плитки[ключ] = п
            ряд.addWidget(п)
        обёртка = QWidget()
        обёртка.setLayout(ряд)
        self.корень.addWidget(обёртка)

        карта = Карта("точки сегодня")
        self.таблица = таблица(["ТОЧКА", "ПРОВЕРОК", "ВЫКУП", "ВЫДАНО"])
        карта.добавить(self.таблица)
        self.корень.addWidget(карта, 1)

    def показать(self, данные: dict):
        self.подпись.setText(f"Сегодня, {данные.get('день') or ''}")
        self.плитки["проверок"].показать(данные.get("проверок"))
        self.плитки["выкуплено"].показать(
            данные.get("выкуплено"),
            f"{round(данные['выкуплено'] * 100 / данные['проверок'])} % из проверенных"
            if данные.get("проверок") and данные.get("выкуплено") else "")
        self.плитки["выдано"].показать(
            миллионы(данные.get("выдано")) if данные.get("выдано") else None,
            f"средний чек {деньги(данные.get('средний_чек'))} ₸" if данные.get("средний_чек") else "")
        self.плитки["оценил_человек"].показать(данные.get("оценил_человек"))
        заполнить(self.таблица, [(т["точка"], т["проверок"], т["выкуп"], деньги(т["выдано"]) + " ₸")
                                 for т in данные.get("точки") or []])


class Тревоги(Раздел):
    def __init__(self):
        super().__init__("Требует внимания", "То, из-за чего стоит работа или теряются деньги")
        карта = Карта("")
        self.таблица = таблица(["ВАЖНОСТЬ", "ЧТО", "ПОЧЕМУ"])
        карта.добавить(self.таблица)
        self.корень.addWidget(карта, 1)

    def показать(self, тревоги: list):
        self.подпись.setText(f"{len(тревоги)} строк(и)" if тревоги else "Сейчас ничего — это хорошо")
        заполнить(self.таблица, [(т["важность"], т["что"], т["почему"]) for т in тревоги],
                  цвет_строки=lambda с: C["badtext"] if с[0] == "беда" else None)


class Точки(Раздел):
    def __init__(self):
        super().__init__("Точки и кассы", "")
        карта = Карта("")
        self.таблица = таблица(["ТОЧКА", "ГОРОД", "НА СМЕНЕ", "КАСС", "СБОРКА", "СВЯЗЬ", "СДЕЛОК"])
        карта.добавить(self.таблица)
        self.корень.addWidget(карта, 1)

    def показать(self, точки: list):
        на_связи = sum(1 for т in точки if (т.get("молчит_часов") or 99) < 2)
        self.подпись.setText(f"{len(точки)} точек · {на_связи} на связи")
        заполнить(self.таблица,
                  [(т["точка"], т["город"], т["на_смене"] or "—", т["касс"], т["сборка"] or "—",
                    давно(т["молчит_часов"]), т["сделок_сегодня"]) for т in точки],
                  цвет_строки=lambda с: C["badtext"] if "дн назад" in str(с[5]) else None)


class Компьютеры(Раздел):
    def __init__(self):
        super().__init__("Компьютеры", "Каждая машина, на которой стоит наша программа")
        карта = Карта("")
        self.таблица = таблица(["МАШИНА", "ТОЧКА", "СБОРКА", "СВЯЗЬ", "ДОСТУП"])
        карта.добавить(self.таблица)
        self.корень.addWidget(карта, 1)

    def показать(self, машины: list):
        self.подпись.setText(f"{len(машины)} машин")
        заполнить(self.таблица,
                  [(м["машина"], м["точка"] or "—", м["сборка"] or "—", давно(м["молчит_часов"]),
                    "работает" if м["работает"] else "закрыт") for м in машины],
                  цвет_строки=lambda с: C["badtext"] if с[4] == "закрыт" else None)


class Люди(Раздел):
    def __init__(self):
        super().__init__("Люди", "Выработка за месяц и доступ")
        карта = Карта("")
        self.таблица = таблица(["СОТРУДНИК", "ТОЧКА", "РОЛЬ", "ПРОВЕРОК", "ВЫКУПОВ", "ВЫДАНО", "ДОСТУП"])
        карта.добавить(self.таблица)
        self.корень.addWidget(карта, 1)

    def показать(self, люди: list):
        работают = sum(1 for ч in люди if ч["доступ"])
        self.подпись.setText(f"{len(люди)} человек · {работают} с доступом")
        заполнить(self.таблица,
                  [(ч["имя"], ч["точка"] or "—", ч["роль_словами"], ч["проверок_за_месяц"],
                    ч["выкупов_за_месяц"], миллионы(ч["выдано_за_месяц"]),
                    "есть" if ч["доступ"] else "закрыт") for ч in люди],
                  цвет_строки=lambda с: C["muted"] if с[6] == "закрыт" else None)


class Вход(QWidget):
    """Экран входа. Пароль не сохраняется нигде — он меняется на токен."""

    вошли = Signal(str, str)                              # токен, имя

    def __init__(self, окно):
        super().__init__()
        self.окно = окно
        корень = QVBoxLayout(self)
        корень.addStretch(1)
        карта = Карта("административное управление")
        карта.setFixedWidth(380)
        карта.добавить(надпись("Вход", шрифт=font(FONT_HEAD, 24, W.Bold)))
        self.логин = QLineEdit()
        self.логин.setPlaceholderText("логин")
        self.пароль = QLineEdit()
        self.пароль.setPlaceholderText("пароль")
        self.пароль.setEchoMode(QLineEdit.Password)
        self.беда = надпись("", "muted", цвет=C["badtext"], перенос=True)
        self.кнопка = QPushButton("Войти")
        self.кнопка.setObjectName("главная")
        for w in (self.логин, self.пароль, self.беда, self.кнопка):
            карта.добавить(w)
        self.пароль.returnPressed.connect(self.кнопка.click)
        ряд = QHBoxLayout()
        ряд.addStretch(1)
        ряд.addWidget(карта)
        ряд.addStretch(1)
        обёртка = QWidget()
        обёртка.setLayout(ряд)
        корень.addWidget(обёртка)
        корень.addStretch(1)

    def сказать(self, текст):
        self.беда.setText(текст or "")


class Окно(Фон):
    """Главное окно: слева меню, справа раздел."""

    def __init__(self, клиент=None):
        super().__init__()
        self.setWindowTitle("Pintel — Административное управление")
        self.resize(1280, 820)
        self.клиент = клиент or Клиент(config.сервер(), config.токен())
        self.задачи = []
        self.имя = ""

        self.стопка = QStackedWidget()
        корень = QHBoxLayout(self)
        корень.setContentsMargins(0, 0, 0, 0)
        корень.setSpacing(0)

        self.меню = Меню()
        self.меню.заголовок("Pintel", "Административное управление")
        self.меню.раздел("обзор")
        self.меню.пункт("обзор", "Обзор")
        self.меню.пункт("тревоги", "Требует внимания")
        self.меню.раздел("точки")
        self.меню.пункт("точки", "Точки и кассы")
        self.меню.пункт("компьютеры", "Компьютеры")
        self.меню.раздел("работа")
        self.меню.пункт("люди", "Люди")
        self.меню.растянуть()
        self.кто = надпись("", "muted")
        self.меню.низ(self.кто)
        выход = QPushButton("Выйти")
        выход.setObjectName("тихая")
        выход.clicked.connect(self.выйти)
        self.меню.низ(выход)
        self.меню.выбрали.connect(self.открыть)

        self.разделы = {"обзор": Обзор(), "тревоги": Тревоги(), "точки": Точки(),
                        "компьютеры": Компьютеры(), "люди": Люди()}
        self.вход = Вход(self)
        self.вход.кнопка.clicked.connect(self._войти)
        self.стопка.addWidget(self.вход)
        for р in self.разделы.values():
            self.стопка.addWidget(р)

        корень.addWidget(self.меню)
        корень.addWidget(self.стопка, 1)
        self.меню.setVisible(False)

        self.часы = QTimer(self)
        self.часы.timeout.connect(self.обновить)
        self.часы.setInterval(ОБНОВЛЯТЬ_СЕК * 1000)

        if self.клиент.токен:
            self._после_входа(config.load().get("имя") or "")
        else:
            self.стопка.setCurrentWidget(self.вход)

    # ---------- вход ----------
    def _войти(self):
        логин = self.вход.логин.text().strip()
        пароль = self.вход.пароль.text()
        if not логин or not пароль:
            self.вход.сказать("Введите логин и пароль")
            return
        self.вход.кнопка.setEnabled(False)
        self.вход.сказать("")

        def работа():
            return self.клиент.войти(логин, пароль)

        def готово(итог):
            self.вход.кнопка.setEnabled(True)
            self.вход.пароль.clear()
            config.save(токен=self.клиент.токен, имя=итог.get("имя") or "", сервер=self.клиент.сервер)
            self._после_входа(итог.get("имя") or "")

        def беда(текст):
            self.вход.кнопка.setEnabled(True)
            self.вход.сказать(текст)

        self._в_потоке(работа, готово, беда)

    def _после_входа(self, имя):
        self.имя = имя
        self.кто.setText(имя)
        self.меню.setVisible(True)
        self.меню.выбрать("обзор")
        self.часы.start()
        self.обновить()

    def выйти(self):
        self._в_потоке(self.клиент.выйти, lambda _и: None, lambda _т: None)
        config.забыть_токен()
        self.часы.stop()
        self.меню.setVisible(False)
        self.стопка.setCurrentWidget(self.вход)

    # ---------- разделы ----------
    def открыть(self, ключ):
        раздел = self.разделы.get(ключ)
        if раздел:
            self.стопка.setCurrentWidget(раздел)
            self.обновить(ключ)

    def обновить(self, ключ=None):
        """Спросить у сервера данные открытого раздела."""
        if not self.клиент.токен:
            return
        ключ = ключ or next((к for к, р in self.разделы.items()
                             if р is self.стопка.currentWidget()), None)
        раздел = self.разделы.get(ключ)
        if not раздел:
            return
        работа = {"обзор": self.клиент.обзор, "тревоги": self.клиент.тревоги,
                  "точки": self.клиент.точки, "компьютеры": self.клиент.компьютеры,
                  "люди": self.клиент.люди}[ключ]

        def готово(данные):
            раздел.сказать_беду("")
            раздел.показать(данные)

        def беда(текст):
            раздел.сказать_беду(текст)
            if "войти" in текст:
                self.выйти()

        self._в_потоке(работа, готово, беда)

    def _в_потоке(self, работа, готово, беда):
        з = Задача(работа, self)
        з.готово.connect(готово)
        з.беда.connect(беда)
        self.задачи = [т for т in self.задачи if т.isRunning()] + [з]
        з.start()
        return з

    def closeEvent(self, e):                                     # noqa: N802 — имя от Qt
        self.часы.stop()
        for з in self.задачи:
            з.wait(2000)
        super().closeEvent(e)


def main(argv=None):
    приложение = QApplication(list(argv or sys.argv))
    load_fonts()
    приложение.setStyleSheet(QSS)
    окно = Окно()
    окно.show()
    return приложение.exec()


if __name__ == "__main__":
    sys.exit(main())
