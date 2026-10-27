# -*- coding: utf-8 -*-
"""Экраны киоска по утверждённому концепту (1920×1080, масштабируется целиком).

Шрифты: Inter — текст, Inter Display — заголовки (в них есть кириллица),
Space Grotesk — крупные цифры и латинские названия моделей (кириллицы в нём нет).
Анимации лёгкие, на таймерах и только пока виджет виден: бесконечные — на экране
ожидания (телефон, кольца, кабель, мигающая точка), одноразовые — на результате
(заполнение батареи, появление номера и QR).
"""
import math
import os
import time

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
C = {
    "ink": "#0C1A2E", "body": "#3B4F6B", "muted": "#5B7392", "brand": "#16417A",
    "action": "#2E6BE6", "action_dark": "#1D4ED8", "tint": "#EAF1FD", "tint_border": "#D7E4F6",
    "ground": "#F5F8FC", "border": "#E3EAF3", "screen": "#13325B",
    "ok": "#15724C", "okdot": "#1E9E6A", "okbg": "#E6F6EE",
    "warn": "#D98B1E", "warntext": "#9A5B07", "warnbg": "#FFF3D6",
    "bad": "#D64541", "badtext": "#B3261E", "badbg": "#FCE9E8",
    "pale": "#AFCBEC", "ring": "#C9D5E3", "ghost": "#C3CEDB",
}
FONT_TEXT, FONT_HEAD, FONT_NUM = "Inter", "Inter Display", "Space Grotesk"
W = QFont.Weight

# Шрифты в QSS только размер/насыщенность: семейство приходит от шрифта приложения (Inter),
# а заголовки и кикеры с межбуквенным интервалом задаются кодом (QSS его не умеет).
QSS = """
QWidget { color: %(ink)s; }
QWidget#screen { background: #FFFFFF; }
QWidget#screen_gray { background: %(ground)s; }
QLabel#lead { font-size: 30px; font-weight: 500; color: %(body)s; }
QLabel#lead_s { font-size: 24px; font-weight: 500; color: %(body)s; }
QLabel#muted { font-size: 19px; font-weight: 600; color: %(muted)s; }
QLabel#step { font-size: 28px; font-weight: 600; }
QLabel#num { background: %(action)s; color: white; border-radius: 16px; min-width: 58px; max-width: 58px; min-height: 58px; max-height: 58px; }
QLabel#cardtext { font-size: 20px; font-weight: 400; color: %(body)s; }
QLabel#cardstatus { font-size: 20px; font-weight: 700; color: %(brand)s; }
QFrame#row { background: %(ground)s; border-radius: 18px; }
QFrame#row_active { background: %(tint)s; border: 2px solid %(action)s; border-radius: 18px; }
QLabel#rowtitle { font-size: 24px; font-weight: 700; }
QLabel#rowtitle_wait { font-size: 24px; font-weight: 700; color: %(body)s; }
QLabel#rowstate { font-size: 19px; font-weight: 600; color: %(muted)s; }
QLabel#rowstate_active { font-size: 19px; font-weight: 700; color: %(action)s; }
QFrame#bluecard { background: qlineargradient(x1:0, y1:0, x2:0.45, y2:1, stop:0 #1F5FB0, stop:1 #13325B); border-radius: 36px; }
QLabel#bluestep { font-size: 23px; font-weight: 500; color: white; }
QLabel#bluenote { font-size: 20px; font-weight: 500; color: #DCE8F5; background: rgba(255,255,255,0.12); border-radius: 16px; padding: 18px 22px; }
QPushButton#skip { font-size: 20px; font-weight: 700; color: %(pale)s; background: transparent; border: 2px solid %(pale)s; border-radius: 14px; padding: 14px 26px; }
QPushButton#skip:pressed { background: rgba(255,255,255,0.12); }
QFrame#card { background: white; border: 1px solid %(border)s; border-radius: 24px; }
QFrame#card_main { background: white; border: 1px solid %(border)s; border-radius: 28px; }
QLabel#line { font-size: 22px; font-weight: 600; }
QLabel#line_s { font-size: 21px; font-weight: 600; }
QLabel#note { font-size: 19px; font-weight: 400; color: %(muted)s; }
QLabel#qrtext { font-size: 23px; font-weight: 500; color: %(body)s; }
QLabel#kv_k { font-size: 19px; font-weight: 400; color: %(muted)s; }
QLabel#kv_v { font-size: 19px; font-weight: 700; }
QLabel#chip_ok { background: %(okbg)s; color: %(ok)s; border-radius: 26px; padding: 12px 24px; font-size: 22px; font-weight: 700; }
QLabel#chip_warn { background: %(warnbg)s; color: %(warntext)s; border-radius: 26px; padding: 12px 24px; font-size: 22px; font-weight: 700; }
QLabel#chip_bad { background: %(badbg)s; color: %(badtext)s; border-radius: 26px; padding: 12px 24px; font-size: 22px; font-weight: 700; }
QPushButton#primary { background: %(action)s; color: white; border-radius: 20px; font-size: 28px; font-weight: 700; min-height: 80px; border: none; }
QPushButton#primary:pressed { background: %(action_dark)s; }
QLabel#footer { font-size: 18px; font-weight: 500; color: %(muted)s; }
""" % C


def load_fonts():
    """Статические начертания (Qt не выбирает насечку у вариативных шрифтов)."""
    d = os.path.join(ASSETS, "fonts")
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if name.endswith(".ttf"):
                QFontDatabase.addApplicationFont(os.path.join(d, name))


