# -*- coding: utf-8 -*-
"""Анкета до диагностики: один вопрос — какой телефон принимаем — и клиент.

Это первый экран сделки, до кабеля: так же начинает и продавец в боте Оценки (имя, телефон,
потом состояние телефона). Состояние решает, что будет дальше:

* «Б/у, всё в порядке» — телефон читается кабелем, и если проверка найдёт замену,
  неоригинальную батарею или другой стоп, состояние меняется само
  (ocenka.переклассифицировать) — сделка уйдёт на ручную оценку, а не получит автоцену;
* «Был в ремонте», «Есть дефекты» — та же проверка кабелем, сделка уйдёт на ручную оценку;
* «Новый, запечатан» — кабеля нет: IMEI с коробки → база IMEI (Sickw) → реестр РФС → сделка.
  Поэтому для него здесь же поля IMEI.

Вопрос задан большими плитками с рисунком, а не кнопками с подписью в одну строку: выбор
делают, глядя на клиента и его телефон, и плитку должно быть видно боковым зрением.
"""
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from pintel_core.external import sickw

from .ui import C, FONT_HEAD, FONT_TEXT, Screen, W, font, kicker, label, logo_label, point_text
from .ui_deal import QSS_DEAL, _кнопка, нормальный_телефон

# Порядок — по частоте: обычный б/у встречается чаще всех, запечатанный реже всех.
ПЛИТКИ = (
    ("норма", "Б/у, всё в порядке", "Проверим кабелем — цена сразу"),
    ("дефект", "Есть дефекты", "Сколы, трещины, что-то не работает"),
    ("ремонт", "Был в ремонте", "Меняли экран, батарею или другое"),
    ("новый", "Новый, запечатан", "Коробку не вскрываем — по IMEI"),
)

ПОДСКАЗКИ = {
    "новый": "Кабель не нужен: введите IMEI с коробки — модель, объём и цвет придут из базы.",
    "ремонт": "Подключим кабелем и проверим. Цену назначит оценщик.",
    "дефект": "Подключим кабелем и проверим. Цену назначит оценщик.",
    "норма": "Подключим кабелем и проверим. Найдётся замена или блокировка — состояние изменится само.",
}
ПОДСКАЗКА_ПУСТО = "Выберите состояние телефона и запишите клиента."


def чистый_imei(текст) -> str:
    """Со сканера или с клавиатуры → 15 цифр; пусто — не IMEI."""
    цифры = "".join(ch for ch in str(текст or "") if ch.isdigit())
    return цифры if len(цифры) == 15 and sickw.luhn_ok(цифры) else ""


