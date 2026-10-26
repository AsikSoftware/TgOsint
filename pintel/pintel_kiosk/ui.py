# -*- coding: utf-8 -*-
"""Экраны киоска по утверждённому макету (1920×1080, масштабируется)."""
import os

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
C = {"text": "#0B1B33", "body": "#3B4F6B", "muted": "#5B7392", "primary": "#1A549D", "pale": "#B8D0EC",
     "light": "#E8F1FB", "bg": "#F3F6FA", "border": "#E3EAF2", "ok": "#15724C", "okdot": "#1E9E6A",
     "okbg": "#E6F6EE", "warn": "#D98B1E", "warntext": "#9A5B07", "bad": "#B3261E"}

QSS = """
QWidget { color: %(text)s; font-family: "Manrope", "Segoe UI", sans-serif; }
QWidget#screen { background: #FFFFFF; }
QWidget#screen_gray { background: %(bg)s; }
QLabel#h1 { font-family: "Montserrat", "Segoe UI", sans-serif; font-size: 72px; font-weight: 800; }
QLabel#h1s { font-family: "Montserrat", "Segoe UI", sans-serif; font-size: 60px; font-weight: 800; }
QLabel#lead { font-size: 30px; font-weight: 500; color: %(body)s; }
QLabel#muted { font-size: 20px; font-weight: 600; color: %(muted)s; }
QLabel#step { font-size: 26px; font-weight: 600; }
QLabel#num { background: %(primary)s; color: white; border-radius: 28px; min-width: 56px; max-width: 56px; min-height: 56px; max-height: 56px; font-family: "Montserrat"; font-size: 26px; font-weight: 800; }
QLabel#cardkicker { font-size: 20px; font-weight: 700; color: %(pale)s; letter-spacing: 3px; background: transparent; }
QLabel#cardtitle { font-family: "Montserrat"; font-size: 44px; font-weight: 800; color: white; background: transparent; }
QLabel#cardtext { font-size: 24px; font-weight: 600; color: #DCE8F5; background: transparent; }
QLabel#cardstatus { font-size: 22px; font-weight: 700; color: white; background: transparent; }
QFrame#row { background: %(bg)s; border-radius: 20px; }
QFrame#row_active { background: %(light)s; border: 2px solid %(primary)s; border-radius: 20px; }
QLabel#rowtitle { font-size: 24px; font-weight: 700; }
QLabel#rowstate { font-size: 20px; font-weight: 600; color: %(muted)s; }
QLabel#rowstate_active { font-size: 20px; font-weight: 700; color: %(primary)s; }
QLabel#dot_done { background: %(okdot)s; border-radius: 22px; min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px; color: white; font-size: 22px; font-weight: 800; }
QLabel#dot_wait { background: transparent; border: 3px solid #C9D5E3; border-radius: 22px; min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px; }
QLabel#dot_run { background: transparent; border: 4px solid %(primary)s; border-radius: 22px; min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px; }
QLabel#dot_warn { background: %(warn)s; border-radius: 22px; min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px; color: white; font-size: 22px; font-weight: 800; }
QLabel#dot_fail { background: %(bad)s; border-radius: 22px; min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px; color: white; font-size: 22px; font-weight: 800; }
QFrame#bluecard { background: %(primary)s; border-radius: 32px; }
QLabel#bluekicker { font-size: 20px; font-weight: 700; color: %(pale)s; letter-spacing: 2px; }
QLabel#bluetitle { font-family: "Montserrat"; font-size: 38px; font-weight: 800; color: white; }
QLabel#bluestep { font-size: 24px; font-weight: 600; color: white; }
QLabel#bluenote { font-size: 20px; font-weight: 600; color: white; background: rgba(255,255,255,0.12); border-radius: 16px; padding: 18px 22px; }
QPushButton#skip { font-size: 20px; font-weight: 700; color: %(pale)s; background: transparent; border: 2px solid %(pale)s; border-radius: 14px; padding: 12px 22px; }
QFrame#card { background: white; border: 1px solid %(border)s; border-radius: 28px; }
QLabel#kicker { font-size: 18px; font-weight: 700; color: %(muted)s; letter-spacing: 2px; }
QLabel#price { font-family: "Montserrat"; font-size: 92px; font-weight: 800; }
QLabel#pricenote { font-size: 22px; font-weight: 600; color: %(body)s; }
QLabel#big { font-family: "Montserrat"; font-size: 54px; font-weight: 800; }
QLabel#line { font-size: 22px; font-weight: 600; }
QLabel#kv_k { font-size: 21px; font-weight: 600; color: %(muted)s; }
QLabel#kv_v { font-size: 21px; font-weight: 700; }
QLabel#chip_ok { background: %(okbg)s; color: %(ok)s; border-radius: 28px; padding: 12px 22px; font-size: 22px; font-weight: 700; }
QLabel#chip_warn { background: #FFF1CC; color: %(warntext)s; border-radius: 28px; padding: 12px 22px; font-size: 22px; font-weight: 700; }
QLabel#chip_bad { background: #FBE9E7; color: %(bad)s; border-radius: 28px; padding: 12px 22px; font-size: 22px; font-weight: 700; }
QPushButton#primary { background: %(primary)s; color: white; border-radius: 22px; font-size: 28px; font-weight: 800; min-height: 88px; border: none; }
QPushButton#primary:pressed { background: #123C74; }
QPushButton#secondary { background: %(bg)s; color: %(text)s; border-radius: 22px; font-size: 22px; font-weight: 700; min-height: 64px; border: none; }
QFrame#ticket { background: %(primary)s; border-radius: 40px; }
QLabel#ticketkicker { font-size: 22px; font-weight: 700; color: %(pale)s; letter-spacing: 3px; }
QLabel#ticketnum { font-family: "Montserrat"; font-size: 220px; font-weight: 800; color: white; }
QLabel#ticketnote { font-size: 24px; font-weight: 600; color: #DCE8F5; }
QFrame#qrbox { border: 2px dashed #C9D5E3; border-radius: 24px; }
QLabel#footer { font-size: 19px; font-weight: 500; color: %(muted)s; }
QLabel#bar_bg { background: %(border)s; border-radius: 7px; min-height: 14px; max-height: 14px; }
QLabel#bar_fg { background: %(okdot)s; border-radius: 7px; min-height: 14px; max-height: 14px; }
QLabel#bar_fg_warn { background: %(warn)s; border-radius: 7px; min-height: 14px; max-height: 14px; }
""" % C


