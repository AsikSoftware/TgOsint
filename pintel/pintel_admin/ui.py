# -*- coding: utf-8 -*-
"""Облик административной программы: стекло, как у маковской кассы.

Цвета, шрифты и материал берутся из кассы (`pintel_kiosk.ui`) намеренно: это одна программа
для одного дела, и две разные палитры означали бы, что где-то цифра «выкуплено» выглядит
по-разному. Здесь только то, чего у кассы нет: боковое меню, карточка с таблицей, плитка с
крупным числом — экран владельца это таблицы и числа, а не шаги сделки.

Размеры не как на кассе: там экран видит клиент через стойку и всё крупное, здесь человек
сидит перед маком.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from pintel_kiosk.ui import C, FONT_HEAD, FONT_NUM, FONT_TEXT, W, аврора, font, load_fonts

# Материал окна: на маке стекло, на остальных системах — те же цвета без прозрачности.
СТЕКЛО = __import__("sys").platform == "darwin"
_ЗАЛИВКА = ("qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255,255,255,0.74), "
            "stop:1 rgba(255,255,255,0.52))") if СТЕКЛО else C["card"]
_КРАЙ = "rgba(255,255,255,0.88)" if СТЕКЛО else C["border"]
_МЕНЮ = "rgba(255,255,255,0.55)" if СТЕКЛО else C["screen"]

QSS = """
QWidget { color: %(ink)s; font-size: 13.5px; }
QLabel#h1 { font-size: 25px; font-weight: 700; letter-spacing: -0.3px; }
QLabel#sub { font-size: 13px; color: %(muted)s; font-weight: 500; }
QLabel#kicker { font-size: 10.5px; font-weight: 700; color: %(brand)s; letter-spacing: 1.4px; }
QLabel#подпись { font-size: 10.5px; font-weight: 700; color: %(muted)s; letter-spacing: 1.4px; }
QLabel#число { font-size: 30px; font-weight: 700; letter-spacing: -1px; }
QLabel#muted { font-size: 12.5px; color: %(muted)s; font-weight: 500; }
QLabel#имя { font-size: 15px; font-weight: 700; }
QFrame#карта { background: %(заливка)s; border: 1px solid %(край)s; border-radius: 18px; }
QFrame#меню { background: %(меню)s; border-right: 1px solid %(край)s; }
QPushButton#пункт { text-align: left; padding: 8px 12px; border-radius: 11px; border: none;
    background: transparent; font-size: 14px; font-weight: 500; color: %(body)s; }
QPushButton#пункт:hover { background: rgba(255,255,255,0.65); }
QPushButton#пункт:checked { background: #FFFFFF; color: %(ink)s; font-weight: 700; }
QPushButton#главная { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1A7CFF, stop:1 #35B2FF);
    color: #fff; border: none; border-radius: 12px; font-size: 14px; font-weight: 700;
    min-height: 38px; padding: 0 18px; }
QPushButton#главная:disabled { background: #E9EEF6; color: %(ghost)s; }
QPushButton#тихая { background: rgba(255,255,255,0.6); border: 1px solid %(край)s;
    border-radius: 11px; font-size: 13px; font-weight: 600; min-height: 32px; padding: 0 14px; }
QLineEdit { background: rgba(255,255,255,0.8); border: 1px solid %(line)s; border-radius: 11px;
    padding: 9px 12px; font-size: 14px; }
QLineEdit:focus { border-color: %(action)s; }
QTableWidget { background: transparent; border: none; gridline-color: transparent;
    selection-background-color: %(tint)s; selection-color: %(ink)s; }
QHeaderView::section { background: transparent; border: none; color: %(ghost)s;
    font-size: 11px; font-weight: 700; padding: 0 8px 8px; }