def app_font():
    f = QFont(FONT_TEXT)
    f.setPixelSize(16)
    return f


def font(family=FONT_TEXT, px=16, weight=W.Normal, spacing=None):
    f = QFont(family)
    f.setPixelSize(px)
    f.setWeight(weight)
    if spacing is not None:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def label(text, name=None, wrap=False, font_=None, color=None):
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    if font_ is not None:
        lab.setFont(font_)
    if color:
        lab.setStyleSheet(f"color: {color};")
    return lab


def kicker(text, px=14, spacing=2.0, color=None):
    """Надзаголовок капителью: «ВАШ НОМЕР», «БАТАРЕЯ»…"""
    return label(text, font_=font(FONT_TEXT, px, W.Bold, spacing), color=color or C["muted"])


def ease_out():
    """cubic-bezier(.2,.8,.2,1) из макета."""
    c = QEasingCurve(QEasingCurve.Type.BezierSpline)
    c.addCubicBezierSegment(QPointF(0.2, 0.8), QPointF(0.2, 1.0), QPointF(1.0, 1.0))
    return c


def smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def logo_label(height=44):
    lab = QLabel()
    p = os.path.join(ASSETS, "logo.png")
    if os.path.isfile(p):
        lab.setPixmap(QPixmap(p).scaledToHeight(height, Qt.SmoothTransformation))
    else:
        lab.setText("PINTEL")
    return lab


def point_text(point):
    return f"Выкуп iPhone · {point}" if point else "Выкуп iPhone"


def header(point_label, right=None):
    row = QHBoxLayout()
    row.setSpacing(14)
    row.addWidget(logo_label())
    row.addWidget(point_label)
    row.addStretch(1)
    if right is not None:
        row.addWidget(right)
    return row


def status_label(text, ok=True):
    return label(("● " if ok else "○ ") + text, font_=font(FONT_TEXT, 19, W.DemiBold),
                 color=C["okdot"] if ok else C["muted"])


# ---------- анимированные примитивы ----------

class Pulse(QWidget):
    """Точка статуса 12 px: мигает (1 → 0.2 → 1 за 1,4 с) или горит ровно."""

    def __init__(self, color, blink=True):
        super().__init__()
        self.setFixedSize(12, 12)
        self.color = QColor(color)
        self.blink = blink
        self.t0 = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.update)

    def set(self, color, blink):
        self.color = QColor(color)
        self.blink = blink
        if blink and self.isVisible():
            self.timer.start()
        elif not blink:
            self.timer.stop()
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        if self.blink:
            self.timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(self.color)
        if self.blink:
            t = time.monotonic() - self.t0
            col.setAlphaF(0.2 + 0.8 * (0.5 + 0.5 * math.cos(2 * math.pi * t / 1.4)))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QRectF(0, 0, 12, 12))


