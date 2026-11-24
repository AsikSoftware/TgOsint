# -*- coding: utf-8 -*-
"""Сверка деталей с экраном телефона: большой блок с вопросом по каждой детали.

Владелец, 24.11.2026: «не прочитанные по деталям с открытого раздела спрашивать по каждой
детали — один большой блок на передний план, пока не ответит, не пройдёт».

Почему вопрос задаётся по одной детали, а не таблицей сразу: отметка в таблице — это
промах мышью, который потом не видно. Здесь на экране одна деталь, крупно, и пять
ответов словами Apple; предыдущий ответ виден и правится кнопкой «Назад».

Спрашиваем только то, на что ответа нет (`analysis/сверка_деталей.детали`): деталь, про
которую Apple уже высказалась сама, сотруднику не показывается — лишний вопрос это
способ получить случайный ответ.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from pintel_core.analysis import сверка_деталей as сверка_mod
from pintel_core.analysis.parts import APPLE_STATES

from .ui import C, FONT_HEAD, FONT_TEXT, W, font, kicker, label

ЗАГОЛОВОК = "ЧТО НАПИСАНО НА ТЕЛЕФОНЕ"
ПУТЬ = ("Настройки → Основные → Об этом устройстве → «Запчасти и история обслуживания». "
        "Нажмите то, что написано напротив детали. Этот же экран сфотографируйте — "
        "бот попросит его четвёртым фото: без снимка ответы проверить нечем.")
# Порядок ответов: сначала самый частый — у чистого телефона раздел пуст.
КНОПКИ = ("absent", "genuine", "unknown", "used", "serviced")
# Короткие подписи: полные формулировки Apple в кнопку не помещаются, а подсказка под ними
# объясняет каждую словами.
КОРОТКО = {
    "absent": "В списке нет",
    "genuine": "Оригинальная",
    "unknown": "Неизвестная",
    "used": "Была в другом",
    "serviced": "Сервис Apple",
}


def _кнопка_ответа(текст, вид="ghost"):
    from .ui_deal import _кнопка
    b = _кнопка(текст, вид)
    b.setMinimumHeight(64)
    return b


class СверкаДеталей(QWidget):
    """Один вопрос на экране: деталь крупно и пять ответов. → сигнал `ответили`."""

    ответили = Signal(dict)          # {ключ детали: состояние Apple}
    закончили = Signal()             # на все вопросы отвечено

    def __init__(self, parent=None, свой_заголовок=True):
        """`свой_заголовок` — рисовать ли надзаголовок. Там, где карточка уже названа
        «Что написано на телефоне», второй такой же заголовок только мешает."""
        super().__init__(parent)
        self.спросить = []           # [(ключ, имя)] — что ещё не отвечено
        self.ответы = {}
        self.номер = 0               # какой вопрос показываем

        корень = QVBoxLayout(self)
        корень.setContentsMargins(0, 0, 0, 0)
        корень.setSpacing(10)
        if свой_заголовок:
            корень.addWidget(kicker(ЗАГОЛОВОК, 14, 2.0, C["brand"]))
        self.путь = label(ПУТЬ, "muted", wrap=True)
        корень.addWidget(self.путь)
        self.счёт = label("", font_=font(FONT_TEXT, 17, W.Medium), color=C["muted"])
        корень.addWidget(self.счёт)
        self.деталь = label("", wrap=True, font_=font(FONT_HEAD, 40, W.Bold))
        корень.addWidget(self.деталь)
        self.кнопки = {}
        for ключ in КНОПКИ:
            ряд = QHBoxLayout()
            b = _кнопка_ответа(КОРОТКО[ключ], "primary" if ключ == "absent" else "ghost")
            b.clicked.connect(lambda _=False, к=ключ: self._ответ(к))
            self.кнопки[ключ] = b
            ряд.addWidget(b, 3)
            ряд.addWidget(label(APPLE_STATES[ключ][1], "muted", wrap=True), 5)
            корень.addLayout(ряд)
        низ = QHBoxLayout()
        self.b_назад = _кнопка_ответа("Назад", "ghost")
        self.b_назад.clicked.connect(self._назад)
        низ.addWidget(self.b_назад)
        низ.addStretch(1)
        корень.addLayout(низ)
        корень.addStretch(1)

    # ---------- данные ----------
    def показать(self, rep, ответы=None):
        """Какой отчёт сверяем. Вопросы берутся из него же."""
        self.ответы = {k: v for k, v in (ответы or {}).items() if v in APPLE_STATES}
        self.спросить = сверка_mod.детали(rep or {})
        self.номер = min(len(self.ответы), max(len(self.спросить) - 1, 0))
        # первый неотвеченный
        for i, (ключ, _имя) in enumerate(self.спросить):
            if ключ not in self.ответы:
                self.номер = i
                break
        self._нарисовать()

    def осталось(self) -> int:
        """Сколько деталей ещё без ответа. 0 — сверка закончена (или не нужна)."""
        return sum(1 for к, _и in self.спросить if к not in self.ответы)

    def нужна(self, rep) -> bool:
        return bool(сверка_mod.спрашивать_ли(rep or {}))

    def _ответ(self, состояние):
        if not self.спросить or self.номер >= len(self.спросить):
            return
        ключ, _имя = self.спросить[self.номер]
        self.ответы[ключ] = состояние
        self.ответили.emit(dict(self.ответы))
        осталось = [i for i, (к, _и) in enumerate(self.спросить) if к not in self.ответы]
        if not осталось:
            self._нарисовать()
            self.закончили.emit()
            return
        self.номер = осталось[0]
        self._нарисовать()

    def _назад(self):
        if self.номер > 0:
            self.номер -= 1
            self.ответы.pop(self.спросить[self.номер][0], None)
            self.ответили.emit(dict(self.ответы))
            self._нарисовать()

    def _нарисовать(self):
        всего = len(self.спросить)
        if not всего:
            self.деталь.setText("Сверять нечего")
            self.счёт.setText("Apple сказала про все детали сама")
            self.путь.setVisible(False)
            for b in self.кнопки.values():
                b.setVisible(False)
            self.b_назад.setVisible(False)
            return
        отвечено = sum(1 for к, _и in self.спросить if к in self.ответы)
        if отвечено >= всего:
            self.деталь.setText("Сверка закончена")
            self.счёт.setText(f"Отмечено {всего} из {всего}")
            self.путь.setVisible(False)
            for b in self.кнопки.values():
                b.setVisible(False)
            self.b_назад.setVisible(True)
            self.b_назад.setEnabled(True)
            return
        self.путь.setVisible(True)
        ключ, имя = self.спросить[self.номер]
        self.деталь.setText(имя)
        self.счёт.setText(f"Деталь {self.номер + 1} из {всего}"
                          + (f" · отвечено {отвечено}" if отвечено else ""))
        for к, b in self.кнопки.items():
            b.setVisible(True)
            b.setEnabled(True)
            # уже отвеченную деталь показываем с её ответом — видно, что меняешь
            b.setProperty("выбран", self.ответы.get(ключ) == к)
        self.b_назад.setVisible(True)
        self.b_назад.setEnabled(self.номер > 0)