QTableWidget::item { padding: 7px 8px; border-bottom: 1px solid rgba(11,27,51,0.07);
    font-size: 13.5px; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: %(ring)s; border-radius: 5px; min-height: 40px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
""" % {**C, "заливка": _ЗАЛИВКА, "край": _КРАЙ, "меню": _МЕНЮ}


def тень(виджет, размытие=28, вниз=6, альфа=32):
    """Мягкая тень под карточкой: у прозрачной карточки нет своей заливки, и без тени она
    не отделяется от фона."""
    if not СТЕКЛО:
        return виджет
    эффект = QGraphicsDropShadowEffect(виджет)
    эффект.setBlurRadius(размытие)
    эффект.setOffset(0, вниз)
    эффект.setColor(QColor(11, 27, 51, альфа))
    виджет.setGraphicsEffect(эффект)
    return виджет


def надпись(текст="", вид="", шрифт=None, цвет=None, перенос=False) -> QLabel:
    l = QLabel(текст)
    if вид:
        l.setObjectName(вид)
    if шрифт:
        l.setFont(шрифт)
    if цвет:
        l.setStyleSheet(f"color: {цвет};")
    l.setWordWrap(перенос)
    return l


class Карта(QFrame):
    """Карточка со стеклянной заливкой и надзаголовком. Внутрь кладут что угодно."""

    def __init__(self, заголовок="", parent=None):
        super().__init__(parent)
        self.setObjectName("карта")
        тень(self)
        self.внутри = QVBoxLayout(self)
        self.внутри.setContentsMargins(16, 14, 16, 14)
        self.внутри.setSpacing(10)
        if заголовок:
            self.внутри.addWidget(надпись(заголовок.upper(), "kicker"))

    def добавить(self, виджет):
        self.внутри.addWidget(виджет)
        return виджет


class Плитка(Карта):
    """Крупное число с подписью: «проверено телефонов — 47».

    Пусто вместо нуля — осознанно: `None` показывается прочерком. Ноль вместо «не знаем» на
    экране владельца это ложь, по которой принимают решения."""

    def __init__(self, подпись: str, parent=None):
        super().__init__("", parent)
        self.внутри.setSpacing(2)
        self.подпись = надпись(подпись.upper(), "подпись")
        self.значение = надпись("—", "число", шрифт=font(FONT_NUM, 30, W.Bold))
        self.пояснение = надпись("", "muted")
        for w in (self.подпись, self.значение, self.пояснение):
            self.внутри.addWidget(w)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def показать(self, значение, пояснение="", цвет=None):
        self.значение.setText(деньги(значение) if isinstance(значение, (int, float)) else
                              (str(значение) if значение not in (None, "") else "—"))
        self.значение.setStyleSheet(f"color: {цвет};" if цвет else "")
        self.пояснение.setText(пояснение or "")


class Меню(QFrame):
    """Боковое меню. Пункты — кнопки-переключатели, выбран всегда ровно один."""

    выбрали = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("меню")
        self.setFixedWidth(244)
        self.кнопки = {}
        # Пунктов полтора десятка, и на невысоком экране они выдавливали заголовок за край.
        # Поэтому список прокручивается, а шапка и низ стоят на месте.
        from PySide6.QtWidgets import QScrollArea
        внешний = QVBoxLayout(self)
        внешний.setContentsMargins(12, 14, 12, 12)
        внешний.setSpacing(6)
        self._шапка = QVBoxLayout()
        self._шапка.setSpacing(0)
        внешний.addLayout(self._шапка)
        прокрутка = QScrollArea()
        прокрутка.setWidgetResizable(True)
        прокрутка.setFrameShape(QScrollArea.NoFrame)
        прокрутка.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        внутри = QWidget()
        self._слой = QVBoxLayout(внутри)
        self._слой.setContentsMargins(0, 0, 4, 0)
        self._слой.setSpacing(2)
        прокрутка.setWidget(внутри)
        внешний.addWidget(прокрутка, 1)
        self._низ = QVBoxLayout()
        self._низ.setSpacing(4)
        внешний.addLayout(self._низ)

    def заголовок(self, текст, подпись=""):
        шапка = QVBoxLayout()
        шапка.setSpacing(0)
        шапка.addWidget(надпись(текст, "имя"))
        if подпись:
            шапка.addWidget(надпись(подпись, "muted", перенос=True))
        обёртка = QWidget()
        обёртка.setLayout(шапка)
        обёртка.setContentsMargins(4, 0, 0, 6)
        self._шапка.addWidget(обёртка)

    def раздел(self, текст):
        l = надпись(текст.upper(), "kicker", цвет=C["ghost"])
        l.setContentsMargins(8, 10, 0, 2)
        self._слой.addWidget(l)

    def пункт(self, ключ, текст):
        b = QPushButton(текст)
        b.setObjectName("пункт")
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda _=False, к=ключ: self.выбрать(к))
        self.кнопки[ключ] = b
        self._слой.addWidget(b)
        return b

    def растянуть(self):
        self._слой.addStretch(1)

    def низ(self, виджет):
        self._низ.addWidget(виджет)

    def выбрать(self, ключ):
        for к, b in self.кнопки.items():
            b.setChecked(к == ключ)
        self.выбрали.emit(ключ)


class Фон(QWidget):
    """Окно рисует световой фон само: сквозь карточки должно быть ВИДНО, что за ними."""

    def paintEvent(self, e):                                     # noqa: N802 — имя от Qt
        from PySide6.QtGui import QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(self.rect(), аврора(t=2.4, сила=0.5))


# ---------------------------------------------------------------- числа словами


def деньги(сумма) -> str:
    """125000 → «125 000». Пусто — прочерк: «0 ₸» там, где данных нет, это неправда."""
    if сумма in (None, ""):
        return "—"
    try:
        ц = int(сумма)
    except (TypeError, ValueError):
        return str(сумма)
    return f"{ц:,}".replace(",", " ")


def миллионы(сумма) -> str:
    """Крупные деньги короче: 3 240 000 → «3,24 млн». Владелец смотрит на порядок, а не на рубли."""
    if сумма in (None, ""):
        return "—"
    ц = int(сумма)
    if ц < 1_000_000:
        return деньги(ц)
    return f"{ц / 1_000_000:.2f}".replace(".", ",") + " млн"


def давно(часов) -> str:
    """Сколько времени назад это было, словами."""
    if часов is None:
        return "не выходила на связь"
    if часов < 0.05:
        return "только что"
    if часов < 1:
        return f"{int(часов * 60)} мин назад"
    if часов < 24:
        return f"{часов:.0f} ч назад".replace(".0", "")
    return f"{int(часов // 24)} дн назад"


__all__ = ["QSS", "Карта", "Меню", "Плитка", "Фон", "деньги", "миллионы", "давно", "надпись",
           "тень", "load_fonts", "C", "FONT_HEAD", "FONT_NUM", "FONT_TEXT", "W", "font"]
