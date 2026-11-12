# -*- coding: utf-8 -*-
"""Привязка сделки к сотруднику — первый экран после ожидания, до анкеты и до кабеля.

Сотрудник сканирует QR своим телефоном, ссылка открывает бота Оценки, и бот запоминает,
чья это сделка. Дальше всё, что раньше требовало второго QR, идёт само: когда на кассе
нажмут «Отправить на оценку», бот напишет ЭТОМУ сотруднику «пришлите фото и видео» и после
них создаст сделку. Ему же придёт карточка с кнопками «Выкуп» и «Закрыть» — и ему же
начислится бонус.

Почему в начале, а не в конце: в конце у сотрудника в одной руке телефон клиента, в другой
свой, а на экране кассы ещё три дела. В начале руки свободны, и вопрос «кто оценивает»
решён до того, как клиент отдал аппарат.

Экран спрашивает одно и ничего не требует набирать. Привязка пришла — показываем имя и
сами идём дальше; сервер не видит бота — говорим это словами и даём продолжить по-старому
(QR для медиа появится на шаге фото и видео), потому что касса не должна вставать из-за
того, что мы чего-то не видим.
"""
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from .ui import (C, FONT_HEAD, FONT_NUM, FONT_TEXT, QrBlock, Screen, W, font, kicker, label,
                 logo_label, point_text, qr_pixmap, Успех)
from .ui_deal import QSS_DEAL, _кнопка

ШАГИ = ("Откройте камеру на своём телефоне",
        "Наведите на код — откроется бот Оценки",
        "Нажмите в боте «Старт»")
# сколько держим на экране «Привязано», прежде чем уйти на анкету: успеть прочитать имя
ПОКАЗАТЬ_ИМЯ_МС = 1100
# после стольких секунд без ответа предлагаем продолжить без привязки
ТЕРПЕНИЕ_С = 25


class Маяк(QWidget):
    """Ждём сканирование: три кольца расходятся от точки. Привязано — стоит галочка.

    Движение тут не украшение: на экране, где ничего не надо нажимать, оно говорит, что
    касса жива и ждёт именно действия на телефоне."""

    def __init__(self, сторона=64):
        super().__init__()
        self.s = int(сторона)
        self.setFixedSize(self.s, self.s)
        self.цвет, self.живой = QColor(C["cyan"]), True
        self.таймер = QTimer(self)
        self.таймер.setInterval(40)
        self.таймер.timeout.connect(self.update)

    def set(self, цвет, живой=True):
        self.цвет, self.живой = QColor(цвет), bool(живой)
        if self.живой and self.isVisible():
            self.таймер.start()
        else:
            self.таймер.stop()
        self.update()

    def showEvent(self, e):                                      # noqa: N802 — имя от Qt
        super().showEvent(e)
        if self.живой:
            self.таймер.start()

    def hideEvent(self, e):                                      # noqa: N802
        super().hideEvent(e)
        self.таймер.stop()

    def paintEvent(self, e):                                     # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ц = QPointF(self.s / 2, self.s / 2)
        if self.живой:
            t = time.monotonic()
            for сдвиг in (0.0, 0.33, 0.66):
                k = (t * 0.55 + сдвиг) % 1.0
                кольцо = QColor(self.цвет)
                кольцо.setAlphaF(0.42 * (1.0 - k))
                p.setPen(QPen(кольцо, 2.5))
                p.setBrush(Qt.NoBrush)
                r = 7 + (self.s / 2 - 9) * k
                p.drawEllipse(ц, r, r)
        p.setPen(Qt.NoPen)
        p.setBrush(self.цвет)
        p.drawEllipse(ц, 7, 7)


