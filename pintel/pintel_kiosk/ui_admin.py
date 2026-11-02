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
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout

from .ui import C, FONT_HEAD, FONT_NUM, Screen, W, font, kicker, label
from .ui_deal import QSS_DEAL, _карточка, _кнопка


class TokenScreen(Screen):
    """Первый запуск: программа ждёт токен точки и ничего больше не умеет."""

    принят = Signal(str)

    def __init__(self):
        super().__init__(gray=True)
        self.setStyleSheet(QSS_DEAL)
        self.root.setContentsMargins(56, 40, 56, 36)
        self.root.addStretch(1)
        карточка, вн = _карточка("ПЕРВЫЙ ЗАПУСК")
        карточка.setMaximumWidth(900)
        вн.addWidget(label("Введите токен точки", font_=font(FONT_HEAD, 40, W.Bold)))
        вн.addWidget(label("Его выдают в кассе: Настройки → Точки → «Выдать токен». Показывается "
                           "он один раз. Больше на этом компьютере настраивать нечего: имя точки, "
                           "бот Оценки, сроки и реквизиты чека придут с сервера.",
                           "muted", wrap=True))
        self.поле = QLineEdit()
        self.поле.setPlaceholderText("pk_…")
        self.поле.setMinimumHeight(64)
        self.поле.returnPressed.connect(self._принять)
        вн.addWidget(self.поле)
        self.ошибка = label("", wrap=True, color=C["badtext"])
        вн.addWidget(self.ошибка)
        ряд = QHBoxLayout()
        ряд.addStretch(1)
        self.кнопка = _кнопка("Сохранить и подключиться")
        self.кнопка.clicked.connect(self._принять)
        ряд.addWidget(self.кнопка)
        вн.addLayout(ряд)
        self.root.addWidget(карточка, 0, Qt.AlignHCenter)
        self.root.addStretch(1)

    def _принять(self):
        токен = self.поле.text().strip()
        if len(токен) < 8:
            self.ошибка.setText("Токен короткий — проверьте, что скопировали его целиком")
            return
        self.ошибка.setText("")
        self.принят.emit(токен)

    def сказать(self, текст, ошибка=True):
        self.ошибка.setText(текст)
        self.ошибка.setStyleSheet(f"color: {C['badtext'] if ошибка else C['ok']}")


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
        пв.addWidget(label("Токен выдают в кассе: Настройки → Точки. Меняют его, когда точку "
                           "перевыпустили или компьютер переставили на другую.", "muted", wrap=True))
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
