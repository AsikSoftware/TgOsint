# -*- coding: utf-8 -*-
"""Токен точки и меню администратора.

Программа на точке — внешняя часть: адрес сервера зашит в сборку, всё остальное приходит
с сервера. Единственное, что вводит человек, — токен точки, и вводит он его здесь, а не в
файле настроек. Токен выдают в кассе («Настройки → Точки»), показывают один раз.

Меню администратора открывается сочетанием **Ctrl+Shift+A** — с экрана его не видно, у
стойки стоит клиент. В нём видно, с чем программа работает, и можно сменить токен, если
точку перевыпустили или компьютер переставили на другую.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLineEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .ui import C, FONT_HEAD, FONT_NUM, Screen, W, font, kicker, label
from .ui_deal import QSS_DEAL, _карточка, _кнопка

QSS_ТОЧКИ = """
QPushButton#точка { background: %(field)s; color: %(ink)s; border: 1px solid %(line)s;
    border-radius: 14px; font-size: 21px; font-weight: 700; min-height: 64px;
    padding: 0 20px; text-align: left; }
QPushButton#точка:checked { background: %(tint)s; border-color: %(cyan)s; color: %(ink)s; }
QPushButton#точка:pressed { background: %(card_hi)s; }
""" % C


class TokenScreen(Screen):
    """Первая настройка: выбрать свою точку и ввести её токен.

    Точка — это магазин Оценки, список приходит с сервера с теми же id. Поэтому сделка
    потом несёт готовый `shop_id`, и в боте точку уже не спрашивают."""

    принят = Signal(int, str)                 # id точки, токен
    обновить_список = Signal()

    def __init__(self):
        super().__init__(gray=True)
        self.setStyleSheet(QSS_DEAL + QSS_ТОЧКИ)
        self.root.setContentsMargins(56, 36, 56, 32)
        self.выбрана = None
        self.кнопки = []

        self.root.addWidget(label("Первая настройка", font_=font(FONT_HEAD, 40, W.Bold)))
        self.root.addWidget(label("Выберите свою точку и введите её токен. Остальное придёт с сервера.",
                                  "muted", wrap=True))
        self.root.addSpacing(14)

        тело = QHBoxLayout()
        тело.setSpacing(22)
        слева, лв = _карточка("ТОЧКА")
        прокрутка = QScrollArea()
        прокрутка.setWidgetResizable(True)
        прокрутка.setFrameShape(QFrame.NoFrame)
        внутри = QWidget()
        self.список = QVBoxLayout(внутри)
        self.список.setSpacing(8)
        self.список.addStretch(1)
        прокрутка.setWidget(внутри)
        лв.addWidget(прокрутка, 1)
        тело.addWidget(слева, 3)

        справа, пв = _карточка("ТОКЕН ТОЧКИ")
        self.поле = QLineEdit()
        self.поле.setPlaceholderText("pk_…")
        self.поле.setMinimumHeight(64)
        self.поле.returnPressed.connect(self._принять)
        пв.addWidget(self.поле)
        self.ошибка = label("", wrap=True, color=C["badtext"])
        пв.addWidget(self.ошибка)
        пв.addStretch(1)
        ряд = QHBoxLayout()
        обнов = _кнопка("Обновить список", "ghost")
        обнов.clicked.connect(self.обновить_список.emit)
        ряд.addWidget(обнов)
        ряд.addStretch(1)
        self.кнопка = _кнопка("Подключиться")
        self.кнопка.clicked.connect(self._принять)
        ряд.addWidget(self.кнопка)
        пв.addLayout(ряд)
        тело.addWidget(справа, 2)
        self.root.addLayout(тело, 1)

    def показать_точки(self, точки):
        """Список с сервера → кнопки. Пусто — значит точки ещё не завели."""
        while self.список.count() > 1:
            w = self.список.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self.кнопки = []
        for т in точки or []:
            подпись = f"{т.get('название') or 'без имени'}"
            если_литера = т.get("литера")
            b = QPushButton(подпись + (f"   ·   {если_литера}" if если_литера else ""))
            b.setObjectName("точка")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, точка=т, кнопка=None: self._выбрать(точка))
            self.список.insertWidget(self.список.count() - 1, b)
            self.кнопки.append((b, т))
        if not точки:
            self.список.insertWidget(0, label("Сервер не дал список точек. Проверьте связь или "
                                              "заведите точки в базе: они берутся из магазинов "
                                              "Оценки командой sync-shops.", "muted", wrap=True))

    def _выбрать(self, точка):
        self.выбрана = точка
        for b, т in self.кнопки:
            b.setChecked(т.get("id") == точка.get("id"))
        self.поле.setFocus()

    def _принять(self):
        токен = self.поле.text().strip()
        if not self.выбрана:
            self.сказать("Сначала выберите точку в списке")
            return
        if len(токен) < 6:
            self.сказать("Токен короткий — проверьте, что скопировали его целиком")
            return
        self.сказать("Проверяем…", ошибка=False)
        self.принят.emit(int(self.выбрана.get("id")), токен)

    def сказать(self, текст, ошибка=True):
        self.ошибка.setText(текст)
        self.ошибка.setStyleSheet(f"color: {C['badtext'] if ошибка else C['muted']}")


class AdminScreen(Screen):
    """Меню администратора: Ctrl+Shift+A. Клиент его не видит и случайно не откроет."""

    закрыть = Signal()
    сменить_токен = Signal(str)
    обновить = Signal()

    def __init__(self):
        super().__init__(gray=True)
        self.setStyleSheet(QSS_DEAL)
        self.root.setContentsMargins(56, 40, 56, 36)
        шапка = QHBoxLayout()
        шапка.addWidget(label("Меню администратора", font_=font(FONT_HEAD, 34, W.Bold)), 1)
        назад = _кнопка("Закрыть", "ghost")
        назад.clicked.connect(self.закрыть.emit)
        шапка.addWidget(назад)
        self.root.addLayout(шапка)
        self.root.addSpacing(18)

        тело = QHBoxLayout()
        тело.setSpacing(22)
        левая, лв = _карточка("С ЧЕМ РАБОТАЕМ")
        self.строки = QVBoxLayout()
        лв.addLayout(self.строки)
        лв.addStretch(1)
        тело.addWidget(левая, 1)

        правая, пв = _карточка("ТОКЕН ТОЧКИ")
        пв.addWidget(label("Токен выдают в кассе: Настройки → Точки.", "muted", wrap=True))
        self.поле = QLineEdit()
        self.поле.setPlaceholderText("pk_…")
        self.поле.setMinimumHeight(56)
        пв.addWidget(self.поле)
        self.ответ = label("", wrap=True, color=C["muted"])
        пв.addWidget(self.ответ)
        ряд = QHBoxLayout()
        b = _кнопка("Сменить токен")
        b.clicked.connect(lambda: self.сменить_токен.emit(self.поле.text().strip()))
        ряд.addWidget(b)
        o = _кнопка("Проверить обновление", "ghost")
        o.clicked.connect(self.обновить.emit)
        ряд.addWidget(o)
        ряд.addStretch(1)
        пв.addLayout(ряд)
        пв.addStretch(1)
        тело.addWidget(правая, 1)
        self.root.addLayout(тело, 1)

    def показать(self, сведения: dict):
        while self.строки.count():
            w = self.строки.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for имя, значение in сведения.items():
            ряд = QHBoxLayout()
            ряд.addWidget(label(имя, "muted"), 1)
            ряд.addWidget(label(str(значение), font_=font(FONT_NUM, 20, W.Bold)))
            обёртка = QPushButton()
            обёртка.setFlat(True)
            обёртка.setEnabled(False)
            обёртка.setLayout(ряд)
            обёртка.setStyleSheet("border: none; background: transparent; min-height: 44px;")
            self.строки.addWidget(обёртка)
        self.ответ.setText("")