def load_fonts():
    """Статические начертания (Qt не выбирает насечку у вариативных шрифтов)."""
    d = os.path.join(ASSETS, "fonts")
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if name.endswith(".ttf"):
                QFontDatabase.addApplicationFont(os.path.join(d, name))


def logo_label(height=44):
    lab = QLabel()
    p = os.path.join(ASSETS, "logo.png")
    if os.path.isfile(p):
        lab.setPixmap(QPixmap(p).scaledToHeight(height, Qt.SmoothTransformation))
    else:
        lab.setText("PINTEL")
    return lab


def label(text, name=None, wrap=False):
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def header(right_widget=None, left_extra=None):
    row = QHBoxLayout()
    row.addWidget(logo_label())
    if left_extra:
        row.addSpacing(28)
        row.addWidget(left_extra)
    row.addStretch(1)
    if right_widget:
        row.addWidget(right_widget)
    return row


def status_label(text, ok=True):
    lab = label(("● " if ok else "○ ") + text, "muted")
    lab.setStyleSheet(f"color: {C['okdot'] if ok else C['muted']}; font-size: 20px; font-weight: 600;")
    return lab


class Screen(QWidget):
    def __init__(self, gray=False):
        super().__init__()
        self.setObjectName("screen_gray" if gray else "screen")
        self.setAutoFillBackground(True)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(96, 56, 96, 48)
        self.root.setSpacing(28)


# ---------- 1. Ожидание ----------