class Витрина(QWidget):
    """Плитка под QR: белая, с мягким светом по краю — код на ней главный на экране."""

    def __init__(self, код: QrBlock):
        super().__init__()
        сл = QVBoxLayout(self)
        сл.setContentsMargins(34, 34, 34, 22)
        сл.addWidget(код, 0, Qt.AlignHCenter)
        self.фаза = 0.0
        self.таймер = QTimer(self)
        self.таймер.setInterval(50)
        self.таймер.timeout.connect(self._тик)
        self.готово = False

    def _тик(self):
        self.фаза = time.monotonic()
        self.update()

    def set_готово(self, да):
        self.готово = bool(да)
        self.update()

    def showEvent(self, e):                                      # noqa: N802
        super().showEvent(e)
        self.таймер.start()

    def hideEvent(self, e):                                      # noqa: N802
        super().hideEvent(e)
        self.таймер.stop()

    def paintEvent(self, e):                                     # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        # дыхание света: едва заметное, чтобы плитка не выглядела картинкой
        сила = 0.5 + 0.5 * math.sin(self.фаза * 1.6)
        цвет = QColor(C["okdot"] if self.готово else C["glow"])
        свет = QRadialGradient(r.center(), max(r.width(), r.height()) * 0.72)
        ближе, дальше = QColor(цвет), QColor(цвет)
        ближе.setAlphaF(0.16 + 0.07 * сила)
        дальше.setAlphaF(0.0)
        свет.setColorAt(0.55, ближе)
        свет.setColorAt(1.0, дальше)
        p.setPen(Qt.NoPen)
        p.setBrush(свет)
        p.drawRoundedRect(QRectF(self.rect()), 44, 44)
        путь = QPainterPath()
        путь.addRoundedRect(r, 34, 34)
        p.fillPath(путь, QColor(C["card_hi"]))
        рамка = QColor(цвет)
        рамка.setAlphaF(0.55 if self.готово else 0.30)
        p.setPen(QPen(рамка, 2))
        p.drawPath(путь)