class Dot(QWidget):
    """Индикатор шага проверки: ждёт, крутится, готово, внимание, ошибка."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(42, 42)
        self.state = "wait"
        self.t0 = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.update)

    def set_state(self, state):
        self.state = state
        if state == "run" and self.isVisible():
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        if self.state == "run":
            self.timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(2.5, 2.5, 37, 37)
        p.setBrush(Qt.NoBrush)
        if self.state == "wait":
            p.setPen(QPen(QColor(C["ring"]), 3))
            p.drawEllipse(r)
        elif self.state == "run":
            faint = QColor(C["action"])
            faint.setAlphaF(0.22)
            p.setPen(QPen(faint, 4))
            p.drawEllipse(r)
            p.setPen(QPen(QColor(C["action"]), 4, Qt.SolidLine, Qt.RoundCap))
            ang = int((time.monotonic() - self.t0) * 300) % 360          # оборот за 1,2 с
            p.drawArc(r, (90 - ang) * 16, -110 * 16)
        else:
            col = {"done": C["okdot"], "warn": C["warn"], "fail": C["bad"]}.get(self.state, C["okdot"])
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawEllipse(QRectF(0, 0, 42, 42))
            p.setPen(QPen(QColor("white"), 3.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            if self.state == "done":
                path = QPainterPath(QPointF(13, 21.5))
                path.lineTo(QPointF(18.5, 27))
                path.lineTo(QPointF(29.5, 15.5))
                p.drawPath(path)
            elif self.state == "fail":
                p.drawLine(QPointF(15, 15), QPointF(27, 27))
                p.drawLine(QPointF(27, 15), QPointF(15, 27))
            else:
                p.drawLine(QPointF(21, 12), QPointF(21, 24))
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("white"))
                p.drawEllipse(QPointF(21, 30.5), 2.3, 2.3)


class ConnectArt(QWidget):
    """Телефон, кабель и расходящиеся кольца — как в макете. Рисуется в своих 240×410
    (хвост кабеля уходит за нижний край) и масштабируется под отведённое место;
    анимация идёт только пока виджет виден."""
    AW, AH = 240, 410
    PW, PH = 188, 330

    def __init__(self):
        super().__init__()
        self.setMinimumSize(120, 200)
        self.state = "wait"
        self.t0 = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.update)

    def set_state(self, state):
        self.state = state
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self.t0 = time.monotonic()
        self.timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    def paintEvent(self, e):
        t = time.monotonic() - self.t0
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        k = min(self.width() / self.AW, self.height() / self.AH)
        p.translate((self.width() - self.AW * k) / 2, (self.height() - self.AH * k) / 2)
        p.scale(k, k)
        # парение всей группы: 0 → −10 px → 0 за 4,5 с
        p.translate(0, -10 * (0.5 - 0.5 * math.cos(2 * math.pi * t / 4.5)))
        ox, oy = (self.AW - self.PW) / 2, 8
        cx = ox + self.PW / 2
        base = oy + self.PH - 6                                           # верх нижнего блока
        # кольца — только пока ждём кабель
        if self.state == "wait":
            for delay in (0.0, 0.9):
                if t < delay:
                    continue
                u = ((t - delay) % 2.2) / 2.2
                ue = 1 - (1 - u) ** 2
                col = QColor(C["action"])
                col.setAlphaF(0.95 * (1 - ue))
                p.setPen(QPen(col, 3))
                p.setBrush(Qt.NoBrush)
                rr = 30 * (0.55 + 1.35 * ue)
                p.drawEllipse(QPointF(cx, base + 12), rr, rr)
        # тень телефона: несколько полупрозрачных слоёв
        p.setPen(Qt.NoPen)
        for i in range(8):
            sh = QColor(C["ink"])
            sh.setAlphaF(0.035)
            p.setBrush(sh)
            g = i * 5
            p.drawRoundedRect(QRectF(ox - g, oy + 22 - g, self.PW + 2 * g, self.PH + 2 * g), 34 + g, 34 + g)
        # телефон
        p.setBrush(QColor(C["ink"]))
        p.drawRoundedRect(QRectF(ox, oy, self.PW, self.PH), 34, 34)
        p.setBrush(QColor(C["screen"]))
        p.drawRoundedRect(QRectF(ox + 9, oy + 9, 170, 312), 27, 27)
        p.setBrush(QColor(C["ink"]))
        p.drawRoundedRect(QRectF(ox + 59, oy + 20, 70, 18), 9, 9)
        p.setBrush(QColor(255, 255, 255, 46))
        p.drawRoundedRect(QRectF(ox + 40, oy + 120, 108, 12), 6, 6)
        p.setBrush(QColor(255, 255, 255, 31))
        p.drawRoundedRect(QRectF(ox + 54, oy + 146, 80, 12), 6, 6)
        p.setBrush(QColor("#0A1526"))
        p.drawRoundedRect(QRectF(ox + 76, oy + 314, 36, 9), 5, 5)
        # кабель: снизу вверх в разъём, пауза, снова
        if self.state == "found":
            dy, a = 0.0, 1.0
        elif self.state == "nodriver":
            dy, a = 84.0, 0.3
        else:
            u = (t % 3.4) / 3.4
            kk = 0.0 if u < 0.12 else (smoothstep((u - 0.12) / 0.28) if u < 0.40 else 1.0)
            dy, a = 84 * (1 - kk), kk
        if a > 0:
            p.setOpacity(a)
            p.setBrush(QColor(C["action"]))
            head = QPainterPath()
            head.addRoundedRect(QRectF(cx - 17, base + 2 + dy, 34, 22), 6, 6)
            p.drawPath(head)
            p.drawRoundedRect(QRectF(cx - 4, base + 22 + dy, 8, 100), 4, 4)
            p.setOpacity(1.0)


class Bar(QWidget):
    """Полоска батареи. Заполняется один раз после показа экрана (1,6 с, задержка 0,35 с)."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(12)
        self.value, self.progress, self.color = 0, 1.0, QColor(C["okdot"])
        self.pending = False
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(1600)
        self.anim.setEasingCurve(ease_out())
        self.anim.valueChanged.connect(self._step)

    def prepare(self, value, color, animate):
        self.value, self.color = max(0, min(100, value or 0)), QColor(color)
        self.pending = bool(animate)
        self.progress = 0.0 if animate else 1.0
        self.update()

    def play(self):
        if self.pending:
            self.pending = False
            QTimer.singleShot(350, self.anim.start)

    def _step(self, v):
        self.progress = float(v)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["border"]))
        p.drawRoundedRect(QRectF(0, 0, self.width(), 12), 6, 6)
        w = self.width() * self.value / 100 * self.progress
        if w > 0:
            p.setBrush(self.color)
            p.drawRoundedRect(QRectF(0, 0, max(w, 12), 12), 6, 6)