class MainScreen(Screen):
    def __init__(self, point=""):
        super().__init__()
        self.point_label = label(f"Выкуп iPhone · {point}" if point else "Выкуп iPhone", "muted")
        self.root.addLayout(header(self.point_label))
        body = QHBoxLayout()
        body.setSpacing(96)
        left = QVBoxLayout()
        left.setSpacing(36)
        left.addStretch(1)
        left.addWidget(label("Узнайте, сколько стоит ваш iPhone", "h1", wrap=True))
        left.addWidget(label("Подключите телефон кабелем. Через две минуты вы увидите его состояние и цену, "
                             "за которую мы готовы выкупить его прямо сейчас.", "lead", wrap=True))
        for i, t in enumerate(("Подключите iPhone кабелем справа", "Разблокируйте и нажмите «Доверять»",
                               "Получите цену и решайте сами"), 1):
            r = QHBoxLayout()
            r.setSpacing(20)
            n = label(str(i), "num")
            n.setAlignment(Qt.AlignCenter)
            r.addWidget(n)
            r.addWidget(label(t, "step"))
            r.addStretch(1)
            left.addLayout(r)
        left.addStretch(1)
        body.addLayout(left, 1)
        self.card = ConnectCard()
        body.addWidget(self.card, 0, Qt.AlignVCenter)
        self.root.addLayout(body, 1)
        foot = QHBoxLayout()
        foot.addWidget(label("Телефон остаётся у вас. Ничего не устанавливаем, данные читаем только с вашего согласия.", "footer"))
        foot.addStretch(1)
        self.status = status_label("Готов к работе")
        foot.addWidget(self.status)
        self.root.addLayout(foot)

    def set_status(self, text, ok=True):
        self.status.setText(("● " if ok else "○ ") + text)
        self.status.setStyleSheet(f"color: {C['okdot'] if ok else C['bad']}; font-size: 20px; font-weight: 600;")

    def set_device(self, state):
        """wait | found | nodriver — состояние правой карточки."""
        self.card.set_state(state)