class Плитка(QPushButton):
    """Один вариант состояния: рисунок, название, строка пояснения.

    Плитка рисуется сама: у кнопки Qt одна строка текста и нет места рисунку. `text()` при
    этом остаётся названием — по нему её читает и тест вёрстки, и программа экранного
    доступа. Выбранная плитка светится и слегка дышит: её видно, не вчитываясь.
    """

    def __init__(self, ключ, заголовок, подпись):
        super().__init__(заголовок)
        self.ключ = ключ
        self.подпись = подпись
        self.setObjectName("выбор")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(font(FONT_HEAD, 27, W.Bold))
        self.setMinimumHeight(250)
        self.t0 = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.update)
        self.toggled.connect(self._выбор)

    def _выбор(self, да):
        self.t0 = time.monotonic()
        if да and self.isVisible():
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        if self.isChecked():
            self.timer.start()

    def _рисунок(self, p, x, y, цвет):
        """Простой штриховой значок 64×64: телефон с отметкой своего состояния."""
        p.setPen(QPen(QColor(цвет), 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        if self.ключ == "новый":                               # коробка с лентой
            p.drawRoundedRect(QRectF(x + 6, y + 18, 52, 40), 6, 6)
            p.drawLine(QPointF(x + 6, y + 31), QPointF(x + 58, y + 31))
            p.drawLine(QPointF(x + 32, y + 18), QPointF(x + 32, y + 58))
            бант = QPainterPath(QPointF(x + 32, y + 18))
            бант.cubicTo(x + 18, y + 2, x + 12, y + 16, x + 32, y + 18)
            бант.cubicTo(x + 52, y + 16, x + 46, y + 2, x + 32, y + 18)
            p.drawPath(бант)
            return
        p.drawRoundedRect(QRectF(x + 15, y + 4, 34, 58), 8, 8)      # телефон
        p.drawLine(QPointF(x + 27, y + 11), QPointF(x + 37, y + 11))
        if self.ключ == "норма":                               # галочка
            галка = QPainterPath(QPointF(x + 23, y + 35))
            галка.lineTo(QPointF(x + 30, y + 42))
            галка.lineTo(QPointF(x + 42, y + 27))
            p.drawPath(галка)
        elif self.ключ == "дефект":                            # трещина
            трещина = QPainterPath(QPointF(x + 38, y + 18))
            for dx, dy in ((29, 28), (36, 34), (26, 45), (33, 53)):
                трещина.lineTo(QPointF(x + dx, y + dy))
            p.drawPath(трещина)
        else:                                                  # ключ: был в ремонте
            p.drawLine(QPointF(x + 25, y + 46), QPointF(x + 36, y + 31))
            p.drawArc(QRectF(x + 31, y + 20, 13, 13), 20 * 16, 250 * 16)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        выбрана = self.isChecked()
        рамка = QRectF(1.5, 1.5, self.width() - 3, self.height() - 3)
        if выбрана:
            пульс = 0.5 + 0.5 * math.sin((time.monotonic() - self.t0) * 2.4)
            ореол = QColor(C["glow"])
            ореол.setAlphaF(0.16 + 0.14 * пульс)
            p.setPen(QPen(ореол, 7))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(рамка.adjusted(2, 2, -2, -2), 24, 24)
        p.setPen(QPen(QColor(C["cyan"] if выбрана else C["line"]), 2 if выбрана else 1))
        фон = QColor(C["tint"] if выбрана else C["card"])
        if self.isDown():
            фон = QColor(C["card_hi"])
        p.setBrush(фон)
        p.drawRoundedRect(рамка.adjusted(4, 4, -4, -4), 22, 22)
        поле = 30
        self._рисунок(p, поле, поле, C["cyan"] if выбрана else C["pale"])
        p.setPen(QColor(C["ink"]))
        p.setFont(self.font())
        p.drawText(QRectF(поле, 112, self.width() - 2 * поле, 44),
                   Qt.AlignLeft | Qt.AlignVCenter, self.text())
        p.setPen(QColor(C["body"] if выбрана else C["muted"]))
        p.setFont(font(FONT_TEXT, 19, W.Medium))
        p.drawText(QRectF(поле, 158, self.width() - 2 * поле, self.height() - 158 - 18),
                   Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self.подпись)


class StartScreen(Screen):
    """Состояние и клиент — до того, как телефон коснётся кабеля."""

    далее = Signal(dict)
    отмена = Signal()

    def __init__(self, point=""):
        super().__init__(gray=True)
        self.setStyleSheet(QSS_DEAL)
        self.root.setContentsMargins(56, 30, 56, 30)
        self.root.setSpacing(0)

        шапка = QHBoxLayout()
        шапка.setSpacing(16)
        шапка.addWidget(logo_label(42))
        шапка.addWidget(label("Новая оценка", font_=font(FONT_HEAD, 26, W.DemiBold)), 1)
        self.точка = label(point_text(point), font_=font(FONT_TEXT, 17, W.Medium), color=C["muted"])
        шапка.addWidget(self.точка)
        self.root.addLayout(шапка)
        self.root.addStretch(2)

        вопрос = label("Какой телефон принимаем?", font_=font(FONT_HEAD, 46, W.Bold))
        вопрос.setAlignment(Qt.AlignHCenter)
        self.root.addWidget(вопрос)
        self.root.addSpacing(8)
        self.подсказка = label(ПОДСКАЗКА_ПУСТО, wrap=True, font_=font(FONT_TEXT, 21, W.Medium),
                               color=C["muted"])
        self.подсказка.setAlignment(Qt.AlignHCenter)
        self.root.addWidget(self.подсказка)
        self.root.addSpacing(30)

        ряд = QHBoxLayout()
        ряд.setSpacing(20)
        self.группа = QButtonGroup(self)
        self.группа.setExclusive(True)
        self.кнопки = {}
        for ключ, заголовок, подпись in ПЛИТКИ:
            b = Плитка(ключ, заголовок, подпись)
            b.toggled.connect(self._проверить)
            self.группа.addButton(b)
            self.кнопки[ключ] = b
            ряд.addWidget(b, 1)
        self.root.addLayout(ряд)
        self.root.addSpacing(34)

        self.root.addWidget(self._клиент(), 0, Qt.AlignHCenter)
        self.root.addStretch(3)

        низ = QHBoxLayout()
        низ.setSpacing(16)
        self.b_отмена = _кнопка("Отменить", "ghost")
        self.b_отмена.clicked.connect(self.отмена.emit)
        self.ошибка = label("", wrap=True, font_=font(FONT_TEXT, 18, W.Medium), color=C["badtext"])
        self.ошибка.setAlignment(Qt.AlignCenter)
        self.b_далее = _кнопка("Далее")
        self.b_далее.clicked.connect(self._далее)
        низ.addWidget(self.b_отмена)
        низ.addWidget(self.ошибка, 1)
        низ.addWidget(self.b_далее)
        self.root.addLayout(низ)
        self.начать()

    def _клиент(self):
        """Клиент — одной строкой под плитками; для запечатанного ниже появляются IMEI."""
        блок = QWidget()
        блок.setFixedWidth(1120)
        сл = QVBoxLayout(блок)
        сл.setContentsMargins(0, 0, 0, 0)
        сл.setSpacing(10)
        сл.addWidget(kicker("КЛИЕНТ", 14, 2.4, C["brand"]))
        ряд = QHBoxLayout()
        ряд.setSpacing(16)
        self.имя = QLineEdit()
        self.имя.setPlaceholderText("Имя клиента")
        self.телефон = QLineEdit()
        self.телефон.setPlaceholderText("+7 7XX XXX XX XX")
        for поле in (self.имя, self.телефон):
            поле.setMinimumHeight(62)
            поле.textChanged.connect(self._проверить)
            ряд.addWidget(поле, 1)
        сл.addLayout(ряд)

        # IMEI — только для запечатанного: кабеля нет, аппарат узнаём по коробке
        self.imei_блок = QWidget()
        бл = QVBoxLayout(self.imei_блок)
        бл.setContentsMargins(0, 12, 0, 0)
        бл.setSpacing(10)
        бл.addWidget(kicker("IMEI С КОРОБКИ", 14, 2.4, C["brand"]))
        ряд_imei = QHBoxLayout()
        ряд_imei.setSpacing(16)
        self.imei1 = QLineEdit()
        self.imei1.setPlaceholderText("IMEI — 15 цифр")
        self.imei2 = QLineEdit()
        self.imei2.setPlaceholderText("IMEI 2 — если есть на коробке")
        for поле in (self.imei1, self.imei2):
            поле.setMaxLength(20)
            поле.setMinimumHeight(62)
            поле.textChanged.connect(self._проверить)
            ряд_imei.addWidget(поле, 1)
        бл.addLayout(ряд_imei)
        бл.addWidget(label("Отсканируйте штрихкод коробки или наберите цифры.", "muted", wrap=True))
        сл.addWidget(self.imei_блок)
        return блок

    # ---------- состояния ----------
    def начать(self):
        self.группа.setExclusive(False)
        for b in self.кнопки.values():
            b.setChecked(False)
        self.группа.setExclusive(True)
        for поле in (self.имя, self.телефон, self.imei1, self.imei2):
            поле.clear()
        self.ошибка.setText("")
        self.подсказка.setText(ПОДСКАЗКА_ПУСТО)
        self.imei_блок.setVisible(False)
        self.b_далее.setText("Далее")
        self._проверить()
        self.имя.setFocus()

    def set_point(self, point):
        self.точка.setText(point_text(point))

    def состояние(self):
        for ключ, b in self.кнопки.items():
            if b.isChecked():
                return ключ
        return None

    # ---------- данные ----------
    def данные(self):
        имеи = [чистый_imei(self.imei1.text()), чистый_imei(self.imei2.text())]
        return {"состояние": self.состояние(), "имя": self.имя.text().strip(),
                "телефон": нормальный_телефон(self.телефон.text()),
                "imei": [x for x in имеи if x]}

    def _чего_не_хватает(self):
        d = self.данные()
        нет = []
        if not d["состояние"]:
            нет.append("состояние телефона")
        if not d["имя"]:
            нет.append("имя клиента")
        if not d["телефон"]:
            нет.append("телефон клиента")
        if d["состояние"] == "новый":
            if not чистый_imei(self.imei1.text()):
                нет.append("IMEI с коробки (15 цифр)")
            if self.imei2.text().strip() and not чистый_imei(self.imei2.text()):
                нет.append("второй IMEI набран неверно")
        return нет

    def _пометить(self, поле, плохо):
        поле.setProperty("плохо", "да" if плохо else "нет")
        поле.style().unpolish(поле)
        поле.style().polish(поле)

    def _проверить(self, *_):
        с = self.состояние()
        self.imei_блок.setVisible(с == "новый")
        self.подсказка.setText(ПОДСКАЗКИ.get(с) or ПОДСКАЗКА_ПУСТО)
        self.b_далее.setText("Далее: IMEI → база → Оценка" if с == "новый"
                             else ("Далее: подключить телефон" if с else "Далее"))
        self._пометить(self.телефон, bool(self.телефон.text().strip() and not нормальный_телефон(self.телефон.text())))
        self._пометить(self.imei1, bool(self.imei1.text().strip() and not чистый_imei(self.imei1.text())))
        self._пометить(self.imei2, bool(self.imei2.text().strip() and not чистый_imei(self.imei2.text())))
        годно = not self._чего_не_хватает()
        self.b_далее.setEnabled(годно)
        return годно

    def _далее(self):
        нет = self._чего_не_хватает()
        if нет:
            self.ошибка.setText("Не хватает: " + ", ".join(нет))
            return
        self.ошибка.setText("")
        self.далее.emit(self.данные())
