# -*- coding: utf-8 -*-
"""Pintel Diagnostics — общий язык экранов: цвета, шрифты, фон, анимированные детали.

Всё свёрстано на 1920×1080 и масштабируется целиком (app.ScaledHost). Облик идёт от знака:
глубокая чернота, синие волны по углам, неоновый синий как единственный акцент. Правило одно
на все экраны — **на экране одно главное**: остальное приглушено, чтобы и сотрудник, и клиент
с полувзгляда видели, что происходит и что делать дальше.

Движение здесь не украшение, а подсказка: пульсирует то, чего ждём; заполняется то, что
идёт; вспыхивает то, что только что изменилось. Все анимации — на таймерах и только пока
виджет виден: невидимый экран не тратит процессор кассы.

Шрифты: Inter — текст, Inter Display — заголовки, Space Grotesk — цифры и латиница.
"""
import math
import os
import time

from PySide6.QtCore import (QEasingCurve, QPointF, QRectF, QSize, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPalette, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
НАЗВАНИЕ = "Pintel Diagnostics"

# Цвета. Имена ключей прежние — по ним красится весь остальной код, — значения новые:
# тёмная тема от знака. «ink» — основной текст (теперь светлый), «ground» — фон экрана.
C = {
    "ink": "#F2F6FF", "body": "#B9C7DE", "muted": "#8496B3", "brand": "#59B8FF",
    "action": "#1E8BFF", "action_dark": "#1672DB", "tint": "#0E2242", "tint_border": "#1D4175",
    "ground": "#03060D", "border": "#18253C", "screen": "#0A1220",
    "ok": "#43E0A0", "okdot": "#2BD98F", "okbg": "#0C2A20",
    "warn": "#FFB547", "warntext": "#FFC670", "warnbg": "#2D2110",
    "bad": "#FF5C5C", "badtext": "#FF8F89", "badbg": "#321517",
    "pale": "#8FC1FF", "ring": "#2B3D5C", "ghost": "#506383",
    # новые
    "card": "#0A111F", "card_hi": "#0D1728", "field": "#060B15", "line": "#1B2A45",
    "glow": "#2A9BFF", "cyan": "#5CD0FF", "qr": "#0A1220",
}
FONT_TEXT, FONT_HEAD, FONT_NUM = "Inter", "Inter Display", "Space Grotesk"
W = QFont.Weight

# В QSS только размер и насыщенность: семейство приходит от шрифта приложения (Inter), а
# заголовки и надзаголовки с межбуквенным интервалом задаются кодом (QSS его не умеет).
QSS = """
QWidget { color: %(ink)s; }
QLabel#lead { font-size: 30px; font-weight: 500; color: %(body)s; }
QLabel#lead_s { font-size: 24px; font-weight: 500; color: %(body)s; }
QLabel#muted { font-size: 19px; font-weight: 500; color: %(muted)s; }
QLabel#step { font-size: 28px; font-weight: 600; }
QFrame#row { background: transparent; border: 1px solid transparent; border-radius: 14px; }
QFrame#row_active { background: %(tint)s; border: 1px solid %(tint_border)s; border-radius: 14px; }
QLabel#rowtitle { font-size: 20px; font-weight: 600; color: %(ink)s; }
QLabel#rowtitle_wait { font-size: 20px; font-weight: 500; color: %(ghost)s; }
QLabel#rowstate { font-size: 17px; font-weight: 500; color: %(muted)s; }
QLabel#rowstate_active { font-size: 17px; font-weight: 700; color: %(brand)s; }
QLabel#note { font-size: 19px; font-weight: 400; color: %(muted)s; }
QPushButton#primary { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1A7CFF, stop:1 #35B2FF);
    color: #FFFFFF; border-radius: 18px; font-size: 26px; font-weight: 700; min-height: 76px;
    border: none; padding: 0 34px; }
QPushButton#primary:pressed { background: %(action_dark)s; }
QPushButton#primary:disabled { background: #0E1626; color: %(ghost)s; }
QPushButton#update { background: %(tint)s; color: %(brand)s; border: 1px solid %(tint_border)s;
    border-radius: 14px; font-size: 20px; font-weight: 700; min-height: 54px; padding: 0 24px; }
QPushButton#update:pressed { background: %(tint_border)s; }
QPushButton#update:disabled { color: %(ghost)s; }
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
    """Надзаголовок капителью: «ТЕЛЕФОН», «КЛИЕНТ»…"""
    return label(text, font_=font(FONT_TEXT, px, W.Bold, spacing), color=color or C["muted"])


def ease_out():
    """cubic-bezier(.2,.8,.2,1)."""
    c = QEasingCurve(QEasingCurve.Type.BezierSpline)
    c.addCubicBezierSegment(QPointF(0.2, 0.8), QPointF(0.2, 1.0), QPointF(1.0, 1.0))
    return c


def smoothstep(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


_КАРТИНКИ = {}


def картинка(имя, высота=None, ширина=None):
    """Картинка из assets, один раз загруженная и ужатая. Нет файла — пустой QPixmap."""
    ключ = (имя, высота, ширина)
    if ключ not in _КАРТИНКИ:
        pm = QPixmap(os.path.join(ASSETS, имя))
        if not pm.isNull():
            if высота:
                pm = pm.scaledToHeight(int(высота), Qt.SmoothTransformation)
            elif ширина:
                pm = pm.scaledToWidth(int(ширина), Qt.SmoothTransformation)
        _КАРТИНКИ[ключ] = pm
    return _КАРТИНКИ[ключ]


def размыть(pm, радиус=26):
    """Гауссово размытие картинки с прозрачностью — из него получается свечение знака.

    Считается один раз при первом показе. Ужать и растянуть картинку было бы дешевле, но
    такое «размытие» видно квадратами и оно съезжает относительно оригинала — на экране
    знак двоился, вместо того чтобы светиться."""
    from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene
    поле = int(радиус * 2.5)
    сцена = QGraphicsScene()
    элемент = QGraphicsPixmapItem(pm)
    эффект = QGraphicsBlurEffect()
    эффект.setBlurRadius(радиус)
    эффект.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    элемент.setGraphicsEffect(эффект)
    сцена.addItem(элемент)
    итог = QImage(pm.width() + 2 * поле, pm.height() + 2 * поле, QImage.Format_ARGB32_Premultiplied)
    итог.fill(Qt.transparent)
    p = QPainter(итог)
    сцена.render(p, QRectF(0, 0, итог.width(), итог.height()),
                 QRectF(-поле, -поле, итог.width(), итог.height()))
    p.end()
    return QPixmap.fromImage(итог)


def logo_label(height=44):
    """Знак (два телефона с лупой) — для шапок рабочих экранов."""
    lab = QLabel()
    pm = картинка("logo_mark.png", высота=height)
    if pm.isNull():
        lab.setText("PINTEL")
    else:
        lab.setPixmap(pm)
        lab.setFixedSize(pm.size())
    return lab


def point_text(point):
    return f"{НАЗВАНИЕ} · {point}" if point else НАЗВАНИЕ


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
    return label(("● " if ok else "○ ") + text, font_=font(FONT_TEXT, 18, W.DemiBold),
                 color=C["okdot"] if ok else C["muted"])


# ---------- фон ----------

def _пятно(p, cx, cy, r, цвет, альфа):
    g = QRadialGradient(QPointF(cx, cy), r)
    c0, c1 = QColor(цвет), QColor(цвет)
    c0.setAlphaF(max(0.0, min(1.0, альфа)))
    c1.setAlphaF(0.0)
    g.setColorAt(0.0, c0)
    g.setColorAt(1.0, c1)
    p.setBrush(g)
    p.drawEllipse(QPointF(cx, cy), r, r)


def аврора(t=0.0, сила=1.0, размер=(320, 180)):
    """Фон знака: чернота и синие волны света по углам. → маленький QPixmap.

    Рисуем нарочно в малом размере и растягиваем: свечение размыто по природе, на глаз
    разницы нет, а закрашивать градиентами два миллиона пикселей тридцать раз в секунду
    касса на слабом ноутбуке не обязана.
    """
    w, h = размер
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor("#02040A"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    a, b = math.sin(t * 0.23), math.cos(t * 0.17)
    c, d = math.sin(t * 0.11 + 1.3), math.cos(t * 0.13 + 0.4)
    _пятно(p, w * 0.00 + 16 * a, h * 0.00 + 9 * b, h * 0.95, "#0B55FF", 0.60 * сила)
    _пятно(p, w * 1.00 - 14 * b, h * 1.02 - 10 * a, h * 1.05, "#0A7BFF", 0.55 * сила)
    _пятно(p, w * (0.50 + 0.20 * c), h * 1.25, h * 0.80, "#0D3BD9", 0.26 * сила)
    _пятно(p, w * (0.80 + 0.10 * d), -h * 0.28, h * 0.70, "#19A0FF", 0.18 * сила)
    _пятно(p, w * (0.16 + 0.06 * d), h * (0.92 + 0.05 * a), h * 0.42, "#0A2FBF", 0.16 * сила)
    p.end()
    return QPixmap.fromImage(img)


_ФОН = {}


def фон_статичный(размер):
    """Фон рабочих экранов: тот же свет по углам, но тихий и неподвижный — за ним работают."""
    ключ = (размер.width(), размер.height())
    if ключ not in _ФОН:
        _ФОН.clear()                                  # размер один на всю программу
        _ФОН[ключ] = аврора(t=2.4, сила=0.42).scaled(размер, Qt.IgnoreAspectRatio,
                                                      Qt.SmoothTransformation)
    return _ФОН[ключ]


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
    """Индикатор шага проверки: ждёт, крутится, готово, внимание, ошибка.

    Готовность не просто появляется, а «щёлкает»: кружок вырастает, галочка на месте.
    За минуту проверки это восемь маленьких подтверждений, что дело идёт."""

    def __init__(self, сторона=30):
        super().__init__()
        self.s = int(сторона)
        self.setFixedSize(self.s, self.s)
        self.state = "wait"
        self.t0 = time.monotonic()
        self.появление = 1.0
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.update)
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(420)
        self.anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self.anim.valueChanged.connect(self._шаг)

    def _шаг(self, v):
        self.появление = float(v)
        self.update()

    def set_state(self, state):
        было = self.state
        self.state = state
        if state == "run" and self.isVisible():
            self.timer.start()
        else:
            self.timer.stop()
        if state in ("done", "warn", "fail") and было != state and self.isVisible():
            self.появление = 0.0
            self.anim.start()
        else:
            self.anim.stop()
            self.появление = 1.0
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
        s = self.s
        r = QRectF(2.5, 2.5, s - 5, s - 5)
        p.setBrush(Qt.NoBrush)
        if self.state == "wait":
            p.setPen(QPen(QColor(C["ring"]), 2.5))
            p.drawEllipse(r)
        elif self.state == "run":
            faint = QColor(C["action"])
            faint.setAlphaF(0.22)
            p.setPen(QPen(faint, 3.5))
            p.drawEllipse(r)
            p.setPen(QPen(QColor(C["cyan"]), 3.5, Qt.SolidLine, Qt.RoundCap))
            ang = int((time.monotonic() - self.t0) * 300) % 360          # оборот за 1,2 с
            p.drawArc(r, (90 - ang) * 16, -110 * 16)
        else:
            col = {"done": C["okdot"], "warn": C["warn"], "fail": C["bad"]}.get(self.state, C["okdot"])
            k = max(0.0, self.появление)
            p.translate(s / 2, s / 2)
            p.scale(k, k)
            p.translate(-s / 2, -s / 2)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawEllipse(QRectF(0, 0, s, s))
            p.setPen(QPen(QColor("#04121C"), s * 0.085, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            u = s / 42.0
            if self.state == "done":
                path = QPainterPath(QPointF(13 * u, 21.5 * u))
                path.lineTo(QPointF(18.5 * u, 27 * u))
                path.lineTo(QPointF(29.5 * u, 15.5 * u))
                p.drawPath(path)
            elif self.state == "fail":
                p.drawLine(QPointF(15 * u, 15 * u), QPointF(27 * u, 27 * u))
                p.drawLine(QPointF(27 * u, 15 * u), QPointF(15 * u, 27 * u))
            else:
                p.drawLine(QPointF(21 * u, 12 * u), QPointF(21 * u, 24 * u))
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#04121C"))
                p.drawEllipse(QPointF(21 * u, 30.5 * u), 2.3 * u, 2.3 * u)


class Ring(QWidget):
    """Кольцо батареи: процент крупно в центре, дуга заполняется при появлении числа.

    Цвет говорит то же, что и число: зелёный — батарея в порядке, жёлтый — на грани,
    красный — ниже восьмидесяти, где сам телефон уже просит обслуживание."""

    def __init__(self, сторона=150):
        super().__init__()
        self.s = int(сторона)
        self.setFixedSize(self.s, self.s)
        self.значение = None
        self.показано = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(1300)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._шаг)

    def _шаг(self, v):
        self.показано = float(v)
        self.update()

    def set(self, значение):
        """Число 0…100 или None, если батарея не прочиталась."""
        новое = None if значение is None else max(0, min(100, int(значение)))
        if новое == self.значение:
            return
        self.значение = новое
        self.anim.stop()
        if новое is None:
            self.показано = 0.0
            self.update()
            return
        if self.isVisible():
            self.anim.setStartValue(0.0)
            self.anim.setEndValue(float(новое))
            self.anim.start()
        else:
            self.показано = float(новое)
            self.update()

    @staticmethod
    def цвет_для(значение):
        if значение is None:
            return C["ghost"]
        return C["okdot"] if значение >= 85 else (C["warn"] if значение >= 80 else C["bad"])

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.s
        толщина = s * 0.085
        r = QRectF(толщина / 2 + 5, толщина / 2 + 5, s - толщина - 10, s - толщина - 10)
        p.setPen(QPen(QColor(C["line"]), толщина))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(r)
        цвет = QColor(self.цвет_для(self.значение))
        if self.значение is not None and self.показано > 0:
            мягко = QColor(цвет)
            мягко.setAlphaF(0.20)
            p.setPen(QPen(мягко, толщина + 8, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(r, 90 * 16, int(-360 * 16 * self.показано / 100))
            p.setPen(QPen(цвет, толщина, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(r, 90 * 16, int(-360 * 16 * self.показано / 100))
        p.setPen(QColor(C["ink"]))
        if self.значение is None:
            p.setFont(font(FONT_NUM, int(s * 0.26), W.Bold))
            p.drawText(self.rect(), Qt.AlignCenter, "—")
            return
        число = str(int(round(self.показано)))
        шрифт = font(FONT_NUM, int(s * 0.30), W.Bold)
        p.setFont(шрифт)
        ш_числа = p.fontMetrics().horizontalAdvance(число)
        малый = font(FONT_NUM, int(s * 0.15), W.Medium)
        p.setFont(малый)
        ш_знака = p.fontMetrics().horizontalAdvance("%")
        x0 = (s - ш_числа - ш_знака - 2) / 2
        p.setFont(шрифт)
        p.drawText(QRectF(x0, 0, ш_числа + 2, s), Qt.AlignVCenter | Qt.AlignLeft, число)
        p.setFont(малый)
        p.setPen(QColor(C["muted"]))
        p.drawText(QRectF(x0 + ш_числа + 2, s * 0.06, ш_знака + 4, s), Qt.AlignVCenter | Qt.AlignLeft, "%")


class Stepper(QWidget):
    """Шаги сделки одной строкой: что сделано, что сейчас, что впереди.

    Это и карта, и навигация: по шагу можно нажать и вернуться к нему. Раньше для этого в
    каждой карточке стояла пара кнопок «К тесту», «К фото», и сотрудник читал их вместо того,
    чтобы смотреть на телефон. Текущий шаг дышит, линия между шагами заполняется по мере
    того, как сделка идёт."""

    выбран = Signal(int)

    def __init__(self, названия):
        super().__init__()
        self.названия = list(названия)
        self.готово = [False] * len(self.названия)
        self.текущий = 0
        self.доступны = set()
        self.идут = set()
        self.setFixedHeight(64)
        self.setMouseTracking(True)
        self._области = []
        self._доля = 0.0                      # заполнение линии, анимируется
        self._всплеск = None                  # когда сменился текущий шаг: от него расходится кольцо
        self.t0 = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._тик)

    def set(self, готово, текущий, доступны=(), идут=()):
        """`идут` — шаги, которые выполняются сами (проверка по кабелю): у них крутится дуга."""
        if int(текущий) != self.текущий and self.isVisible():
            self._всплеск = time.monotonic()
        self.готово = list(готово)
        self.текущий = int(текущий)
        self.доступны = set(доступны)
        self.идут = set(идут)
        self.update()

    def _цель(self):
        """До какого шага дотянута линия: до последнего сделанного подряд."""
        n = 0
        for есть in self.готово:
            if not есть:
                break
            n += 1
        return min(n, len(self.названия) - 1) / max(1, len(self.названия) - 1)

    def _тик(self):
        цель = self._цель()
        if abs(цель - self._доля) > 0.002:
            self._доля += (цель - self._доля) * 0.14
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self.timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    def _на_шаге(self, pos):
        for i, область in enumerate(self._области):
            if область.contains(pos):
                return i
        return None

    def mouseMoveEvent(self, e):
        i = self._на_шаге(e.position())
        self.setCursor(Qt.PointingHandCursor if i in self.доступны else Qt.ArrowCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        i = self._на_шаге(e.position())
        if e.button() == Qt.LeftButton and i is not None and i in self.доступны:
            self.выбран.emit(i)
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.названия)
        w, h = self.width(), self.height()
        кружок = 34
        шрифт = font(FONT_TEXT, 19, W.DemiBold)
        p.setFont(шрифт)
        fm = p.fontMetrics()
        ширины = [кружок + 12 + fm.horizontalAdvance(имя) for имя in self.названия]
        зазор = (w - sum(ширины) - 8) / max(1, n - 1)
        y = h / 2
        t = time.monotonic() - self.t0
        x = 4.0
        края = []
        for ш in ширины:
            края.append((x, x + ш))
            x += ш + зазор
        p.setPen(QPen(QColor(C["line"]), 2))
        for i in range(n - 1):
            p.drawLine(QPointF(края[i][1] + 14, y), QPointF(края[i + 1][0] - 14, y))
        полная = (n - 1) * self._доля
        for i in range(n - 1):
            доля = max(0.0, min(1.0, полная - i))
            if доля <= 0:
                continue
            a, b = края[i][1] + 14, края[i + 1][0] - 14
            g = QLinearGradient(a, y, b, y)
            g.setColorAt(0, QColor(C["okdot"]))
            g.setColorAt(1, QColor(C["cyan"]))
            p.setPen(QPen(g, 2.5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(a, y), QPointF(a + (b - a) * доля, y))
        self._области = []
        for i, имя in enumerate(self.названия):
            x0, x1 = края[i]
            self._области.append(QRectF(x0 - 8, 0, x1 - x0 + 16, h))
            сделан, сейчас = self.готово[i], i == self.текущий
            c = QPointF(x0 + кружок / 2, y)
            if сейчас:
                пульс = 0.5 + 0.5 * math.sin(t * 2.6)
                ореол = QColor(C["glow"])
                ореол.setAlphaF(0.10 + 0.16 * пульс)
                p.setPen(Qt.NoPen)
                p.setBrush(ореол)
                p.drawEllipse(c, кружок / 2 + 4 + 3 * пульс, кружок / 2 + 4 + 3 * пульс)
                if self._всплеск is not None:
                    u = (time.monotonic() - self._всплеск) / 0.7
                    if u < 1.0:
                        кольцо = QColor(C["cyan"])
                        кольцо.setAlphaF(0.7 * (1 - u))
                        p.setPen(QPen(кольцо, 2))
                        p.setBrush(Qt.NoBrush)
                        r = кружок / 2 + 26 * (1 - (1 - u) ** 2)
                        p.drawEllipse(c, r, r)
                    else:
                        self._всплеск = None
            if i in self.идут and not сделан:
                слабая = QColor(C["action"])
                слабая.setAlphaF(0.25)
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(слабая, 3))
                дуга = QRectF(c.x() - кружок / 2 + 1.5, y - кружок / 2 + 1.5, кружок - 3, кружок - 3)
                p.drawEllipse(дуга)
                p.setPen(QPen(QColor(C["cyan"]), 3, Qt.SolidLine, Qt.RoundCap))
                угол = int(t * 300) % 360
                p.drawArc(дуга, (90 - угол) * 16, -110 * 16)
                p.setPen(QColor(C["body"]))
                p.setFont(font(FONT_NUM, 17, W.Bold))
                p.drawText(QRectF(c.x() - кружок / 2, y - кружок / 2, кружок, кружок),
                           Qt.AlignCenter, str(i + 1))
            elif сделан:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(C["okdot"]))
                p.drawEllipse(c, кружок / 2, кружок / 2)
                p.setPen(QPen(QColor("#04121C"), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                path = QPainterPath(c + QPointF(-7, 0.5))
                path.lineTo(c + QPointF(-2, 5.5))
                path.lineTo(c + QPointF(7.5, -5))
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)
            else:
                p.setPen(QPen(QColor(C["cyan"] if сейчас else C["ring"]), 2.5))
                p.setBrush(QColor(C["tint"]) if сейчас else Qt.NoBrush)
                p.drawEllipse(c, кружок / 2 - 1.5, кружок / 2 - 1.5)
                p.setPen(QColor(C["ink"] if сейчас else C["ghost"]))
                p.setFont(font(FONT_NUM, 17, W.Bold))
                p.drawText(QRectF(c.x() - кружок / 2, y - кружок / 2, кружок, кружок),
                           Qt.AlignCenter, str(i + 1))
            p.setFont(шрифт)
            p.setPen(QColor(C["ink"] if сейчас else (C["body"] if (сделан or i in self.идут) else C["ghost"])))
            p.drawText(QRectF(x0 + кружок + 12, 0, x1 - x0 - кружок - 12 + 6, h),
                       Qt.AlignVCenter | Qt.AlignLeft, имя)


class Успех(QWidget):
    """Сделка ушла: кольцо замыкается, галочка прорисовывается. Один раз, при показе."""

    def __init__(self, сторона=132):
        super().__init__()
        self.s = int(сторона)
        self.setFixedSize(self.s, self.s)
        self.v = 1.0
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(900)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._шаг)

    def _шаг(self, v):
        self.v = float(v)
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self.v = 0.0
        self.anim.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.s
        r = QRectF(8, 8, s - 16, s - 16)
        ореол = QColor(C["okdot"])
        ореол.setAlphaF(0.14 * self.v)
        p.setPen(Qt.NoPen)
        p.setBrush(ореол)
        p.drawEllipse(QRectF(0, 0, s, s))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(C["okdot"]), 6, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r, 90 * 16, int(-360 * 16 * min(1.0, self.v / 0.6)))
        k = max(0.0, (self.v - 0.45) / 0.55)
        if k > 0:
            a, b, c = QPointF(s * 0.30, s * 0.52), QPointF(s * 0.44, s * 0.66), QPointF(s * 0.72, s * 0.36)
            path = QPainterPath(a)
            path.lineTo(a + (b - a) * min(1.0, k / 0.4))
            if k > 0.4:
                path.lineTo(b + (c - b) * ((k - 0.4) / 0.6))
            p.setPen(QPen(QColor(C["okdot"]), 8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)


class SheenButton(QPushButton):
    """Главная кнопка: когда она готова к нажатию, по ней раз в несколько секунд пробегает
    блик. Глаз сам находит на экране то, что движется, — искать «куда нажать» не приходится."""

    def __init__(self, text=""):
        super().__init__(text)
        self.t0 = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._тик)

    def _живая(self):
        return self.isEnabled() and self.objectName() == "primary"

    def _тик(self):
        if self._живая():
            self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self.timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self._живая():
            return
        u = ((time.monotonic() - self.t0) % 3.6) / 1.1          # блик идёт 1,1 с из каждых 3,6
        if u >= 1.0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 18, 18)
        p.setClipPath(clip)
        w, h = self.width(), self.height()
        x = -0.40 * w + 1.8 * w * u
        g = QLinearGradient(x, 0, x + 0.38 * w, 0)
        g.setColorAt(0.0, QColor(255, 255, 255, 0))
        g.setColorAt(0.5, QColor(255, 255, 255, 70))
        g.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        полоса = QPainterPath()
        полоса.moveTo(x + 0.10 * w, 0)
        полоса.lineTo(x + 0.38 * w, 0)
        полоса.lineTo(x + 0.28 * w, h)
        полоса.lineTo(x, h)
        полоса.closeSubpath()
        p.drawPath(полоса)


class QrBlock(QWidget):
    """QR на белой плитке с подписью.

    `сторона` — желаемый размер кода. Размер не жёсткий, а предельный: под давлением QR
    ужимается (до `МИНИМУМ`). Так было не всегда, и платили за это на точке: жёсткий размер
    ужиматься отказывался, и когда содержимому карточки переставало хватать высоты — из-за
    длинного текста или более крупного системного шрифта, — раскладка Qt укладывала
    следующие подписи ПОВЕРХ него. Ужавшийся QR читается телефоном, текст по тексту — никем.
    """

    # До этого размера QR ужимается молча: ссылка в нём короткая, это 29–37 модулей, то есть
    # около трёх пикселей на модуль — телефон наводится с ладони.
    МИНИМУМ = 100

    def __init__(self, сторона=200):
        super().__init__()
        self.сторона = int(сторона)
        self.setMaximumSize(self.сторона + 16, self.сторона + 46)
        self.setMinimumSize(self.МИНИМУМ + 16, self.МИНИМУМ + 46)
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
        self.pm = pm.scaled(self.сторона, self.сторона, Qt.KeepAspectRatio,
                            Qt.FastTransformation) if pm else None
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

    def sizeHint(self):
        return QSize(self.сторона + 16, self.сторона + 46)

    def _сторона_сейчас(self) -> int:
        """Сколько места под сам код есть прямо сейчас: ширина и высота минус поля."""
        return max(self.МИНИМУМ, min(self.width() - 16, self.height() - 46))

    def paintEvent(self, e):
        if self.pm is None:
            return
        бок = self._сторона_сейчас()
        код = self.pm.scaled(бок, бок, Qt.KeepAspectRatio, Qt.FastTransformation)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self.alpha)
        p.translate(0, self.dy)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("white"))
        рамка = бок + 15
        p.drawRoundedRect(QRectF(0.5, 0.5, рамка, рамка), 18, 18)
        p.drawPixmap(8 + (бок - код.width()) // 2, 8 + (бок - код.height()) // 2, код)
        p.setFont(self.font_)
        p.setPen(QColor(C["muted"]))
        p.drawText(QRectF(0, бок + 24, бок + 16, 20),
                   Qt.AlignHCenter | Qt.AlignVCenter, self.caption)


# ---------- каркас ----------

class Screen(QWidget):
    """Экран: тёмный фон со светом по углам рисует сам, детей кладёт в `self.root`.

    Фон именно рисуется, а не лежит отдельным виджетом под остальными: любой виджет-подложка
    был бы «соседом» каждой карточки, и тест вёрстки справедливо счёл бы это наездом.
    `gray` оставлен в подписи ради прежних вызовов — светлых экранов больше нет."""

    def __init__(self, gray=False, margins=(88, 72, 88, 72), spacing=24):
        super().__init__()
        self.setObjectName("screen")
        self.setAutoFillBackground(False)
        pal = self.palette()
        for роль in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            pal.setColor(роль, QColor(C["ink"]))
        pal.setColor(QPalette.PlaceholderText, QColor(C["ghost"]))
        pal.setColor(QPalette.Highlight, QColor(C["action"]))
        pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        self.setPalette(pal)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(*margins)
        self.root.setSpacing(spacing)

    def paintEvent(self, e):
        p = QPainter(self)
        p.drawPixmap(0, 0, фон_статичный(self.size()))


# ---------- 1. Ожидание ----------

class MainScreen(Screen):
    """Экран ожидания: знак Pintel Diagnostics, живой свет и одна подсказка.

    Здесь нарочно почти ничего нет. Перед стойкой стоит клиент, и первое, что он видит, —
    не инструкция из трёх пунктов, а знак и одна фраза. Начать можно нажатием в любое место
    экрана или клавишей: искать кнопку незачем.

    Знак, свет, искры и подсказка нарисованы в `paintEvent`, а не собраны из виджетов: они
    движутся и накладываются друг на друга, чего раскладка Qt не умеет. Виджетами остались
    только статус связи, имя точки и кнопка обновления — то, что должно нажиматься и
    читаться тестом вёрстки.
    """

    обновить = Signal()
    начать = Signal()

    ПОДСКАЗКА = "Нажмите, чтобы начать"

    def __init__(self, point=""):
        super().__init__(margins=(56, 40, 56, 40), spacing=0)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.device = "wait"
        self.t0 = time.monotonic()
        self._искры = [((i * 0.6180339887) % 1.0, (i * 0.3819660113 + 0.17) % 1.0,
                        0.5 + ((i * 7) % 10) / 10.0, 1.2 + (i % 4) * 0.7) for i in range(46)]

        верх = QHBoxLayout()
        self.point_label = label(point_text(point), font_=font(FONT_TEXT, 18, W.Medium), color=C["muted"])
        self.status = status_label("Готов к работе")
        верх.addWidget(self.point_label)
        верх.addStretch(1)
        верх.addWidget(self.status)
        self.root.addLayout(верх)
        self.root.addStretch(1)
        низ = QHBoxLayout()
        низ.addStretch(1)
        self.b_обновить = QPushButton("Обновить программу")
        self.b_обновить.setObjectName("update")
        self.b_обновить.setCursor(Qt.PointingHandCursor)
        self.b_обновить.setFont(font(FONT_TEXT, 20, W.Bold))
        self.b_обновить.clicked.connect(self.обновить.emit)
        self.b_обновить.setVisible(False)
        низ.addWidget(self.b_обновить)
        self.root.addLayout(низ)

        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.update)

    # ---------- то, что зовёт приложение ----------
    def set_point(self, point):
        self.point_label.setText(point_text(point))

    def set_status(self, text, ok=True):
        self.status.setText(("● " if ok else "○ ") + text)
        self.status.setStyleSheet(f"color: {C['okdot'] if ok else C['bad']};")

    def set_device(self, state):
        """wait | found | nodriver — что с кабелем; меняет строку под знаком."""
        self.device = state
        self.update()

    def показать_обновление(self, текст="", занято=False):
        """Новая версия найдена — кнопка появляется. Пусто — прячем."""
        self.b_обновить.setVisible(bool(текст))
        self.b_обновить.setEnabled(not занято)
        if текст:
            self.b_обновить.setText(текст)

    # ---------- жизнь ----------
    def showEvent(self, e):
        super().showEvent(e)
        self.t0 = time.monotonic()
        self.timer.start()
        self.setFocus()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.начать.emit()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.начать.emit()
            return
        super().keyPressEvent(e)

    # ---------- рисунок ----------
    def _знак(self):
        """Знак с надписью и его размытый двойник для свечения. Считаются один раз."""
        ширина = int(min(self.width() * 0.60, 1180))
        if getattr(self, "_знак_ширина", None) != ширина:
            знак = картинка("logo_full.png", ширина=ширина)
            if знак.isNull():
                self._знак_пара = (знак, знак)
            else:
                self._знак_пара = (знак, размыть(знак, 30))
            self._знак_ширина = ширина
        return self._знак_пара

    def paintEvent(self, e):
        t = time.monotonic() - self.t0
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawPixmap(self.rect(), аврора(t))

        # волны по углам — тонкие светящиеся кромки, как на знаке
        p.setBrush(Qt.NoBrush)
        for угол in (0, 1):
            for k in range(3):
                фаза = t * (0.20 + 0.05 * k) + угол * 1.7 + k * 0.9
                сдвиг = 46 * k + 16 * math.sin(фаза)
                путь = QPainterPath()
                if угол == 0:
                    путь.moveTo(-20, h * 0.34 + сдвиг)
                    путь.cubicTo(w * 0.10, h * (0.26 + 0.03 * math.sin(фаза)), w * 0.16, h * 0.08,
                                 w * 0.34 + сдвиг, -20)
                    g = QLinearGradient(0, h * 0.34, w * 0.34, 0)
                else:
                    путь.moveTo(w + 20, h * 0.40 - сдвиг)
                    путь.cubicTo(w * 0.93, h * (0.62 + 0.03 * math.cos(фаза)), w * 0.80, h * 0.84,
                                 w * 0.52 - сдвиг, h + 20)
                    g = QLinearGradient(w, h * 0.40, w * 0.52, h)
                яркость = 0.55 - 0.15 * k
                g.setColorAt(0.0, QColor(40, 160, 255, 0))
                g.setColorAt(0.5, QColor(70, 180, 255, int(255 * яркость)))
                g.setColorAt(1.0, QColor(40, 120, 255, 0))
                p.setPen(QPen(g, 2.4 - 0.5 * k))
                p.drawPath(путь)

        # искры: медленно всплывают и мерцают
        p.setPen(Qt.NoPen)
        for x0, y0, скорость, размер in self._искры:
            y = (y0 - t * 0.012 * скорость) % 1.0
            x = x0 + 0.012 * math.sin(t * 0.5 * скорость + x0 * 9)
            мерц = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 1.3 * скорость + y0 * 20))
            край = smoothstep(min(y, 1 - y) / 0.12)
            c = QColor(140, 205, 255)
            c.setAlphaF(0.55 * мерц * край)
            p.setBrush(c)
            p.drawEllipse(QPointF(x * w, y * h), размер, размер)

        # знак: парит, свечение дышит, раз в несколько секунд по нему проходит блик
        знак, ореол = self._знак()
        if not знак.isNull():
            парение = 7 * math.sin(t * 0.8)
            вход = smoothstep(t / 1.1)                       # появление при показе экрана
            cx, cy = w / 2, h * 0.455 + парение + 26 * (1 - вход)
            дыхание = 0.5 + 0.5 * math.sin(t * 1.25)
            p.setOpacity((0.45 + 0.55 * дыхание) * вход)      # свечение дышит
            p.drawPixmap(int(cx - ореол.width() / 2), int(cy - ореол.height() / 2), ореол)
            p.setOpacity(вход)
            x, y = int(cx - знак.width() / 2), int(cy - знак.height() / 2)
            p.drawPixmap(x, y, знак)
            u = (t % 5.5) / 1.3
            if u < 1.0 and вход >= 1.0:
                блик = QPixmap(знак.size())
                блик.fill(Qt.transparent)
                q = QPainter(блик)
                q.drawPixmap(0, 0, знак)
                q.setCompositionMode(QPainter.CompositionMode_SourceAtop)
                bx = -0.25 * знак.width() + 1.5 * знак.width() * u
                g = QLinearGradient(bx, 0, bx + 0.22 * знак.width(), знак.height() * 0.4)
                g.setColorAt(0.0, QColor(255, 255, 255, 0))
                g.setColorAt(0.5, QColor(255, 255, 255, 150))
                g.setColorAt(1.0, QColor(255, 255, 255, 0))
                q.fillRect(блик.rect(), g)
                q.end()
                p.drawPixmap(x, y, блик)
            p.setOpacity(1.0)

        # одна фраза под знаком и строка про кабель
        пульс = 0.5 + 0.5 * math.sin(t * 2.0)
        цвет = QColor(C["ink"])
        цвет.setAlphaF((0.45 + 0.50 * пульс) * smoothstep((t - 0.6) / 1.0))
        p.setPen(цвет)
        p.setFont(font(FONT_TEXT, 30, W.Medium, 0.6))
        p.drawText(QRectF(0, h * 0.775, w, 46), Qt.AlignHCenter | Qt.AlignVCenter, self.ПОДСКАЗКА)
        ya = h * 0.775 + 62 + 6 * пульс                      # стрелка под фразой покачивается
        p.setPen(QPen(цвет, 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        стрелка = QPainterPath(QPointF(w / 2 - 13, ya))
        стрелка.lineTo(QPointF(w / 2, ya + 12))
        стрелка.lineTo(QPointF(w / 2 + 13, ya))
        p.drawPath(стрелка)
        строка, цвет_строки = {
            "found": ("Телефон подключён", C["okdot"]),
            "nodriver": ("Служба Apple не отвечает — перезапустите Apple Mobile Device Service",
                         C["warntext"]),
        }.get(self.device, ("", C["muted"]))
        if строка:
            p.setFont(font(FONT_TEXT, 21, W.DemiBold))
            p.setPen(QColor(цвет_строки))
            p.drawText(QRectF(0, h * 0.775 + 96, w, 34), Qt.AlignHCenter | Qt.AlignVCenter,
                       "●  " + строка)


# ---------- 2. Проверка ----------

# Короткие названия: строка шага должна читаться целиком и с двух метров.
STEPS = [("connect", "Подключение"), ("passport", "Модель и память"),
         ("battery", "Батарея"), ("locks", "Блокировки"),
         ("apple", "Данные Apple"), ("sickw", "База IMEI"),
         ("rfs", "Реестр IMEI РК"), ("upload", "Отправка на кассу")]


class StepRow(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("row")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 16, 9)
        lay.setSpacing(14)
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
        self.state.setText(text or {"wait": "", "run": "…", "done": "готово", "warn": "", "fail": ""}.get(state, ""))
        for w in (self, self.title, self.state):                  # перечитать QSS после смены objectName
            w.style().unpolish(w)
            w.style().polish(w)
            w.update()


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
    p.setBrush(QColor(C["qr"]))
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                p.drawRect(x * box, y * box, box, box)
    p.end()
    return pm