class ConnectCard(QFrame):
    """Правая часть экрана ожидания: тёмно-синяя карточка с кабелем и живым статусом."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(640, 640)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(52, 48, 52, 44)
        lay.setSpacing(16)
        self.kicker = label("ШАГ 1 ИЗ 3", "cardkicker")
        self.title = label("Подключите телефон кабелем", "cardtitle", wrap=True)
        lay.addWidget(self.kicker)
        lay.addWidget(self.title)
        self.art = QLabel()
        self.art.setPixmap(cable_pixmap())
        self.art.setAlignment(Qt.AlignCenter)
        self.art.setStyleSheet("background: transparent;")
        lay.addWidget(self.art, 1)
        self.text = label("Кабели Lightning и USB‑C — справа от экрана. Телефон остаётся у вас в руках.", "cardtext", wrap=True)
        lay.addWidget(self.text)
        self.status = label("●  ждём подключения", "cardstatus")
        lay.addWidget(self.status)
        self._blink = QTimer(self)
        self._blink.setInterval(700)
        self._blink.timeout.connect(self._tick)
        self._blink.start()
        self._on = True
        self.state = "wait"

    def _tick(self):
        if self.state != "wait":
            return
        self._on = not self._on
        self.status.setText(("●" if self._on else "○") + "  ждём подключения")

    def set_state(self, state):
        """wait | found | nodriver"""
        self.state = state
        if state == "found":
            self.kicker.setText("ШАГ 2 ИЗ 3")
            self.title.setText("Телефон найден")
            self.text.setText("Разблокируйте его и нажмите «Доверять» на экране телефона.")
            self.status.setText("●  подключён")
        elif state == "nodriver":
            self.kicker.setText("ТЕХНИЧЕСКАЯ ПАУЗА")
            self.title.setText("Киоск временно не принимает")
            self.text.setText("Подойдите к сотруднику — он проверит телефон на кассе.")
            self.status.setText("○  нет связи с кабелем")
        else:
            self.kicker.setText("ШАГ 1 ИЗ 3")
            self.title.setText("Подключите телефон кабелем")
            self.text.setText("Кабели Lightning и USB‑C — справа от экрана. Телефон остаётся у вас в руках.")
            self.status.setText("●  ждём подключения")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor("#1F5FB0"))
        g.setColorAt(1, QColor("#123C74"))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 48, 48)
        p.end()
        super().paintEvent(e)


def cable_pixmap(size=300):
    """Разъём и кабель — тонкими белыми линиями, без мультяшности."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    white = QColor(255, 255, 255)
    pen = QPen(white, 9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(QColor(255, 255, 255, 28))
    cx = size / 2
    # штекер
    p.drawRoundedRect(QRectF(cx - 46, 36, 92, 44), 22, 22)
    # корпус разъёма
    p.drawRoundedRect(QRectF(cx - 62, 80, 124, 96), 26, 26)
    # хвост кабеля — плавная кривая вниз
    path = QPainterPath()
    path.moveTo(cx, 176)
    path.cubicTo(cx, 240, cx - 110, 230, cx - 110, size - 20)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    # контакты штекера
    pen2 = QPen(QColor(255, 255, 255, 170), 5, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen2)
    for dx in (-18, 0, 18):
        p.drawLine(int(cx + dx), 48, int(cx + dx), 68)
    p.end()
    return pm


def phone_pixmap():
    pm = QPixmap(420, 560)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(C["text"]))
    p.drawRoundedRect(70, 10, 280, 500, 56, 56)
    p.setBrush(QColor("#FFFFFF"))
    p.drawRoundedRect(84, 24, 252, 472, 44, 44)
    p.setBrush(QColor(C["text"]))
    p.drawRoundedRect(160, 40, 100, 26, 13, 13)
    p.setBrush(QColor("#DCE6F0"))
    p.drawRoundedRect(118, 130, 184, 18, 9, 9)
    p.drawRoundedRect(118, 166, 140, 18, 9, 9)
    p.setBrush(QColor("#E8F4FB"))
    p.drawRoundedRect(118, 230, 184, 120, 20, 20)
    p.setBrush(QColor(C["primary"]))
    p.drawRoundedRect(190, 496, 40, 36, 8, 8)
    p.drawEllipse(184, 264, 52, 52)
    p.setPen(QColor(C["primary"]))
    p.setBrush(Qt.NoBrush)
    from PySide6.QtGui import QPen
    pen = QPen(QColor(C["primary"]), 10, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(210, 532, 210, 556)
    pen = QPen(QColor("#FFFFFF"), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.drawLine(198, 290, 206, 298)
    p.drawLine(206, 298, 222, 280)
    p.end()
    return pm


# ---------- 2. Проверка ----------

STEPS = [("connect", "Подключение и доверие"), ("passport", "Модель, память, серийный номер"),
         ("battery", "Батарея: здоровье и циклы"), ("locks", "Блокировки: Найти iPhone, активация, корпоративный надзор"),
         ("apple", "История обслуживания от Apple"), ("sickw", "Проверка по базе IMEI"), ("upload", "Отправка на кассу")]


class StepRow(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("row")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(20)
        self.dot = QLabel("")
        self.dot.setObjectName("dot_wait")
        self.dot.setAlignment(Qt.AlignCenter)
        self.title = label(title, "rowtitle")
        self.state = label("", "rowstate")
        lay.addWidget(self.dot)
        lay.addWidget(self.title, 1)
        lay.addWidget(self.state)
        self.set("wait", "")

    def set(self, state, text):
        names = {"wait": ("dot_wait", ""), "run": ("dot_run", ""), "done": ("dot_done", "✓"),
                 "warn": ("dot_warn", "!"), "fail": ("dot_fail", "✕")}
        dn, glyph = names.get(state, ("dot_wait", ""))
        self.dot.setObjectName(dn)
        self.dot.setText(glyph)
        self.setObjectName("row_active" if state == "run" else "row")
        self.state.setObjectName("rowstate_active" if state == "run" else "rowstate")
        self.state.setText(text or {"wait": "следом", "run": "…", "done": "готово", "warn": "", "fail": ""}[state])
        self.setGraphicsEffect(None)
        self.setStyleSheet(self.styleSheet())           # перечитать QSS после смены objectName
        for w in (self.dot, self.state):
            w.setStyleSheet(w.styleSheet())


class ScanScreen(Screen):
    skip_requested = Signal()

    def __init__(self):
        super().__init__()
        self.device_label = status_label("Телефон подключён")
        self.root.addLayout(header(self.device_label))
        body = QHBoxLayout()
        body.setSpacing(72)
        left = QVBoxLayout()
        left.setSpacing(28)
        left.addWidget(label("Проверяем телефон", "h1s", wrap=True))
        self.lead = label("Не отключайте кабель. Обычно это занимает около минуты.", "lead", wrap=True)
        left.addWidget(self.lead)
        self.rows = {}
        col = QVBoxLayout()
        col.setSpacing(14)
        for key, title in STEPS:
            r = StepRow(title)
            self.rows[key] = r
            col.addWidget(r)
        left.addLayout(col)
        left.addStretch(1)
        body.addLayout(left, 1)
        self.panel = QFrame()
        self.panel.setObjectName("bluecard")
        self.panel.setFixedWidth(720)
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(48, 44, 48, 44)
        pl.setSpacing(22)
        pl.addWidget(label("ОДИН ШАГ НА ТЕЛЕФОНЕ", "bluekicker"))
        pl.addWidget(label("Откройте историю обслуживания — и Apple сама скажет, что менялось", "bluetitle", wrap=True))
        for i, t in enumerate(("Настройки → Основные", "Об этом устройстве", "Нажмите «Запчасти и история обслуживания»"), 1):
            pl.addWidget(label(f"{i}   {t}", "bluestep", wrap=True))
        pl.addStretch(1)
        pl.addWidget(label("Если раздел уже открыт — выйдите назад и зайдите снова. Мы ждём, пока вы это сделаете.", "bluenote", wrap=True))
        self.skip = QPushButton("Пропустить этот шаг")
        self.skip.setObjectName("skip")
        self.skip.setCursor(Qt.PointingHandCursor)
        self.skip.clicked.connect(self.skip_requested.emit)
        pl.addWidget(self.skip, 0, Qt.AlignLeft)
        body.addWidget(self.panel)
        self.root.addLayout(body, 1)
        self.show_prompt(False)

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


def card(kicker):
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(36, 32, 36, 32)
    lay.setSpacing(10)
    lay.addWidget(label(kicker, "kicker"))
    return f, lay


def line(text, colour=None):
    lab = label(("● " if colour else "") + text, "line", wrap=True)
    if colour:
        lab.setStyleSheet(f"color: {C['text']};")
        lab.setText(f'<span style="color:{colour}">●</span>  {text}')
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

    def __init__(self, currency="₸"):
        super().__init__(gray=True)
        self.currency = currency
        self.title = label("iPhone", "h1s")
        self.title.setStyleSheet("font-size: 34px;")
        self.sub = label("", "muted")
        self.sub.setStyleSheet("font-size: 24px; font-weight: 600; color: %s;" % C["muted"])
        left = QWidget()
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(28)
        ll.addWidget(self.title)
        ll.addWidget(self.sub)
        self.chip = label("Готовы выкупить", "chip_ok")
        self.root.addLayout(header(self.chip, left))
        body = QHBoxLayout()
        body.setSpacing(28)
        # цена
        self.price_card, pl = card("ЦЕНА ВЫКУПА СЕГОДНЯ")
        self.price_card.setFixedWidth(640)
        pl.setContentsMargins(48, 44, 48, 44)
        self.price = label("—", "price")
        self.price_note = label("", "pricenote", wrap=True)
        pl.addWidget(self.price)
        pl.addWidget(self.price_note)
        pl.addStretch(1)
        self.btn_sell = QPushButton("Продать")
        self.btn_sell.setObjectName("primary")
        self.btn_sell.setCursor(Qt.PointingHandCursor)
        self.btn_sell.clicked.connect(self.sell.emit)
        self.btn_look = QPushButton("Спасибо, просто смотрел")
        self.btn_look.setObjectName("secondary")
        self.btn_look.setCursor(Qt.PointingHandCursor)
        self.btn_look.clicked.connect(self.just_looking.emit)
        pl.addWidget(self.btn_sell)
        pl.addWidget(self.btn_look)
        body.addWidget(self.price_card)
        grid = QGridLayout()
        grid.setSpacing(24)
        self.c_bat, self.l_bat = card("БАТАРЕЯ")
        self.c_apple, self.l_apple = card("ЧТО ГОВОРИТ APPLE")
        self.c_locks, self.l_locks = card("БЛОКИРОВКИ И БАЗЫ")
        self.c_pass, self.l_pass = card("ПАСПОРТ")
        grid.addWidget(self.c_bat, 0, 0)
        grid.addWidget(self.c_apple, 0, 1)
        grid.addWidget(self.c_locks, 1, 0)
        grid.addWidget(self.c_pass, 1, 1)
        body.addLayout(grid, 1)
        self.root.addLayout(body, 1)
        self.footer = label("Цена предварительная: сотрудник осмотрит корпус и экран на месте. "
                            "Данные телефона мы не храним без вашего согласия.", "footer", wrap=True)
        self.root.addWidget(self.footer)

    def fill(self, rep, server=None):
        pas, bat, leg = rep.get("паспорт") or {}, rep.get("батарея") or {}, rep.get("правовой") or {}
        sk, sto, hist = rep.get("sickw") or {}, rep.get("память") or {}, rep.get("apple_история") or {}
        price, itog = rep.get("цена") or {}, rep.get("итог") or {}
        self.title.setText(pas.get("модель") or "iPhone")
        self.sub.setText(" · ".join(x for x in (f"{sto.get('объём_гб')} ГБ" if sto.get("объём_гб") else None,
                                                 pas.get("цвет"), f"iOS {pas.get('ios')}" if pas.get("ios") else None) if x))
        problem = itog.get("вердикт") == "ПРОБЛЕМНЫЙ"
        cur = price.get("валюта") or self.currency
        if problem:
            self.chip.setObjectName("chip_bad")
            self.chip.setText("Не сможем выкупить")
            self.price.setText("—")
            self.price_note.setText("Причина: " + (itog.get("почему") or "см. сотрудника") + ". Подойдите к сотруднику, он объяснит подробнее.")
            self.btn_sell.setVisible(False)
        elif price.get("цена"):
            self.chip.setObjectName("chip_ok" if itog.get("вердикт") in ("ИДЕАЛ", "ХОРОШИЙ") else "chip_warn")
            self.chip.setText("Готовы выкупить" if itog.get("вердикт") in ("ИДЕАЛ", "ХОРОШИЙ") else "Нужен осмотр сотрудника")
            self.price.setText(f"{int(price['цена']):,} {cur}".replace(",", " "))
            self.price_note.setText(price.get("основание") or "")
            self.btn_sell.setVisible(True)
            self.btn_sell.setText(f"Продать за {int(price['цена']):,} {cur}".replace(",", " "))
        else:
            self.chip.setObjectName("chip_warn")
            self.chip.setText("Цену назовёт сотрудник")
            self.price.setText("—")
            self.price_note.setText(price.get("основание") or "Для этой модели цена уточняется у сотрудника.")
            self.btn_sell.setVisible(True)
            self.btn_sell.setText("Узнать цену у сотрудника")
        self.chip.setStyleSheet(self.chip.styleSheet())
        # батарея
        clear_layout(self.l_bat)
        self.l_bat.addWidget(label("БАТАРЕЯ", "kicker"))
        h = bat.get("здоровье_%")
        row = QHBoxLayout()
        row.addWidget(label(f"{h} %" if h is not None else "—", "big"))
        st = ("хорошее состояние" if h is not None and h >= 85 else ("заметный износ" if h is not None else "не прочиталась"))
        sl = label(st, "line")
        sl.setStyleSheet(f"color: {C['ok'] if h is not None and h >= 85 else C['warntext']}; font-weight: 700;")
        row.addSpacing(14)
        row.addWidget(sl, 0, Qt.AlignBottom)
        row.addStretch(1)
        self.l_bat.addLayout(row)
        bar_bg = QLabel()
        bar_bg.setObjectName("bar_bg")
        bar_fg = QLabel(bar_bg)
        bar_fg.setObjectName("bar_fg" if (h or 0) >= 85 else "bar_fg_warn")
        bar_fg.setFixedHeight(14)
        self._bar = (bar_bg, bar_fg, h or 0)
        self.l_bat.addWidget(bar_bg)
        fake = bat.get("подделка") or []
        self.l_bat.addWidget(label(f"{bat.get('циклы') if bat.get('циклы') is not None else '?'} циклов · "
                                   + ("признаки неоригинальной батареи" if fake else "оригинальный аккумулятор Apple"),
                                   "pricenote", wrap=True))
        # Apple
        clear_layout(self.l_apple)
        self.l_apple.addWidget(label("ЧТО ГОВОРИТ APPLE", "kicker"))
        if hist:
            groups = {}
            for v in hist.values():
                groups.setdefault(v["деталь"], v)
            shown = 0
            for name, v in list(groups.items())[:5]:
                verb = _changed_verb(name)
                if v.get("меняли"):
                    self.l_apple.addWidget(line(f"{name} — {verb}, " + ("б/у деталь" if v.get("бу") else "деталь Apple, новая"), C["warn"] if not v.get("бу") else C["bad"]))
                else:
                    self.l_apple.addWidget(line(f"{name} — не {verb}", C["okdot"]))
                shown += 1
            self.l_apple.addWidget(label("Из раздела «Запчасти и история обслуживания» вашего телефона", "muted"))
        else:
            self.l_apple.addWidget(line("Раздел пока не открыт", C["warn"]))
            self.l_apple.addWidget(label("Откройте на телефоне Настройки → Основные → Об этом устройстве → "
                                         "«Запчасти и история обслуживания» — данные появятся здесь сами.",
                                         "pricenote", wrap=True))
        # блокировки
        clear_layout(self.l_locks)
        self.l_locks.addWidget(label("БЛОКИРОВКИ И БАЗЫ", "kicker"))
        blk = sk.get("в_чёрном_списке")
        self.l_locks.addWidget(line("Не в чёрном списке" if blk is False else ("В ЧЁРНОМ СПИСКЕ" if blk else "База IMEI не проверялась"),
                                    C["okdot"] if blk is False else (C["bad"] if blk else C["warn"])))
        mdm = leg.get("mdm")
        self.l_locks.addWidget(line("Без корпоративного надзора" if mdm is False else ("Корпоративный надзор (MDM)" if mdm else "Надзор уточнит сотрудник"),
                                    C["okdot"] if mdm is False else (C["bad"] if mdm else C["warn"])))
        fmi_on = leg.get("найти_iphone") == "включён" or sk.get("fmi_включён") is True
        self.l_locks.addWidget(line("«Найти iPhone» включён — выключите перед продажей" if fmi_on else "«Найти iPhone» выключен",
                                    C["warn"] if fmi_on else C["okdot"]))
        if leg.get("пароль"):
            self.l_locks.addWidget(line("Стоит пароль — попросим снять при продаже", C["warn"]))
        # паспорт
        clear_layout(self.l_pass)
        self.l_pass.addWidget(label("ПАСПОРТ", "kicker"))
        self.l_pass.addLayout(kv("Серийный номер", pas.get("серийник") or "?"))
        self.l_pass.addLayout(kv("IMEI", pas.get("imei") or "—"))
        self.l_pass.addLayout(kv("Память", f"{sto.get('объём_гб') or '?'} ГБ, свободно {int(sto.get('свободно_гб') or 0)}"))
        self.l_pass.addLayout(kv("Куплен (по базе)", sk.get("дата_покупки") or "—"))
        self.l_pass.addLayout(kv("Уже приносили", "да" if (server or {}).get("уже_приносили") else "нет"))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_bar()

    def showEvent(self, e):
        super().showEvent(e)
        self._fit_bar()

    def _fit_bar(self):
        b = getattr(self, "_bar", None)
        if b:
            bg, fg, h = b
            fg.setGeometry(0, 0, int(bg.width() * min(100, max(0, h)) / 100), 14)


# ---------- 4. Талон ----------

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
    p.setBrush(QColor(C["text"]))
    for y, row in enumerate(m):
        for x, v in enumerate(row):
            if v:
                p.drawRect(x * box, y * box, box, box)
    p.end()
    return pm


class TicketScreen(Screen):
    def __init__(self):
        super().__init__()
        self.sub = label("", "muted")
        self.root.addLayout(header(self.sub))
        body = QHBoxLayout()
        body.setSpacing(96)
        self.ticket = QFrame()
        self.ticket.setObjectName("ticket")
        self.ticket.setFixedSize(560, 640)
        tl = QVBoxLayout(self.ticket)
        tl.setContentsMargins(48, 48, 48, 48)
        tl.setSpacing(12)
        tl.addStretch(1)
        k = label("ВАШ НОМЕР", "ticketkicker")
        k.setAlignment(Qt.AlignCenter)
        tl.addWidget(k)
        self.num = label("—", "ticketnum")
        self.num.setAlignment(Qt.AlignCenter)
        tl.addWidget(self.num)
        self.note = label("Подойдите к сотруднику — он уже видит вашу оценку на своём экране", "ticketnote", wrap=True)
        self.note.setAlignment(Qt.AlignCenter)
        tl.addWidget(self.note)
        tl.addStretch(1)
        body.addWidget(self.ticket, 0, Qt.AlignVCenter)
        right = QVBoxLayout()
        right.setSpacing(30)
        right.addWidget(label("Пока идёте к кассе — два шага на телефоне", "h1s", wrap=True))
        self.steps_box = QVBoxLayout()
        self.steps_box.setSpacing(16)
        right.addLayout(self.steps_box)
        qrbox = QFrame()
        qrbox.setObjectName("qrbox")
        ql = QHBoxLayout(qrbox)
        ql.setContentsMargins(28, 22, 28, 22)
        ql.setSpacing(24)
        self.qr = QLabel()
        self.qr.setFixedSize(140, 140)
        ql.addWidget(self.qr)
        ql.addWidget(label("Хотите забрать оценку с собой? Отсканируйте — откроется страница с полным отчётом по этому телефону.", "line", wrap=True), 1)
        right.addWidget(qrbox)
        self.back_note = label("Экран вернётся к началу через 60 секунд или когда вы отключите телефон", "muted")
        right.addWidget(self.back_note)
        right.addStretch(1)
        body.addLayout(right, 1)
        self.root.addLayout(body, 1)

    def fill(self, rep, server, return_seconds):
        pas, leg, price = rep.get("паспорт") or {}, rep.get("правовой") or {}, rep.get("цена") or {}
        cur = price.get("валюта") or "₸"
        self.sub.setText(f"{pas.get('модель') or 'iPhone'}" + (f" · {int(price['цена']):,} {cur}".replace(",", " ") if price.get("цена") else ""))
        if server and server.get("номер"):
            self.num.setText(str(server["номер"]))
            self.note.setText("Подойдите к сотруднику — он уже видит вашу оценку на своём экране")
        else:
            self.num.setText("—")
            self.note.setText("Связи с кассой сейчас нет. Подойдите к сотруднику, оценка сохранена на этом киоске")
        clear_layout(self.steps_box)
        steps = []
        if leg.get("найти_iphone") == "включён":
            steps.append(("Выключите «Найти iPhone»", "Настройки → ваше имя → Локатор → Найти iPhone → выключить. Понадобится пароль Apple ID."))
        steps.append(("Сделайте резервную копию, если нужна", "Перед выкупом телефон будет стёрт. Сотрудник поможет перенести данные на новый."))
        if pas.get("esim"):
            steps.append(("Удалите eSIM при стирании", "Телефон предложит удалить профиль eSIM — согласитесь, чтобы номер не остался на чужом аппарате."))
        for i, (t, d) in enumerate(steps, 1):
            f = QFrame()
            f.setObjectName("row")
            lay = QHBoxLayout(f)
            lay.setContentsMargins(28, 24, 28, 24)
            lay.setSpacing(22)
            n = label(str(i), "num")
            n.setAlignment(Qt.AlignCenter)
            lay.addWidget(n, 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(6)
            col.addWidget(label(t, "step"))
            dl = label(d, "pricenote", wrap=True)
            col.addWidget(dl)
            lay.addLayout(col, 1)
            self.steps_box.addWidget(f)
        url = (server or {}).get("ссылка_отчёта")
        pm = qr_pixmap(url, 140) if url else None
        if pm:
            self.qr.setPixmap(pm.scaled(140, 140, Qt.KeepAspectRatio, Qt.FastTransformation))
            self.qr.setVisible(True)
        else:
            self.qr.setVisible(False)
        self.back_note.setText(f"Экран вернётся к началу через {return_seconds} секунд или когда вы отключите телефон")