class PopNumber(QWidget):
    """Номер заявки 150 px (Space Grotesk). «—» серым, пока номера нет; номер появляется
    один раз с лёгким подскоком (0,55 → 1,06 → 1 за 0,9 с)."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(150)
        self.setMinimumWidth(320)
        self.text, self.color = "—", QColor(C["ghost"])
        self.scale_, self.alpha, self.pending = 1.0, 1.0, False
        self.font_ = font(FONT_NUM, 150, W.Bold)
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(900)
        self.anim.setEasingCurve(ease_out())
        self.anim.valueChanged.connect(self._step)

    def set_text(self, text, number, pop):
        self.text = text
        self.color = QColor(C["brand"] if number else C["ghost"])
        self.pending = bool(pop)
        self.scale_, self.alpha = (0.55, 0.0) if pop else (1.0, 1.0)
        self.update()

    def play(self):
        if self.pending:
            self.pending = False
            QTimer.singleShot(200, self.anim.start)

    def _step(self, v):
        v = float(v)
        if v < 0.6:
            k = v / 0.6
            self.scale_, self.alpha = 0.55 + 0.51 * k, k
        else:
            self.scale_, self.alpha = 1.06 - 0.06 * (v - 0.6) / 0.4, 1.0
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setOpacity(self.alpha)
        h = self.height()
        p.translate(0, h / 2)
        p.scale(self.scale_, self.scale_)
        p.translate(0, -h / 2)
        p.setFont(self.font_)
        p.setPen(self.color)
        p.drawText(QRectF(0, 0, self.width() / max(self.scale_, 0.01), h), Qt.AlignLeft | Qt.AlignVCenter, self.text)


class QrBlock(QWidget):
    """QR 200×200 в белой рамке с подписью. Умеет один раз «всплыть» снизу (0,7 с, задержка 0,6 с)."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(216, 246)
        self.pm, self.caption = None, ""
        self.dy, self.alpha, self.pending = 0.0, 1.0, False
        self.font_ = font(FONT_TEXT, 14, W.Bold, 2.0)
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(700)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._step)

    def set(self, pm, caption, rise):
        self.pm = pm.scaled(200, 200, Qt.KeepAspectRatio, Qt.FastTransformation) if pm else None
        self.caption = caption
        self.pending = bool(rise)
        self.dy, self.alpha = (18.0, 0.0) if rise else (0.0, 1.0)
        self.setVisible(self.pm is not None)
        self.update()

    def play(self):
        if self.pending:
            self.pending = False
            QTimer.singleShot(600, self.anim.start)

    def _step(self, v):
        v = float(v)
        self.dy, self.alpha = 18 * (1 - v), v
        self.update()

    def paintEvent(self, e):
        if self.pm is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self.alpha)
        p.translate(0, self.dy)
        p.setPen(QPen(QColor(C["border"]), 1))
        p.setBrush(QColor("white"))
        p.drawRoundedRect(QRectF(0.5, 0.5, 215, 215), 18, 18)
        p.drawPixmap(8 + (200 - self.pm.width()) // 2, 8 + (200 - self.pm.height()) // 2, self.pm)
        p.setFont(self.font_)
        p.setPen(QColor(C["muted"]))
        p.drawText(QRectF(0, 224, 216, 20), Qt.AlignHCenter | Qt.AlignVCenter, self.caption)


# ---------- каркас ----------

class Screen(QWidget):
    def __init__(self, gray=False, margins=(88, 72, 88, 72), spacing=24):
        super().__init__()
        self.setObjectName("screen_gray" if gray else "screen")
        self.setAutoFillBackground(True)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(*margins)
        self.root.setSpacing(spacing)


# ---------- 1. Ожидание ----------

class MainScreen(Screen):
    def __init__(self, point=""):
        super().__init__()
        self.point_label = label(point_text(point), "muted")
        self.status = status_label("Готов к работе")
        self.root.addLayout(header(self.point_label, self.status))
        body = QHBoxLayout()
        body.setSpacing(88)
        left = QVBoxLayout()
        left.setSpacing(0)
        left.addStretch(1)
        left.addWidget(label("Узнайте, сколько стоит ваш iPhone", wrap=True, font_=font(FONT_HEAD, 78, W.Bold, -1.5)))
        left.addSpacing(28)
        lead = label("Подключите телефон кабелем. Через пару минут увидите состояние, а цену назовёт сотрудник.",
                     "lead", wrap=True)
        lead.setMaximumWidth(760)
        left.addWidget(lead)
        left.addSpacing(48)
        steps = ("Подключите iPhone", "Разблокируйте и нажмите «Доверять»", "Получите отчёт — остальное у сотрудника")
        for i, t in enumerate(steps, 1):
            r = QHBoxLayout()
            r.setSpacing(22)
            n = label(str(i), "num", font_=font(FONT_NUM, 26, W.Bold))
            n.setAlignment(Qt.AlignCenter)
            r.addWidget(n)
            r.addWidget(label(t, "step"))
            r.addStretch(1)
            left.addLayout(r)
            if i < len(steps):
                left.addSpacing(22)
        left.addStretch(1)
        body.addLayout(left, 1)
        self.card = ConnectCard()
        body.addWidget(self.card, 0, Qt.AlignVCenter)
        self.root.addLayout(body, 1)
        self.root.addWidget(label("Ничего не устанавливаем. Данные читаем только с вашего согласия.", "footer"))

    def set_point(self, point):
        self.point_label.setText(point_text(point))

    def set_status(self, text, ok=True):
        self.status.setText(("● " if ok else "○ ") + text)
        self.status.setStyleSheet(f"color: {C['okdot'] if ok else C['bad']};")

    def set_device(self, state):
        """wait | found | nodriver — состояние правой карточки."""
        self.card.set_state(state)


class ConnectCard(QFrame):
    """Правая часть экрана ожидания: светлая карточка с живой иллюстрацией."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(620, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(52, 48, 52, 40)
        lay.setSpacing(0)
        self.kicker = kicker("ШАГ 1 ИЗ 3", 15, 3.0, C["brand"])
        self.title = label("Подключите телефон кабелем", wrap=True, font_=font(FONT_HEAD, 38, W.Bold))
        lay.addWidget(self.kicker)
        lay.addSpacing(10)
        lay.addWidget(self.title)
        lay.addSpacing(6)
        self.art = ConnectArt()
        lay.addWidget(self.art, 1)
        lay.addSpacing(6)
        self.text = label("Кабели Lightning и USB‑C — справа. Телефон остаётся у вас в руках.", "cardtext", wrap=True)
        lay.addWidget(self.text)
        lay.addSpacing(16)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.pulse = Pulse(C["action"])
        self.status = label("ждём подключения", "cardstatus")
        row.addWidget(self.pulse)
        row.addWidget(self.status)
        row.addStretch(1)
        lay.addLayout(row)
        self.state = "wait"

    def set_state(self, state):
        """wait | found | nodriver"""
        self.state = state
        self.art.set_state(state)
        if state == "found":
            self.kicker.setText("ШАГ 2 ИЗ 3")
            self.title.setText("Телефон найден")
            self.text.setText("Разблокируйте его и нажмите «Доверять» на экране телефона.")
            self.status.setText("подключён")
            self.status.setStyleSheet(f"color: {C['ok']};")
            self.pulse.set(C["okdot"], blink=False)
        elif state == "nodriver":
            self.kicker.setText("ТЕХНИЧЕСКАЯ ПАУЗА")
            self.title.setText("Киоск временно не принимает")
            self.text.setText("Подойдите к сотруднику — он проверит телефон на кассе.")
            self.status.setText("нет связи с кабелем")
            self.status.setStyleSheet(f"color: {C['badtext']};")
            self.pulse.set(C["bad"], blink=False)
        else:
            self.kicker.setText("ШАГ 1 ИЗ 3")
            self.title.setText("Подключите телефон кабелем")
            self.text.setText("Кабели Lightning и USB‑C — справа. Телефон остаётся у вас в руках.")
            self.status.setText("ждём подключения")
            self.status.setStyleSheet(f"color: {C['brand']};")
            self.pulse.set(C["action"], blink=True)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(C["tint_border"]), 1))
        p.setBrush(QColor(C["tint"]))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 36, 36)


# ---------- 2. Проверка ----------

STEPS = [("connect", "Подключение и доверие"), ("passport", "Модель, память, серийный номер"),
         ("battery", "Батарея: здоровье и циклы"), ("locks", "Блокировки: Найти iPhone, активация, корпоративный надзор"),
         ("apple", "История обслуживания от Apple"), ("sickw", "Проверка по базе IMEI"), ("upload", "Отправка на кассу")]


class StepRow(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("row")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(20)
        self.dot = Dot()
        self.title = label(title, "rowtitle_wait")
        self.state = label("", "rowstate")
        lay.addWidget(self.dot)
        lay.addWidget(self.title, 1)
        lay.addWidget(self.state)
        self.set("wait", "")

    def set(self, state, text):
        self.dot.set_state(state)
        self.setObjectName("row_active" if state == "run" else "row")
        self.title.setObjectName("rowtitle_wait" if state == "wait" else "rowtitle")
        self.state.setObjectName("rowstate_active" if state == "run" else "rowstate")
        self.state.setText(text or {"wait": "следом", "run": "…", "done": "готово", "warn": "", "fail": ""}.get(state, ""))
        for w in (self, self.title, self.state):                  # перечитать QSS после смены objectName
            w.style().unpolish(w)
            w.style().polish(w)
            w.update()


class ScanScreen(Screen):
    skip_requested = Signal()

    def __init__(self, point=""):
        super().__init__()
        self.point_label = label(point_text(point), "muted")
        self.device_label = status_label("Телефон подключён")
        self.root.addLayout(header(self.point_label, self.device_label))
        body = QHBoxLayout()
        body.setSpacing(64)
        left = QVBoxLayout()
        left.setSpacing(0)
        left.addWidget(label("Проверяем телефон", font_=font(FONT_HEAD, 60, W.Bold, -1.0)))
        left.addSpacing(10)
        self.lead = label("Не отключайте кабель. Обычно это занимает около минуты.", "lead_s", wrap=True)
        left.addWidget(self.lead)
        left.addSpacing(30)
        self.rows = {}
        for i, (key, title) in enumerate(STEPS):
            r = StepRow(title)
            self.rows[key] = r
            if i:
                left.addSpacing(12)
            left.addWidget(r)
        left.addStretch(1)
        body.addLayout(left, 1)
        self.panel = QFrame()
        self.panel.setObjectName("bluecard")
        self.panel.setFixedWidth(680)
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(48, 48, 48, 48)
        pl.setSpacing(0)
        pl.addWidget(kicker("ОДИН ШАГ НА ТЕЛЕФОНЕ · ПОДТВЕРЖДЕНИЕ APPLE", 16, 3.0, C["pale"]))
        pl.addSpacing(14)
        pl.addWidget(label("Откройте на телефоне «Детали и обслуживание» — Apple сама скажет, что менялось",
                           wrap=True, font_=font(FONT_HEAD, 34, W.Bold), color="white"))
        pl.addSpacing(34)
        for i, t in enumerate(("Настройки → Основные", "Об этом устройстве",
                               "«Детали и обслуживание»\n(на старых iOS — «Запчасти и история обслуживания»)"), 1):
            if i > 1:
                pl.addSpacing(18)
            pl.addWidget(label(f"{i} · {t}", "bluestep", wrap=True))
        pl.addStretch(1)
        pl.addWidget(label("По кабелю мы видим привязку модулей, но подтвердить подлинность может только Apple — "
                           "и только с этого экрана. Если раздел уже открыт, выйдите и зайдите снова.",
                           "bluenote", wrap=True))
        pl.addSpacing(22)
        self.skip = QPushButton("Сделает сотрудник")
        self.skip.setObjectName("skip")
        self.skip.setCursor(Qt.PointingHandCursor)
        self.skip.clicked.connect(self.skip_requested.emit)
        pl.addWidget(self.skip, 0, Qt.AlignLeft)
        body.addWidget(self.panel)
        self.root.addLayout(body, 1)
        self.show_prompt(False)

    def set_point(self, point):
        self.point_label.setText(point_text(point))

    def reset(self, device_text="Телефон подключён"):
        for r in self.rows.values():
            r.set("wait", "")
        self.rows["connect"].set("run", "ждём «Доверять»")
        self.device_label.setText("● " + device_text)
        self.lead.setText("Не отключайте кабель. Обычно это занимает около минуты.")
        self.show_prompt(False)

    def show_prompt(self, on):
        self.panel.setVisible(bool(on))

    def set_step(self, key, state, text):
        if key in self.rows:
            self.rows[key].set(state, text)

    def set_trouble(self, text):
        self.lead.setText(text)


# ---------- 3. Результат ----------

def _changed_verb(name):
    """«Экран — менялся», «Камера — менялась», «Заднее стекло — менялось»."""
    w = name.strip().split()[-1].lower()
    if w.endswith(("а", "я")):
        return "менялась"
    if w.endswith(("о", "е")):
        return "менялось"
    return "менялся"


def card():
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(30, 30, 30, 30)
    lay.setSpacing(8)
    return f, lay


def line(text, colour=None, small=False):
    lab = label(text, "line_s" if small else "line", wrap=True)
    if colour:
        lab.setText(f'<span style="color:{colour}">●</span>&nbsp;&nbsp;{text}')
    return lab


def kv(k, v):
    row = QHBoxLayout()
    row.addWidget(label(k, "kv_k"))
    row.addStretch(1)
    vl = label(v, "kv_v")
    vl.setAlignment(Qt.AlignRight)
    row.addWidget(vl)
    return row


def clear_layout(lay):
    """Убрать всё из раскладки сразу: deleteLater без setParent(None) оставляет
    старые подписи нарисованными поверх новых до следующего цикла событий."""
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif it.layout() is not None:
            clear_layout(it.layout())


class ResultScreen(Screen):
    sell = Signal()
    just_looking = Signal()
    TEXT_WAIT = ("Подойдите к сотруднику — он запишет ваши имя и телефон, и здесь появится номер заявки. "
                 f'<b style="color:{C["ink"]}">Цену назовёт сотрудник</b> после осмотра. '
                 "По QR — отчёт о проверке, его можно забрать с собой.")
    TEXT_NUMBER = ("Заявка оформлена. Сотрудник сфотографирует телефон и "
                   f'<b style="color:{C["ink"]}">назовёт цену</b> после осмотра. '
                   "По QR — отчёт о проверке, его можно забрать с собой.")
    TEXT_LOCAL = "Назовите этот номер сотруднику — он осмотрит телефон и назовёт цену."

    def __init__(self):
        super().__init__(gray=True, margins=(72, 64, 72, 64), spacing=28)
        self.title = label("iPhone", font_=font(FONT_NUM, 40, W.Bold, -0.5))
        self.sub = label("", font_=font(FONT_TEXT, 22, W.DemiBold), color=C["muted"])
        self.chip = label("Хорошее состояние", "chip_ok")
        head = QHBoxLayout()
        head.setSpacing(24)
        head.addWidget(self.title)
        head.addWidget(self.sub)
        head.addStretch(1)
        head.addWidget(self.chip)
        self.root.addLayout(head)
        body = QHBoxLayout()
        body.setSpacing(28)
        # номер + QR; цены на киоске нет — её называет сотрудник
        self.next_card = QFrame()
        self.next_card.setObjectName("card_main")
        self.next_card.setFixedWidth(600)
        pl = QVBoxLayout(self.next_card)
        pl.setContentsMargins(44, 44, 44, 44)
        pl.setSpacing(0)
        pl.addWidget(kicker("ВАШ НОМЕР", 15))
        pl.addSpacing(6)
        self.number = PopNumber()
        pl.addWidget(self.number)
        pl.addSpacing(10)
        qrow = QHBoxLayout()
        qrow.setSpacing(24)
        self.qr = QrBlock()
        qrow.addWidget(self.qr, 0, Qt.AlignTop)
        self.qr_text = label(self.TEXT_WAIT, "qrtext", wrap=True)
        qrow.addWidget(self.qr_text, 1, Qt.AlignVCenter)
        pl.addLayout(qrow)
        pl.addSpacing(22)
        srow = QHBoxLayout()
        srow.setSpacing(12)
        self.pulse = Pulse(C["action"])
        self.status = label("ожидаем оформление у сотрудника", "cardstatus")
        srow.addWidget(self.pulse)
        srow.addWidget(self.status)
        srow.addStretch(1)
        pl.addLayout(srow)
        pl.addStretch(1)
        self.btn_done = QPushButton("Готово")
        self.btn_done.setObjectName("primary")
        self.btn_done.setCursor(Qt.PointingHandCursor)
        self.btn_done.clicked.connect(self.just_looking.emit)
        pl.addWidget(self.btn_done)
        body.addWidget(self.next_card)
        grid = QGridLayout()
        grid.setSpacing(24)
        self.c_bat, self.l_bat = card()
        self.c_apple, self.l_apple = card()
        self.c_locks, self.l_locks = card()
        self.c_pass, self.l_pass = card()
        grid.addWidget(self.c_bat, 0, 0)
        grid.addWidget(self.c_apple, 0, 1)
        grid.addWidget(self.c_locks, 1, 0)
        grid.addWidget(self.c_pass, 1, 1)
        body.addLayout(grid, 1)
        self.root.addLayout(body, 1)
        self.bar = None
        self._mode = None
        self._qr_url = None

    def fill(self, rep, server=None):
        pas, bat, leg = rep.get("паспорт") or {}, rep.get("батарея") or {}, rep.get("правовой") or {}
        sk, sto, hist = rep.get("sickw") or {}, rep.get("память") or {}, rep.get("apple_история") or {}
        itog = rep.get("итог") or {}
        self.title.setText(pas.get("модель") or "iPhone")
        self.sub.setText(" · ".join(x for x in (f"{sto.get('объём_гб')} ГБ" if sto.get("объём_гб") else None,
                                                 pas.get("цвет"), f"iOS {pas.get('ios')}" if pas.get("ios") else None) if x))
        # цену на киоске НЕ показываем — её называет сотрудник. Чип отражает только состояние.
        verdict = itog.get("вердикт")
        if verdict == "ПРОБЛЕМНЫЙ":
            self.chip.setObjectName("chip_bad")
            self.chip.setText("● Есть вопросы — к сотруднику")
        elif verdict in ("ИДЕАЛ", "ХОРОШИЙ"):
            self.chip.setObjectName("chip_ok")
            self.chip.setText("● Хорошее состояние")
        else:
            self.chip.setObjectName("chip_warn")
            self.chip.setText("● Нужен осмотр сотрудника")
        self.chip.style().unpolish(self.chip)
        self.chip.style().polish(self.chip)
        if not self.isVisible():                        # новый телефон: состояние заявки с нуля
            self._mode = None
            self._qr_url = None
            self.set_intake(server or {})
        # батарея
        clear_layout(self.l_bat)
        self.l_bat.addWidget(kicker("БАТАРЕЯ"))
        h = bat.get("здоровье_%")
        good = h is not None and h >= 85
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(label(f"{h} %" if h is not None else "—", font_=font(FONT_NUM, 54, W.Bold)))
        st = "хорошее состояние" if good else ("заметный износ" if h is not None else "не прочиталась")
        sl = label(st, font_=font(FONT_TEXT, 20, W.Bold), color=C["ok"] if good else C["warntext"])
        sl.setContentsMargins(0, 0, 0, 9)
        row.addWidget(sl, 0, Qt.AlignBottom)
        row.addStretch(1)
        self.l_bat.addLayout(row)
        self.l_bat.addSpacing(4)
        self.bar = Bar()
        self.bar.prepare(h or 0, C["okdot"] if good else C["warn"], animate=not self.isVisible())
        self.l_bat.addWidget(self.bar)
        self.l_bat.addSpacing(4)
        fake = bat.get("подделка") or []
        self.l_bat.addWidget(label(f"{bat.get('циклы') if bat.get('циклы') is not None else '?'} циклов · "
                                   + ("признаки неоригинальной батареи" if fake else "оригинальный аккумулятор Apple"),
                                   "note", wrap=True))
        self.l_bat.addStretch(1)
        # подлинность деталей
        clear_layout(self.l_apple)
        pv = rep.get("детали_вердикт") or {}
        self.l_apple.addWidget(kicker("ПОДЛИННОСТЬ ДЕТАЛЕЙ"))
        self.l_apple.addSpacing(6)
        itog_pv = pv.get("итог")
        if itog_pv == "родные":
            self.l_apple.addWidget(line("Все проверенные детали родные", C["okdot"]))
            self.l_apple.addWidget(label("Привязка модулей по кабелю и проверка Apple сошлись." if pv.get("apple_подтверждено")
                                         else "Проверено по кабелю: у этой модели Apple историю деталей не ведёт.",
                                         "note", wrap=True))
        elif itog_pv == "ремонт":
            for d in pv.get("детали", []):
                if d["статус"] in ("used", "repaired"):
                    self.l_apple.addWidget(line(f"{d['деталь']}: {d['почему']}", C["warn"]))
        elif itog_pv == "замена":
            for d in pv.get("детали", []):
                if d["статус"] == "bad":
                    self.l_apple.addWidget(line(f"{d['деталь']}: {d['почему']}", C["bad"]))
        else:                                           # кабель / неполно: без Apple зелёного не бывает
            self.l_apple.addWidget(line("Подлинность не подтверждена Apple", C["warn"]))
            self.l_apple.addWidget(label("Откройте на телефоне Настройки → Основные → Об этом устройстве → "
                                         "Детали и обслуживание — экран обновится сам. Сотрудник сверит раздел "
                                         "при оформлении.", "note", wrap=True))
        if hist:
            groups = {}
            for v in hist.values():
                groups.setdefault(v["деталь"], v)
            for name, v in list(groups.items())[:5]:
                verb = _changed_verb(name)
                if v.get("записи_без_деталей"):
                    self.l_apple.addWidget(line("У Apple есть записи о ремонте — подробности на экране телефона", C["warn"]))
                elif v.get("неизвестная"):
                    self.l_apple.addWidget(line(f"{name} — деталь неизвестного происхождения", C["bad"]))
                elif v.get("меняли"):
                    self.l_apple.addWidget(line(f"{name} — {verb}, " + ("б/у деталь" if v.get("бу") else "деталь Apple, новая"),
                                                C["warn"] if not v.get("бу") else C["bad"]))
                elif pv.get("apple_подтверждено"):
                    self.l_apple.addWidget(line(f"{name} — не {verb}", C["okdot"]))
                else:
                    self.l_apple.addWidget(line(f"{name} — ремонтов Apple не отмечено", C["muted"], small=True))
            self.l_apple.addWidget(label("По сверке Apple с заводской печатью вашего телефона" if any(
                v.get("источник", "").startswith("сверка") for v in hist.values())
                else "Из раздела «Детали и обслуживание» вашего телефона", "note", wrap=True))
        else:
            st = rep.get("apple_история_статус")
            if st == "формат не распознан":
                self.l_apple.addWidget(line("Раздел открыт — сотрудник сверит его на экране телефона", C["warn"]))
            elif itog_pv in ("ремонт", "замена"):
                self.l_apple.addWidget(label("Хотите увидеть ДАТЫ ремонтов — откройте на телефоне «Детали и обслуживание».",
                                             "note", wrap=True))
        self.l_apple.addStretch(1)
        # блокировки
        clear_layout(self.l_locks)
        self.l_locks.addWidget(kicker("БЛОКИРОВКИ И БАЗЫ"))
        self.l_locks.addSpacing(6)
        blk = sk.get("в_чёрном_списке")
        self.l_locks.addWidget(line("Не в чёрном списке" if blk is False else ("В ЧЁРНОМ СПИСКЕ" if blk else "База IMEI не проверялась"),
                                    C["okdot"] if blk is False else (C["bad"] if blk else C["warn"]), small=True))
        fmi_on = leg.get("найти_iphone") == "включён" or sk.get("fmi_включён") is True
        self.l_locks.addWidget(line("«Найти iPhone» включён — выключите перед продажей" if fmi_on else "Найти iPhone выключен",
                                    C["warn"] if fmi_on else C["okdot"], small=True))
        mdm = leg.get("mdm")
        self.l_locks.addWidget(line("Без корпоративного надзора" if mdm is False else ("Корпоративный надзор (MDM)" if mdm else "Надзор уточнит сотрудник"),
                                    C["okdot"] if mdm is False else (C["bad"] if mdm else C["warn"]), small=True))
        if leg.get("пароль"):
            self.l_locks.addWidget(line("Стоит пароль — попросим снять при продаже", C["warn"], small=True))
        self.l_locks.addStretch(1)
        # паспорт
        clear_layout(self.l_pass)
        self.l_pass.addWidget(kicker("ПАСПОРТ"))
        self.l_pass.addSpacing(6)
        self.l_pass.addLayout(kv("Серийный", pas.get("серийник") or "?"))
        self.l_pass.addLayout(kv("IMEI", pas.get("imei") or "—"))
        self.l_pass.addLayout(kv("Память", f"{sto.get('объём_гб') or '?'} ГБ, свободно {int(sto.get('свободно_гб') or 0)}"))
        self.l_pass.addLayout(kv("Куплен (по базе)", sk.get("дата_покупки") or "—"))
        self.l_pass.addLayout(kv("Уже приносили", "да" if (server or {}).get("уже_приносили") else "нет"))
        self.l_pass.addStretch(1)

    def set_intake(self, st):
        """Номер заявки появляется, когда сотрудник в кассе записал имя и телефон клиента
        (киоск опрашивает сервер); клиент сам ничего не вводит. QR всегда ведёт на отчёт
        о проверке. Появление номера анимируется один раз, QR всплывает при первом показе."""
        num = st.get("номер")
        url = st.get("ссылка_отчёта")
        if num and not st.get("локально"):
            mode, text = "number", self.TEXT_NUMBER
            status, colour, blink = "заявка оформлена", C["ok"], False
        elif num:                                         # автономно, без сервера — только номер
            mode, text = "local", self.TEXT_LOCAL
            status, colour, blink = "номер выдан", C["ok"], False
        else:
            mode, text = "wait", self.TEXT_WAIT
            status, colour, blink = "ожидаем оформление у сотрудника", C["brand"], True
        changed, first = mode != self._mode, self._mode is None
        self._mode = mode
        self.number.set_text(str(num) if num else "—", number=bool(num), pop=changed and bool(num))
        if url != self._qr_url or first:
            self._qr_url = url
            self.qr.set(qr_pixmap(url, 200) if url else None, "ОТЧЁТ", rise=first)
        self.qr_text.setText(text)
        self.status.setText(status)
        self.status.setStyleSheet(f"color: {colour};")
        self.pulse.set(C["okdot"] if not blink else C["action"], blink)
        if self.isVisible():
            self.number.play()
            self.qr.play()

    def showEvent(self, e):
        super().showEvent(e)
        self.number.play()
        self.qr.play()
        if self.bar is not None:
            self.bar.play()


def qr_pixmap(text, size=200):
    try:
        import qrcode
        q = qrcode.QRCode(border=1, box_size=1)
        q.add_data(text)
        q.make(fit=True)
        m = q.get_matrix()
    except Exception:                                            # noqa: BLE001
        return None
    n = len(m)
    box = max(1, size // n)
    pm = QPixmap(n * box, n * box)
    pm.fill(Qt.white)
    p = QPainter(pm)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(C["ink"]))
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                p.drawRect(x * box, y * box, box, box)
    p.end()
    return pm