class LinkScreen(Screen):
    """Чья сделка: QR слева, три шага и состояние справа."""

    готово = Signal(str)            # привязано — имя сотрудника; идём на анкету
    без_привязки = Signal()         # сервер не видит бота — работаем по-старому
    отмена = Signal()
    новый_код = Signal()

    def __init__(self, point=""):
        super().__init__(gray=True)
        self.setStyleSheet(QSS_DEAL)
        self.root.setContentsMargins(56, 30, 56, 30)
        self.root.setSpacing(0)
        self.имя, self.привязан, self._начали = "", False, 0.0

        шапка = QHBoxLayout()
        шапка.setSpacing(16)
        шапка.addWidget(logo_label(42))
        шапка.addWidget(label("Новая оценка", font_=font(FONT_HEAD, 26, W.DemiBold)), 1)
        self.точка = label(point_text(point), font_=font(FONT_TEXT, 17, W.Medium), color=C["muted"])
        шапка.addWidget(self.точка)
        self.root.addLayout(шапка)
        self.root.addStretch(2)

        пара = QHBoxLayout()
        пара.setSpacing(84)
        пара.addStretch(1)

        # --- слева: код
        self.qr = QrBlock(400)
        self.витрина = Витрина(self.qr)
        пара.addWidget(self.витрина, 0, Qt.AlignVCenter)

        # --- справа: что сделать и что происходит
        право = QVBoxLayout()
        право.setSpacing(0)
        право.addWidget(kicker("ШАГ 1 ИЗ 2 · ДО КАБЕЛЯ", 14, 2.4, C["brand"]))
        право.addSpacing(12)
        self.заголовок = label("Кто оценивает?", font_=font(FONT_HEAD, 54, W.Bold))
        право.addWidget(self.заголовок)
        право.addSpacing(10)
        self.подзаголовок = label(
            "Отсканируйте код своим телефоном — сделка привяжется к вам в боте Оценки.",
            wrap=True, font_=font(FONT_TEXT, 22, W.Medium), color=C["muted"])
        self.подзаголовок.setFixedWidth(620)
        право.addWidget(self.подзаголовок)
        право.addSpacing(34)
        for n, текст in enumerate(ШАГИ, 1):
            строка = QHBoxLayout()
            строка.setSpacing(18)
            номер = label(str(n), font_=font(FONT_NUM, 26, W.Bold), color=C["cyan"])
            номер.setFixedWidth(30)
            строка.addWidget(номер)
            строка.addWidget(label(текст, font_=font(FONT_TEXT, 25, W.DemiBold)), 1)
            право.addLayout(строка)
            право.addSpacing(14)
        право.addSpacing(22)

        # состояние: маяк и одна строка. Высота закреплена: галочка крупнее маяка, и без
        # этого строка прыгала бы в момент привязки
        состояние = QHBoxLayout()
        состояние.setSpacing(18)
        self.маяк = Маяк(64)
        self.успех = Успех(64)
        self.успех.hide()
        состояние.addWidget(self.маяк)
        состояние.addWidget(self.успех)
        слова = QVBoxLayout()
        слова.setSpacing(2)
        self.статус = label("Ждём сканирование…", font_=font(FONT_TEXT, 26, W.Bold))
        self.статус_подпись = label("Дальше касса перейдёт сама.", wrap=True,
                                    font_=font(FONT_TEXT, 18, W.Medium), color=C["muted"])
        self.статус_подпись.setFixedWidth(520)
        слова.addWidget(self.статус)
        слова.addWidget(self.статус_подпись)
        состояние.addLayout(слова, 1)
        блок = QWidget()
        блок.setLayout(состояние)
        блок.setFixedHeight(88)
        право.addWidget(блок)

        обёртка = QWidget()
        обёртка.setLayout(право)
        обёртка.setFixedWidth(640)
        пара.addWidget(обёртка, 0, Qt.AlignVCenter)
        пара.addStretch(1)
        self.root.addLayout(пара)
        self.root.addStretch(3)

        низ = QHBoxLayout()
        низ.setSpacing(16)
        self.b_отмена = _кнопка("Отменить", "ghost")
        self.b_отмена.clicked.connect(self.отмена.emit)
        self.b_код = _кнопка("Другой код", "small")
        self.b_код.clicked.connect(self.новый_код.emit)
        self.b_без = _кнопка("Продолжить без привязки", "ghost")
        self.b_без.clicked.connect(self.без_привязки.emit)
        self.b_без.hide()
        низ.addWidget(self.b_отмена)
        низ.addWidget(self.b_код)
        низ.addStretch(1)
        низ.addWidget(self.b_без)
        self.root.addLayout(низ)

        self._уход = QTimer(self)
        self._уход.setSingleShot(True)
        self._уход.timeout.connect(lambda: self.готово.emit(self.имя))
        self.начать()

    # ---------- состояния ----------
    def начать(self):
        """Новая сделка: никто не привязан, ждём сканирование."""
        self._уход.stop()
        self.имя, self.привязан, self._начали = "", False, time.monotonic()
        self.витрина.set_готово(False)
        self.успех.hide()
        self.маяк.show()
        self.маяк.set(C["cyan"], True)
        self.заголовок.setText("Кто оценивает?")
        self._сказать("Ждём сканирование…", "Дальше касса перейдёт сама.", C["ink"])
        self.b_без.hide()
        self.b_код.show()

    def set_point(self, point):
        self.точка.setText(point_text(point))

    def показать_код(self, код, ссылка):
        """QR со ссылкой на бота. Ссылки нет (в кассе не задан бот) — привязывать не к чему:
        говорим это и даём работать по-старому."""
        if not ссылка:
            self.qr.set(None, "", False)
            self.маяк.set(C["warn"], False)
            self._сказать("В кассе не задан бот Оценки",
                          "Привязать сделку не к чему — продолжайте без привязки.", C["warntext"])
            self.b_без.show()
            self.b_код.hide()
            return
        self.qr.set(qr_pixmap(ссылка, 400), str(код or ""), True)
        self.qr.play()

    def _сказать(self, текст, подпись, цвет):
        self.статус.setText(текст)
        self.статус.setStyleSheet(f"color: {цвет}")
        self.статус_подпись.setText(подпись)

    def set_состояние(self, состояние):
        """Ответ сервера по коду обмена: открыл ли кто-нибудь ссылку и кто именно."""
        if self.привязан or not isinstance(состояние, dict):
            return
        if состояние.get("известно") and состояние.get("начали"):
            self._привязано(str(состояние.get("сотрудник") or "").strip())
            return
        if not состояние.get("известно"):
            # Сервер не смог посмотреть: это не «никто не сканировал». Не держим кассу —
            # сотрудник мог отсканировать, а мы просто не видим.
            self.маяк.set(C["warn"], True)
            self._сказать("Касса не видит бота",
                          str(состояние.get("почему") or "сервер не ответил").capitalize()
                          + ". Можно продолжить: код для фото и видео появится позже.",
                          C["warntext"])
            self.b_без.show()
            return
        self.маяк.set(C["cyan"], True)
        if time.monotonic() - self._начали > ТЕРПЕНИЕ_С:
            self._сказать("Ждём сканирование…",
                          "Бот не открывается? Проверьте интернет на телефоне или возьмите "
                          "другой код.", C["ink"])
        else:
            self._сказать("Ждём сканирование…", "Дальше касса перейдёт сама.", C["ink"])

    def _привязано(self, имя):
        self.привязан, self.имя = True, имя
        self.витрина.set_готово(True)
        self.маяк.hide()
        self.успех.show()
        self.b_без.hide()
        self.b_код.hide()
        self._сказать("Привязано" + (f": {имя}" if имя else ""),
                      "Фото и видео бот попросит у вас сам — в конце.", C["ok"])
        self._уход.start(ПОКАЗАТЬ_ИМЯ_МС)
