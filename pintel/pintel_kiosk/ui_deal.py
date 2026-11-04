# -*- coding: utf-8 -*-
"""Рабочее окно сотрудника: проверка, сделка и медиа на одном экране.

За экраном работает сотрудник, а не клиент: он вводит имя и телефон, ставит цену и
сканирует QR своим телефоном. Поэтому окно одно и плотное — шесть экранов на сделку он
проходил бы по десять раз в день.

Три колонки: слева идёт проверка и её итог, в середине — сделка, справа — то, что нужно
прямо сейчас: сначала шаг с разделом Apple на телефоне, потом QR для медиа, потом
подтверждение отправки. Имя клиента можно записывать, пока читается телефон.

Поля сделки — ровно те, что хранит Оценка. Фото и видео приложение не видит вовсе: их
принимает бот по коду с этого экрана, он же проверяет видео и создаёт сделку.

Ручные проверки (кнопки, вибрация, SIM, герметик) отмечают здесь же, на экране: телефон
клиента лежит на столе рядом с кассой, а не рядом с чатом. Раньше их спрашивал бот
кнопками — восемь нажатий в Telegram с аппаратом в руках были лишним шагом, на котором
ещё и ошибались. Отметки уезжают в сделку посылкой, и бот кладёт их в карточку как есть.
"""
import re

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLineEdit,
                               QPushButton, QSizePolicy, QStackedWidget, QTextEdit, QVBoxLayout,
                               QWidget)

from pintel_core import phonetest
from pintel_core.external import ocenka_media

from .ui import (C, FONT_HEAD, FONT_NUM, FONT_TEXT, QrBlock, Screen, StepRow, STEPS, W, font,
                 kicker, label, point_text, qr_pixmap)

QSS_DEAL = """
QLineEdit, QComboBox, QTextEdit { background: #FFFFFF; border: 2px solid %(border)s; border-radius: 14px;
    padding: 11px 15px; font-size: 21px; color: %(ink)s; selection-background-color: %(tint)s; }
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border-color: %(action)s; }
QLineEdit[плохо="да"] { border-color: %(bad)s; }
QComboBox::drop-down { border: none; width: 38px; }
QCheckBox { font-size: 21px; font-weight: 600; spacing: 12px; }
QCheckBox::indicator { width: 26px; height: 26px; border: 2px solid %(ring)s; border-radius: 8px;
    background: #FFFFFF; }
QCheckBox::indicator:checked { background: %(action)s; border-color: %(action)s; }
QPushButton#ghost { background: transparent; color: %(body)s; border: 2px solid %(border)s;
    border-radius: 14px; font-size: 21px; font-weight: 700; min-height: 56px; padding: 0 28px; }
QPushButton#ghost:pressed { background: %(ground)s; }
QPushButton#ghost:disabled { color: %(ghost)s; border-color: %(border)s; }
QPushButton#primary:disabled { background: %(ghost)s; }
QPushButton#small { background: %(tint)s; color: %(brand)s; border: none; border-radius: 12px;
    font-size: 19px; font-weight: 700; min-height: 48px; padding: 0 22px; }
QFrame#карточка { background: #FFFFFF; border: 2px solid %(border)s; border-radius: 20px; }
""" % C

СОСТОЯНИЕ = {"ok": ("оригинальная", C["ok"]), "repaired": ("меняли, оригинал Apple", C["warntext"]),
             "used": ("б/у деталь", C["warntext"]), "bad": ("не подтверждена", C["badtext"])}

# Страницы правой колонки. Раньше индексы стояли числами в семи местах, и добавить между ними
# ещё одну страницу было нельзя, не переставив все.
СТР_APPLE, СТР_ТЕСТ, СТР_РУЧНАЯ, СТР_МЕДИА, СТР_ГОТОВО = 0, 1, 2, 3, 4
# как показываем ответ теста: значок, цвет, подпись
ВИД_ОТВЕТА = {phonetest.ОК: ("✓", C["ok"], "в порядке"),
              phonetest.ПЛОХО: ("✗", C["badtext"], "не прошёл"),
              phonetest.ПРОПУСК: ("—", C["warntext"], "не проверили"),
              None: ("·", C["ghost"], "ждём")}


def нормальный_телефон(текст):
    """«8 705 883 79 53» → «+77058837953». Пусто — значит не разобрали."""
    цифры = re.sub(r"\D", "", str(текст or ""))
    if len(цифры) == 11 and цифры[0] in "78":
        цифры = "7" + цифры[1:]
    elif len(цифры) == 10:
        цифры = "7" + цифры
    else:
        return ""
    return "+" + цифры


# Размеры надписей кнопок. Те же числа стоят в QSS (там они красят), но ширину кнопки Qt
# считает по шрифту самого виджета: пока он оставался шрифтом приложения, «Отправить в
# Оценку» не помещалась в кнопку и вылезала за её край.
РАЗМЕР_КНОПКИ = {"primary": 28, "ghost": 21, "small": 19}


def _кнопка(текст, вид="primary"):
    b = QPushButton(текст)
    b.setObjectName(вид)
    b.setCursor(Qt.PointingHandCursor)
    b.setFont(font(FONT_TEXT, РАЗМЕР_КНОПКИ.get(вид, 21), W.Bold))
    return b


def _плашка(текст, фон, цвет):
    l = label(текст, font_=font(FONT_TEXT, 20, W.Bold))
    l.setStyleSheet(f"background: {фон}; color: {цвет}; border-radius: 16px; padding: 7px 18px;")
    return l


# Подсказка под QR теста. Две строки, не три: карточка плотная — семь строк результата,
# QR, код и кнопки, — и лишняя строка здесь выталкивает нижние виджеты друг на друга.
ПОДСКАЗКА_МЕДИА = ("Сканируйте телефоном сотрудника: бот проведёт по шагам. "
                   "Кто прислал — тот и оценщик.")
# Короткая строка намеренно: ниже семь строк результата, а каждая лишняя строка текста
# отнимает высоту у них и у QR этой же карточки.
ПОДСКАЗКА_ТЕСТА = "Клиент сканирует QR телефоном, который сдаёт."

# Вид пункта по ответу: подпись состояния, цвет текста, фон и рамка ряда.
ВИД_ПУНКТА = {None: ("не отмечено", C["muted"], "#FFFFFF", C["border"]),
              True: ("работает", C["ok"], C["okbg"], C["ok"]),
              False: ("НЕ работает", C["badtext"], C["badbg"], C["bad"])}


class Отметка(QWidget):
    """Квадратик состояния: пусто · галочка · крест. Рисуется, а не набирается значком.

    Эмодзи ⬜✅❌ выглядели на экране точки чужеродно — у них своя палитра, свой размер и
    своя насечка, не те, что у остального окна. Здесь те же три состояния нарисованы теми
    же цветами, что и весь интерфейс, и одинаково на любой машине: шрифт с эмодзи на
    Windows может оказаться другим, а рисунок — нет.
    """

    def __init__(self, сторона=26):
        super().__init__()
        self.сторона = int(сторона)
        self.ответ = None
        self.setFixedSize(self.сторона, self.сторона)

    def set(self, ответ):
        self.ответ = ответ
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        с = self.сторона
        поле = QRectF(1, 1, с - 2, с - 2)
        цвет = {True: C["ok"], False: C["bad"]}.get(self.ответ)
        p.setPen(QPen(QColor(цвет or C["ring"]), 2))
        p.setBrush(QColor(цвет) if цвет else QColor("#FFFFFF"))
        p.drawRoundedRect(поле, 7, 7)
        if self.ответ is None:
            return
        p.setPen(QPen(QColor("#FFFFFF"), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if self.ответ:                       # галочка
            p.drawPolyline([поле.topLeft() + QPointF(5, с * 0.52),
                            поле.topLeft() + QPointF(с * 0.40, с * 0.72),
                            поле.topLeft() + QPointF(с - 9, с * 0.28)])
        else:                                # крест
            k = с * 0.30
            p.drawLine(поле.topLeft() + QPointF(k, k), поле.bottomRight() - QPointF(k, k))
            p.drawLine(поле.topRight() + QPointF(-k, k), поле.bottomLeft() + QPointF(k, -k))


class ПунктРяд(QFrame):
    """Один пункт ручной проверки: квадратик состояния, название и чем его проверить.

    Нажатие по всему ряду, а не по маленькому квадратику: сотрудник держит телефон клиента
    в одной руке. Состояний три — не отмечено, работает, не работает, — и «не проверял»
    среди них нет намеренно: нечем проверить значит «не работает», и сделку смотрит человек.
    Состояние говорится и словами справа: по одному цвету его читать нельзя.
    """

    нажали = Signal(str)

    def __init__(self, ключ, имя, подробно):
        super().__init__()
        self.ключ = ключ
        # имя объекта и селектор по нему: иначе рамка и фон достаются и подписям внутри —
        # стиль QFrame без селектора наследуется всеми детьми
        self.setObjectName("checkrow")
        self.setCursor(Qt.PointingHandCursor)
        # MinimumExpanding: свободную высоту карточки забирают сами ряды, а не пустота под
        # ними — иначе длинная подпись («Детали и обслуживание…») обрезается на первой строке
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        self.setMinimumHeight(54)
        ряд = QHBoxLayout(self)
        ряд.setContentsMargins(12, 5, 12, 5)
        ряд.setSpacing(10)
        self.значок = Отметка()
        текст = QVBoxLayout()
        текст.setContentsMargins(0, 0, 0, 0)
        текст.setSpacing(0)
        # Состояние словами — в одну строку с названием, а не отдельной колонкой справа:
        # колонка съедала ширину у подписи, и та обрывалась на полуслове.
        верх = QHBoxLayout()
        верх.setContentsMargins(0, 0, 0, 0)
        верх.setSpacing(8)
        self.имя = label(имя, font_=font(FONT_TEXT, 18, W.Bold))
        self.состояние = label("", font_=font(FONT_TEXT, 15, W.Bold))
        верх.addWidget(self.имя)
        верх.addWidget(self.состояние)
        верх.addStretch(1)
        текст.addLayout(верх)
        self.подробно = label(подробно, "muted", wrap=True, font_=font(FONT_TEXT, 13))
        текст.addWidget(self.подробно)
        ряд.addWidget(self.значок, 0, Qt.AlignVCenter)
        ряд.addLayout(текст, 1)
        # Нажимают по всей строке, поэтому её содержимое мышь не ловит вовсе
        for внутри in (self.значок, self.имя, self.состояние, self.подробно):
            внутри.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.set(None)

    def set(self, ответ):
        подпись, цвет, фон, рамка = ВИД_ПУНКТА.get(ответ, ВИД_ПУНКТА[None])
        self.значок.set(ответ)
        self.setStyleSheet(f"QFrame#checkrow {{ background: {фон}; border: 2px solid {рамка}; "
                           "border-radius: 14px; }")
        self.имя.setStyleSheet(f"color: {цвет if ответ is not None else C['ink']}")
        self.состояние.setText(подпись if ответ is not None else "")
        self.состояние.setStyleSheet(f"color: {цвет}")

    def mousePressEvent(self, e):
        """Принять нажатие обязательно, иначе отметки не ставятся вовсе.

        Qt отдаёт `mouseReleaseEvent` только тому виджету, который принял нажатие, а
        `QWidget.mousePressEvent` по умолчанию его отклоняет — нажатие уходило родителю, и
        отпускание до ряда уже не доходило. На экране это выглядело так, будто строки
        мёртвые."""
        if e.button() == Qt.LeftButton:
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        # Палец увели со строки, не отпуская, — это не нажатие, а передумали
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.нажали.emit(self.ключ)
            e.accept()
            return
        super().mouseReleaseEvent(e)


def _карточка(заголовок):
    """Колонка-карточка с заголовком: внутрь кладут содержимое."""
    рамка = QFrame()
    рамка.setObjectName("карточка")
    рамка.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
    внутри = QVBoxLayout(рамка)
    внутри.setContentsMargins(26, 22, 26, 22)
    внутри.setSpacing(12)
    внутри.addWidget(kicker(заголовок, 15, 2.4, C["brand"]))
    return рамка, внутри


class WorkScreen(Screen):
    """Всё, что делает сотрудник после «Начать оценку»."""

    отправить = Signal(dict)
    печать = Signal()
    заново = Signal()
    пропустить_apple = Signal()
    новый_код = Signal()
    новый_тест = Signal()                 # другой одноразовый код для теста на телефоне
    пропустить_тест = Signal()            # телефона нет в нашей сети — сделка уйдёт человеку
    перепроверить = Signal()              # прочитать телефон заново, не брать прошлую проверку

    def __init__(self, point=""):
        super().__init__(gray=True)
        self.setStyleSheet(QSS_DEAL)
        self.rep, self.готово, self.отправлено = {}, False, False
        # результат теста на телефоне клиента: пока его нет, сделку отправить нельзя
        self.тест, self.тест_пропущен = {}, ""
        # ручные проверки сотрудника: отмечаются здесь, на экране, и едут в сделку посылкой
        self.ручная = {}
        # что дошло до бота: фото, видео, отметки диагностики. Пустой словарь — ещё не
        # спрашивали; {"известно": False} — спросили, но сервер не смог посмотреть
        self.медиа_состояние = {}
        self.root.setContentsMargins(56, 40, 56, 36)

        шапка = QHBoxLayout()
        шапка.setSpacing(16)
        self.аппарат = label("Подключите телефон кабелем", font_=font(FONT_TEXT, 22, W.Bold))
        # состояние, выбранное сотрудником до диагностики — кнопка Оценки; проверка может его
        # изменить, и тогда здесь же видно, на что и почему
        self.состояние = _плашка("", C["tint"], C["brand"])
        self.состояние.setWordWrap(True)
        self.состояние.hide()
        self.точка = label(point_text(point), "muted")
        шапка.addWidget(self.аппарат, 1)
        шапка.addWidget(self.состояние, 2)
        шапка.addWidget(self.точка)
        self.root.addLayout(шапка)

        self.плашки = QHBoxLayout()
        self.плашки.setSpacing(12)
        self.плашки.addStretch(1)
        self.root.addSpacing(14)
        self.root.addLayout(self.плашки)

        тело = QHBoxLayout()
        тело.setSpacing(22)
        # Правая колонка шире прежнего: в ней живут восемь строк проверок руками с
        # подсказками, и на узкой колонке подписи обрезались на полуслове.
        тело.addWidget(self._проверка(), 100)
        тело.addWidget(self._сделка(), 92)
        тело.addWidget(self._справа(), 93)
        self.root.addSpacing(18)
        self.root.addLayout(тело, 1)

        self.ошибка = label("", wrap=True, color=C["badtext"])
        self.root.addSpacing(10)
        self.root.addWidget(self.ошибка)
        низ = QHBoxLayout()
        низ.setSpacing(14)
        self.b_отмена = _кнопка("Отменить", "ghost")
        self.b_отмена.clicked.connect(self.заново.emit)
        self.b_печать = _кнопка("Печать чека", "ghost")
        self.b_печать.clicked.connect(self.печать.emit)
        self.b_отправить = _кнопка("Отправить в Оценку")
        self.b_отправить.clicked.connect(self._отправить)
        низ.addWidget(self.b_отмена)
        низ.addStretch(1)
        низ.addWidget(self.b_печать)
        низ.addWidget(self.b_отправить)
        self.root.addSpacing(16)
        self.root.addLayout(низ)
        self.начать()

    # ---------- колонки ----------
    def _проверка(self):
        рамка, внутри = _карточка("ПРОВЕРКА")
        self.стопка = QStackedWidget()
        шаги = QWidget()
        сл = QVBoxLayout(шаги)
        сл.setContentsMargins(0, 0, 0, 0)
        сл.setSpacing(10)
        self.шаги = {}
        for ключ, имя in STEPS:
            r = StepRow(имя)
            self.шаги[ключ] = r
            сл.addWidget(r)
        self.подсказка = label("Не отключайте кабель. Обычно это занимает около минуты.", "muted", wrap=True)
        сл.addSpacing(6)
        сл.addWidget(self.подсказка)
        сл.addStretch(1)
        итог = QWidget()
        ил = QVBoxLayout(итог)
        ил.setContentsMargins(0, 0, 0, 0)
        ил.setSpacing(0)
        self.итоги = QGridLayout()
        self.итоги.setHorizontalSpacing(16)
        self.итоги.setVerticalSpacing(0)
        self.итоги.setColumnStretch(0, 1)
        ил.addLayout(self.итоги)
        ил.addStretch(1)
        # Проверку могли взять готовой, прошлую (этот же телефон приносили час назад). Это
        # обязано быть видно словами, и выход должен быть рядом: кнопка читает телефон заново.
        self.повтор_текст = label("", wrap=True, color=C["warntext"])
        self.повтор_текст.hide()
        ил.addWidget(self.повтор_текст)
        self.b_перепроверить = _кнопка("Проверить телефон заново", "small")
        self.b_перепроверить.clicked.connect(self.перепроверить.emit)
        self.b_перепроверить.hide()
        ил.addSpacing(8)
        ил.addWidget(self.b_перепроверить, 0, Qt.AlignLeft)
        self.стопка.addWidget(шаги)
        self.стопка.addWidget(итог)
        внутри.addWidget(self.стопка, 1)
        return рамка

    def _сделка(self):
        рамка, внутри = _карточка("СДЕЛКА")
        сетка = QGridLayout()
        сетка.setHorizontalSpacing(12)
        сетка.setVerticalSpacing(6)
        self.имя = QLineEdit()
        self.имя.setPlaceholderText("Имя клиента")
        self.телефон = QLineEdit()
        self.телефон.setPlaceholderText("+7 7XX XXX XX XX")
        for столбец, (подпись, поле) in enumerate((("ИМЯ", self.имя), ("ТЕЛЕФОН", self.телефон))):
            поле.textChanged.connect(self._проверить)
            сетка.addWidget(kicker(подпись, 13, 2.0), 0, столбец)
            сетка.addWidget(поле, 1, столбец)
        внутри.addLayout(сетка)

        ряд = QHBoxLayout()
        ряд.setSpacing(20)
        self.коробка = QCheckBox("Коробка")
        self.шнур = QCheckBox("Шнур")
        self.sim = QComboBox()
        self.sim.addItems(["Стандарт", "Dual sim", "E-sim", "Прочее"])
        ряд.addWidget(self.коробка)
        ряд.addWidget(self.шнур)
        ряд.addWidget(self.sim, 1)
        внутри.addSpacing(6)
        внутри.addLayout(ряд)
        # SIM кассе не надо спрашивать: лоток и eSIM видно по кабелю (SIMTrayStatus, профиль
        # eSIM, второй IMEI). Пишем, откуда взялось значение, — иначе сотрудник не понимает,
        # его это выбор или уже определённый, и правит наугад.
        self.sim_подпись = label("", "muted", wrap=True)
        внутри.addWidget(self.sim_подпись)

        внутри.addSpacing(6)
        внутри.addWidget(label("Цену посчитает бот Оценки по своему прайсу — здесь её не ставим.",
                               "muted", wrap=True))

        self.комментарий = QTextEdit()
        self.комментарий.setPlaceholderText("Сколы, состояние корпуса")
        внутри.addWidget(self.комментарий, 1)
        return рамка

    def _справа(self):
        """Что нужно прямо сейчас: шаг Apple → QR для медиа → подтверждение."""
        self.правая = QStackedWidget()

        apple = QFrame()
        apple.setObjectName("карточка")
        ал = QVBoxLayout(apple)
        ал.setContentsMargins(26, 22, 26, 22)
        ал.setSpacing(10)
        ал.addWidget(kicker("ОДИН ШАГ НА ТЕЛЕФОНЕ", 15, 2.4, C["brand"]))
        ал.addWidget(label("Откройте «Об этом устройстве» — Apple сама скажет, что менялось",
                           wrap=True, font_=font(FONT_HEAD, 25, W.Bold)))
        for i, t in enumerate(("Настройки → Основные", "Об этом устройстве",
                               "если есть «Детали и обслуживание» — зайдите в неё"), 1):
            ал.addWidget(label(f"{i} · {t}", "muted", wrap=True))
        ал.addStretch(1)
        ал.addWidget(label("Строки может не быть: Apple показывает её, только если деталь меняли. "
                           "Проверка всё равно уйдёт.", "muted", wrap=True))
        b_пропуск = _кнопка("Сделает сотрудник", "small")
        b_пропуск.clicked.connect(self.пропустить_apple.emit)
        ал.addWidget(b_пропуск, 0, Qt.AlignLeft)

        тест, тл = _карточка("ТЕСТ НА ТЕЛЕФОНЕ КЛИЕНТА")
        # код поменьше: под ним ещё семь строк результата и кнопки, в полный размер
        # содержимое карточки не помещается. Сканируют его с 20 см — этого хватает с запасом
        self.qr_тест = QrBlock(170)
        тл.addWidget(self.qr_тест, 0, Qt.AlignHCenter)
        self.тест_ссылка = label("", "muted", wrap=True)
        self.тест_ссылка.setAlignment(Qt.AlignHCenter)
        тл.addWidget(self.тест_ссылка)
        self.тест_подсказка = label(ПОДСКАЗКА_ТЕСТА, "muted", wrap=True)
        self.тест_подсказка.setAlignment(Qt.AlignHCenter)
        тл.addWidget(self.тест_подсказка)
        self.тест_список = QVBoxLayout()
        self.тест_список.setSpacing(2)
        тл.addLayout(self.тест_список)
        тл.addStretch(1)
        # По две кнопки в ряд: три в один ряд не помещаются по ширине колонки, и подписи
        # обрезаются на полуслове — «Нет в нашей се…» читается как что угодно.
        for пара in ((("Нет в нашей сети", self.пропустить_тест.emit),
                      ("К проверкам руками",
                       lambda: self.правая.setCurrentIndex(СТР_РУЧНАЯ))),
                     (("Другой код", self.новый_тест.emit),)):
            ряд_теста = QHBoxLayout()
            ряд_теста.setSpacing(10)
            for надпись, что in пара:
                b = _кнопка(надпись, "small")
                b.clicked.connect(что)
                ряд_теста.addWidget(b)
            if len(пара) == 1:
                ряд_теста.addStretch(1)
            тл.addLayout(ряд_теста)

        ручная, рл = _карточка("ПРОВЕРЬТЕ РУКАМИ")
        # восемь рядов с подписями — карточка плотная: промежутки урезаем, иначе длинные
        # подписи («Детали и обслуживание…») не помещаются во вторую строку и обрезаются
        рл.setSpacing(8)
        рл.addWidget(label("Нажимайте по строке: работает → НЕ работает → не отмечено",
                           "muted", wrap=True, font_=font(FONT_TEXT, 14)))
        ряды = QVBoxLayout()
        ряды.setContentsMargins(0, 0, 0, 0)
        ряды.setSpacing(5)
        self.пункты_ряды = {}
        for ключ, имя, подробно in ocenka_media.ПУНКТЫ:
            r = ПунктРяд(ключ, имя, подробно)
            r.нажали.connect(self.отметить)
            self.пункты_ряды[ключ] = r
            ряды.addWidget(r)
        рл.addLayout(ряды, 1)
        self.ручная_итог = label("", wrap=True, font_=font(FONT_TEXT, 16, W.Bold))
        self.ручная_итог.setAlignment(Qt.AlignHCenter)
        рл.addWidget(self.ручная_итог)
        ряд_ручной = QHBoxLayout()
        ряд_ручной.setSpacing(10)
        # «Запечатан» тут кнопкой не нужен: у запечатанного аппарата отметка ставится сама
        # (коробку не вскрывают), а на б/у сделке бот её всё равно не примет
        for надпись, что in (("К тесту телефона", lambda: self.правая.setCurrentIndex(СТР_ТЕСТ)),
                             ("К фото и видео", lambda: self.правая.setCurrentIndex(СТР_МЕДИА))):
            b = _кнопка(надпись, "small")
            b.clicked.connect(что)
            ряд_ручной.addWidget(b)
        рл.addLayout(ряд_ручной)

        медиа, мл = _карточка("ФОТО И ВИДЕО — ЧЕРЕЗ БОТА")
        мл.setSpacing(9)          # карточка плотная: QR, код, адрес, чек-лист и три кнопки
        self.qr = QrBlock()
        мл.addWidget(self.qr, 0, Qt.AlignHCenter)
        self.код = label("—", font_=font(FONT_NUM, 28, W.Bold))
        self.код.setAlignment(Qt.AlignHCenter)
        мл.addWidget(self.код)
        # Адрес нужен, только если QR не считался, — поэтому мелко: место на этой
        # карточке дороже отдать самому коду и кнопкам.
        self.ссылка = label("", "muted", wrap=True, font_=font(FONT_TEXT, 15))
        self.ссылка.setAlignment(Qt.AlignHCenter)
        мл.addWidget(self.ссылка)
        # Текст короткий намеренно: по шагам сотрудника ведёт сам бот, а каждая лишняя
        # строка здесь отнимает высоту у QR и кнопок этой же карточки.
        self.медиа = label(ПОДСКАЗКА_МЕДИА, "muted", wrap=True)
        self.медиа.setAlignment(Qt.AlignHCenter)
        мл.addWidget(self.медиа)
        # Что уже дошло до бота — здесь же, живьём. Касса спрашивает об этом сервер (он
        # читает базу Оценки), и до тех пор, пока фото, видео и отметки не собраны, кнопка
        # «Отправить в Оценку» не нажимается: иначе карточка уходит в группу без медиа, а
        # отказ прилетает минутой позже, когда телефон клиента уже в руках.
        self.медиа_список = QVBoxLayout()
        self.медиа_список.setSpacing(2)
        мл.addLayout(self.медиа_список)
        мл.addStretch(1)
        for пара in ((("К проверкам руками",
                       lambda: self.правая.setCurrentIndex(СТР_РУЧНАЯ)),
                      ("К тесту телефона", lambda: self.правая.setCurrentIndex(СТР_ТЕСТ))),
                     (("Другой код", self.новый_код.emit),)):
            ряд_медиа = QHBoxLayout()
            ряд_медиа.setSpacing(10)
            for надпись, что in пара:
                b = _кнопка(надпись, "small")
                b.clicked.connect(что)
                ряд_медиа.addWidget(b)
            if len(пара) == 1:
                ряд_медиа.addStretch(1)
            мл.addLayout(ряд_медиа)

        готово, гл = _карточка("ОТПРАВЛЕНО")
        гл.addStretch(1)
        self.номер = label("—", font_=font(FONT_NUM, 44, W.Bold))
        self.номер.setAlignment(Qt.AlignHCenter)
        гл.addWidget(self.номер)
        self.итог_текст = label("", "muted", wrap=True)
        self.итог_текст.setAlignment(Qt.AlignHCenter)
        гл.addWidget(self.итог_текст)
        гл.addStretch(1)

        for w in (apple, тест, ручная, медиа, готово):   # порядок — СТР_APPLE…СТР_ГОТОВО
            self.правая.addWidget(w)
        return self.правая

    # ---------- состояния ----------
    def начать(self):
        """Новая сделка: поля пустые, проверка с нуля."""
        self.rep, self.готово, self.отправлено = {}, False, False
        self.тест, self.тест_пропущен = {}, ""
        self.ручная = {}
        self.медиа_состояние, self._подсказка = {}, ""
        self._нарисовать_ручную()
        self._нарисовать_тест()
        self._нарисовать_медиа()
        self.имя.clear()
        self.телефон.clear()
        self.комментарий.clear()
        self.коробка.setChecked(False)
        self.шнур.setChecked(False)
        self.sim.setCurrentIndex(0)
        self.sim_подпись.setText("")
        self.аппарат.setText("Подключите телефон кабелем")
        self.ошибка.setText("")
        self._нарисовать_повтор({})
        self.подсказка.setText("Не отключайте кабель. Обычно это занимает около минуты.")
        for r in self.шаги.values():
            r.set("wait", "")
        self.set_состояние("")
        self.режим(False)
        self.стопка.setCurrentIndex(0)
        self.правая.setCurrentIndex(СТР_ТЕСТ)
        self._очистить_итоги()
        self.b_отправить.setText("Отправить в Оценку")
        self.b_отмена.setText("Отменить")
        self.b_печать.setEnabled(False)
        self.имя.setFocus()
        self._проверить()

    def set_point(self, point):
        self.точка.setText(point_text(point))

    def set_клиент(self, имя, телефон):
        """Клиента записали на анкете, до кабеля; здесь поля остаются правимыми."""
        self.имя.setText(str(имя or ""))
        self.телефон.setText(str(телефон or ""))
        self._проверить()

    def set_состояние(self, текст, причина=""):
        """Плашка состояния: выбор сотрудника, а если проверка его изменила — на что и почему."""
        if not текст:
            self.состояние.hide()
            return
        if причина:
            self.состояние.setText(f"{текст} — изменено проверкой: {причина}")
            self.состояние.setStyleSheet(f"background: {C['warnbg']}; color: {C['warntext']}; "
                                         "border-radius: 16px; padding: 7px 18px;")
        else:
            self.состояние.setText(str(текст))
            self.состояние.setStyleSheet(f"background: {C['tint']}; color: {C['brand']}; "
                                         "border-radius: 16px; padding: 7px 18px;")
        self.состояние.show()

    СТРОКИ_КАБЕЛЯ = ("connect", "battery", "locks", "apple", "upload")

    def режим(self, запечатанный, имеи=()):
        """Запечатанный: кабеля нет, остаются шаги по базе IMEI и реестру; коробка и шнур
        на месте по определению. Обычный аппарат — все шаги."""
        for ключ, r in self.шаги.items():
            r.setVisible(not (запечатанный and ключ in self.СТРОКИ_КАБЕЛЯ))
        if запечатанный:
            self.аппарат.setText("Запечатанный · IMEI " + " · ".join(x for x in имеи if x))
            self.подсказка.setText("Кабель не нужен: проверяем IMEI с коробки по базе и реестру РФС.")
            self.шаги["passport"].set("run", "по базе IMEI")
            self.коробка.setChecked(True)
            self.шнур.setChecked(True)
            # Теста на телефоне у запечатанного быть не может — коробку не вскрывают. Это не
            # «всё в порядке», а записанный пропуск: автоцены у такой сделки нет в любом
            # случае, и оценщик видит причину словами.
            if not self.тест_пропущен:
                self.тест_пропущен = "запечатанный — коробку не вскрывали"
                self._нарисовать_тест()
            # и руками проверять нечего по той же причине: отметка записана, а не выдумана
            self.ручная = {ocenka_media.ЗАПЕЧАТАН: True}
            self._нарисовать_ручную()
            self.правая.setCurrentIndex(СТР_МЕДИА)
        else:
            self.шаги["connect"].set("run", "ждём «Доверять»")

    def set_step(self, key, state, text):
        if key in self.шаги:
            self.шаги[key].set(state, text)

    def set_trouble(self, text):
        self.подсказка.setText(text)

    def show_prompt(self, on):
        """Шаг с разделом Apple занимает правую колонку, пока он нужен."""
        if self.отправлено:
            return
        self.правая.setCurrentIndex(СТР_APPLE if on else СТР_ТЕСТ)

    def показать_код(self, код, ссылка):
        self.код.setText(код or "—")
        # под QR достаточно короткого адреса: он нужен, только если QR не считался
        self.ссылка.setText(str(ссылка or "").replace("https://", ""))
        self.qr.set(qr_pixmap(ссылка) if ссылка else None, "СКАНИРУЙТЕ", rise=False)

    # ---------- тест на телефоне клиента ----------
    def показать_тест(self, ссылка, почему=""):
        """QR на страницу теста. Пустая ссылка — сети нет, и это надо сказать словами."""
        self.тест_ссылка.setText(str(ссылка or "").replace("http://", ""))
        self.qr_тест.set(qr_pixmap(ссылка) if ссылка else None, "СКАНИРУЙТЕ", rise=False)
        if not ссылка:
            self.тест_подсказка.setText(почему or "Касса не в сети — тест на телефоне не открыть. "
                                        "Проверьте руками и нажмите «Нет в нашей сети».")
        else:
            self.тест_подсказка.setText(ПОДСКАЗКА_ТЕСТА)
        self._нарисовать_тест()

    def set_тест(self, res, пропущен=""):
        """Результат теста пришёл с телефона (или сотрудник отметил, что теста не будет)."""
        self.тест = dict(res or {})
        self.тест_пропущен = str(пропущен or "")
        self._нарисовать_тест()
        # Тест закончился — следующий шаг показываем сами: сотрудник не обязан догадываться,
        # что надо переключить карточку справа. Сначала ручные проверки (телефон ещё в
        # руках), и только когда они отмечены — фото и видео.
        if self._тест_закрыт() and not self.отправлено:
            self.правая.setCurrentIndex(СТР_МЕДИА if ocenka_media.готова(self.ручная)
                                        else СТР_РУЧНАЯ)
        self._проверить()

    def _тест_закрыт(self) -> bool:
        return bool(self.тест_пропущен) or phonetest.готов(self.тест)

    def _нарисовать_тест(self):
        while self.тест_список.count():
            w = self.тест_список.takeAt(0).widget()
            if w:
                # setParent(None) обязателен: deleteLater откладывает удаление до
                # следующего круга цикла событий, и до тех пор старые строки остаются
                # детьми карточки — то есть лежат поверх новых, на своих прежних местах
                w.setParent(None)
                w.deleteLater()
        if self.тест_пропущен:
            self.тест_список.addWidget(label("Тест на телефоне пропущен: " + self.тест_пропущен,
                                             wrap=True, color=C["warntext"]))
            return
        for имя, ответ in phonetest.коротко(self.тест):
            значок, цвет, подпись = ВИД_ОТВЕТА.get(ответ, ВИД_ОТВЕТА[None])
            self.тест_список.addWidget(label(f"{значок}  {имя} — {подпись}", color=цвет,
                                             font_=font(FONT_TEXT, 17)))

    # ---------- ручные проверки ----------
    def отметить(self, ключ):
        """Нажали по пункту (или по «Запечатан»): ⬜ → ✅ → ❌ → ⬜.

        Когда отмечены все, сами переводим на фото и видео: это следующий шаг, и искать
        его на экране сотрудник не должен."""
        if self.отправлено:
            return
        было_готово = ocenka_media.готова(self.ручная)
        self.ручная = ocenka_media.переключить(self.ручная, ключ)
        self._нарисовать_ручную()
        if (not было_готово and ocenka_media.готова(self.ручная)
                and self.правая.currentIndex() == СТР_РУЧНАЯ):
            self.правая.setCurrentIndex(СТР_МЕДИА)
        self._проверить()

    def _нарисовать_ручную(self):
        d = ocenka_media.разобрать(self.ручная)
        запечатан = bool(d.get(ocenka_media.ЗАПЕЧАТАН))
        for ключ, ряд in self.пункты_ряды.items():
            ряд.set(None if запечатан else d.get(ключ))
            ряд.setEnabled(not запечатан)
        осталось = ocenka_media.не_отмечено(d)
        плох = [имя for _, имя in ocenka_media.плохие(d)]
        if запечатан:
            текст, цвет = "Коробку не вскрывали — проверять руками нечего", C["warntext"]
        elif осталось:
            # Перечислять, чего не хватает, не нужно: неотмеченные пункты и так видны
            # строкой выше — а длинный список отнимал у них высоту и наезжал на кнопки.
            текст, цвет = (f"Осталось отметить {len(осталось)} из {len(self.пункты_ряды)}",
                           C["warntext"])
        elif плох:
            текст, цвет = ("НЕ работает: " + ", ".join(плох)
                           + ". Сделку оценит человек — автоцены не будет.", C["badtext"])
        else:
            текст, цвет = "Все пункты отмечены — всё работает", C["ok"]
        self.ручная_итог.setText(текст)
        self.ручная_итог.setStyleSheet(f"color: {цвет}")
        # чек-лист отправки живёт на карточке медиа, и строка про проверки руками — в нём:
        # перерисовываем здесь, иначе он остаётся с прошлым числом отмеченных
        self._нарисовать_медиа()

    # ---------- фото и видео в боте ----------
    def set_медиа(self, состояние):
        """Сервер ответил, что дошло до бота по коду обмена. Пустой ответ — не трогаем."""
        if not isinstance(состояние, dict):
            return
        self.медиа_состояние = dict(состояние)
        self._нарисовать_медиа()
        self._проверить()

    def _медиа_готовы(self) -> bool:
        """Собраны ли фото, видео и отметки. Сервер не смог посмотреть — не держим сделку:
        отказать из-за своей же слепоты хуже, чем пропустить карточку, которую бот всё
        равно не примет без видео. На экране при этом прямо написано, что мы не видим."""
        с = self.медиа_состояние
        if not с:
            return False                       # ещё не спрашивали — значит и не дошло
        if not с.get("известно"):
            return True
        return bool(с.get("готово"))

    def _нарисовать_медиа(self):
        """Чек-лист отправки: фото и видео (их видит сервер) и ручные проверки (наши же).

        Один список на всё, и он висит там, где стоит кнопка «Отправить в Оценку»: иначе
        сотрудник ищет, чего не хватает, по трём карточкам."""
        while self.медиа_список.count():
            w = self.медиа_список.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        с = self.медиа_состояние
        строки = []
        if not с:
            pass                               # ещё не спрашивали сервер — и сказать нечего
        elif not с.get("известно"):
            self.медиа_список.addWidget(label(
                "Касса не видит бота: " + str(с.get("почему") or "сервер не ответил")
                + ". Проверьте сами, что фото и видео отправлены, — без них бот сделку не создаст.",
                wrap=True, color=C["warntext"]))
        else:
            фото = int(с.get("фото") or 0)
            строки += [(f"Фото {фото} из {ocenka_media.НУЖНО_ФОТО}",
                        фото >= ocenka_media.НУЖНО_ФОТО),
                       ("Видео телефона", bool(с.get("видео")))]
        # Ручные проверки спрашивать не у кого: их отмечают здесь, на экране, и мы про них
        # знаем всё. Строка остаётся на месте и когда сервера нет вовсе.
        осталось = ocenka_media.не_отмечено(self.ручная)
        строки.append((f"Проверки руками — осталось {len(осталось)}" if осталось
                       else ("Проверки руками — коробку не вскрывали"
                             if ocenka_media.разобрать(self.ручная).get(ocenka_media.ЗАПЕЧАТАН)
                             else f"Проверки руками — все {len(ocenka_media.КЛЮЧИ)} пунктов"),
                      ocenka_media.готова(self.ручная)))
        for текст, есть in строки:
            значок, цвет = ("✓", C["ok"]) if есть else ("○", C["warntext"])
            строка = label(f"{значок}  {текст}", color=цвет,
                           font_=font(FONT_TEXT, 20, W.Bold if not есть else W.Medium))
            строка.setAlignment(Qt.AlignHCenter)
            self.медиа_список.addWidget(строка)

    def _очистить_итоги(self):
        """Убрать прошлый итог проверки — так, чтобы его не осталось на экране.

        `setParent(None)` обязателен: `deleteLater` откладывает удаление до следующего
        круга цикла событий, и до тех пор старые подписи остаются детьми карточки, то есть
        лежат поверх новых, на своих прежних местах. Видно это было не сразу: `показать`
        вызывается второй раз, когда с телефона приходит журнал Apple (и теперь — когда
        берётся прошлая проверка), и именно тогда текст наезжал на текст."""
        for список in (self.итоги, self.плашки):
            while список.count() > (1 if список is self.плашки else 0):
                w = список.takeAt(0).widget()
                if w:
                    w.setParent(None)
                    w.deleteLater()

    def _строка_итога(self, ключ, значение, цвет=None):
        n = self.итоги.rowCount()
        self.итоги.addWidget(label(ключ, "muted", font_=font(FONT_TEXT, 20)), n, 0, Qt.AlignLeft)
        self.итоги.addWidget(label(значение, font_=font(FONT_TEXT, 20, W.Bold), color=цвет), n, 1,
                             Qt.AlignRight)

    def показать(self, rep):
        """Проверка закончилась: плашки наверху, подробности слева, QR справа."""
        self.rep = rep or {}
        пас = self.rep.get("паспорт") or {}
        пам = self.rep.get("память") or {}
        бат = self.rep.get("батарея") or {}
        вердикт = self.rep.get("детали_вердикт") or {}
        итог = (self.rep.get("итог") or {}).get("вердикт") or ""
        self.готово = True
        self.аппарат.setText(" · ".join(x for x in (
            пас.get("модель"), f"{пам.get('объём_гб')} ГБ" if пам.get("объём_гб") else None,
            f"iOS {пас.get('ios')}" if пас.get("ios") else None,
            f"IMEI {пас.get('imei')}" if пас.get("imei") else None) if x))
        self._очистить_итоги()

        цвет = {"ХОРОШИЙ": (C["okbg"], C["ok"]), "ИДЕАЛ": (C["okbg"], C["ok"]),
                "ПРОБЛЕМНЫЙ": (C["badbg"], C["badtext"])}.get(итог, (C["warnbg"], C["warntext"]))
        плашки = [(итог or "ПРОВЕРКА", *цвет)]
        повтор = self.rep.get("повторная_проверка") or {}
        if повтор:
            плашки.append(("Проверка прошлая · " + str(повтор.get("словами") or ""),
                           C["warnbg"], C["warntext"]))
        self._нарисовать_повтор(повтор)
        if вердикт.get("apple_подтверждено"):
            плашки.append(("Apple подтвердила детали", C["tint"], C["brand"]))
        if бат.get("здоровье_%") is not None:
            фон, кр = (C["warnbg"], C["warntext"]) if бат["здоровье_%"] < 85 else (C["okbg"], C["ok"])
            плашки.append((f"Аккумулятор {бат['здоровье_%']}%"
                           + (f" · {бат['циклы']} циклов" if бат.get("циклы") else ""), фон, кр))
        пан = self.rep.get("паника") or {}
        if пан.get("panic_full"):
            плашки.append(("panic full: ЕСТЬ", C["badbg"], C["badtext"]))
        elif пан.get("проверено"):
            плашки.append(("panic full: нет", "#FFFFFF", C["body"]))
        for n, (текст, фон, кр) in enumerate(плашки):
            self.плашки.insertWidget(n, _плашка(текст, фон, кр))

        for d in (вердикт.get("детали") or [])[:7]:
            имя = str(d.get("деталь") or "")
            if имя.startswith("Записи"):
                continue
            текст, кр = СОСТОЯНИЕ.get(d.get("статус"), (d.get("почему") or "—", C["muted"]))
            self._строка_итога(имя, текст, кр)
        прав = self.rep.get("правовой") or {}
        sk = self.rep.get("sickw") or {}
        if прав.get("найти_iphone"):
            включён = прав["найти_iphone"] == "включён"
            self._строка_итога("Найти iPhone", прав["найти_iphone"],
                               C["badtext"] if включён else C["ok"])
        if sk.get("в_чёрном_списке") is not None:
            плохо = sk["в_чёрном_списке"] is True
            self._строка_итога("Чёрный список", "числится" if плохо else "чисто",
                               C["badtext"] if плохо else C["ok"])
        from pintel_core.external import rfs as rfs_mod
        for r in (self.rep.get("рфс") or []):                  # реестр РК — по каждому IMEI
            цвет_рфс = (C["muted"] if not r.get("ok") else
                        {rfs_mod.VERIFIED: C["ok"], rfs_mod.BLOCKED: C["badtext"]}.get(r.get("verdict"), C["warntext"]))
            self._строка_итога(f"РФС · {r.get('imei')}", rfs_mod.словами(r), цвет_рфс)
        if self.rep.get("запечатанный"):                       # что знаем о коробке из базы IMEI
            for имя, ключ in (("Активация", "активация"), ("Гарантия", "гарантия"),
                              ("Куплен", "дата_покупки"), ("Страна покупки", "страна_покупки")):
                if sk.get(ключ):
                    self._строка_итога(имя, str(sk[ключ]))
            if пас.get("цвет"):
                self._строка_итога("Цвет (по базе)", str(пас["цвет"]))
        if пам.get("объём_гб"):
            self._строка_итога("Память", f"{пам['объём_гб']} ГБ"
                               + (f" · свободно {пам['свободно_гб']:.0f}" if пам.get("свободно_гб") else ""))
        for n, x in enumerate((self.rep.get("внимание") or [])[:3]):
            self._строка_итога("Внимание" if not n else "", x, C["warntext"])
        self.стопка.setCurrentIndex(1)

        from pintel_core.external import ocenka
        self.sim.setCurrentText(ocenka.sim_для_оценки(пас))
        self._сказать_про_sim(пас)
        if not self.отправлено:
            # проверка кабелем кончилась — теперь тест на телефоне, он идёт перед медиа
            self.правая.setCurrentIndex(СТР_МЕДИА if self._тест_закрыт() else СТР_ТЕСТ)
        self._проверить()

    def _нарисовать_повтор(self, повтор):
        """Проверку взяли готовой — говорим это словами, с временем и с выходом.

        Без этой строки экран выглядел бы как после обычного чтения по кабелю, и сотрудник
        не отличил бы отчёт получасовой давности от сделанного минуту назад."""
        if not повтор:
            self.повтор_текст.hide()
            self.b_перепроверить.hide()
            return
        сверка = str(повтор.get("сверка") or "")
        хвост = ("серийник, IMEI и замки сверены с телефоном" if сверка == "сошлась"
                 else сверка or "с телефоном не сверяли")
        self.повтор_текст.setText(f"Телефон кабелем не перечитывали: взята проверка "
                                  f"{повтор.get('словами') or 'прошлая'} — {хвост}.")
        self.повтор_текст.show()
        self.b_перепроверить.show()

    def снова_проверка(self):
        """Телефон читают заново: шаги с нуля, прошлый итог с экрана убираем.

        Клиента и уже собранное — тест, отметки руками, медиа — не трогаем: заново читается
        аппарат, а не сделка. Иначе кнопка «Проверить заново» стоила бы сотруднику всего,
        что он успел сделать."""
        self.rep, self.готово = {}, False
        self._нарисовать_повтор({})
        self._очистить_итоги()
        for r in self.шаги.values():
            r.set("wait", "")
        self.стопка.setCurrentIndex(0)
        self.аппарат.setText("Читаем телефон заново")
        self.подсказка.setText("Не отключайте кабель. Обычно это занимает около минуты.")
        self.сказать("", беда=False)
        self._проверить()

    def _сказать_про_sim(self, пас):
        """Откуда взялся тип SIM: это читается по кабелю, а не спрашивается у сотрудника."""
        если = []
        if пас.get("esim_only"):
            если.append("лотка нет, только eSIM")
        else:
            if пас.get("sim_в_лотке"):
                если.append("SIM в лотке")
            if пас.get("esim"):
                если.append("профиль eSIM")
            if (пас.get("imei2") or "").strip():
                если.append("второй IMEI")
        if self.rep.get("запечатанный"):
            self.sim_подпись.setText("Запечатанный: SIM по кабелю не читается — выберите сами.")
        elif если:
            self.sim_подпись.setText("SIM определён по телефону: " + ", ".join(если)
                                     + ". Поправьте, если не так.")
        else:
            self.sim_подпись.setText("SIM по телефону не определился — выберите сами.")

    def сказать(self, текст, беда=True):
        """Одна строка под колонками. Беда — красным, ожидание — цветом внимания: «ждём
        фото» не ошибка, а нормальный ход сделки, и пугать им сотрудника незачем."""
        self.ошибка.setText(текст)
        self.ошибка.setStyleSheet(f"color: {C['badtext'] if беда else C['warntext']}")

    def отказ(self, текст):
        """Телефон с заменой: сделку не оформляем, слепок уже сохранён."""
        self.готово = False
        self.ошибка.setText(текст)
        self.b_отправить.setEnabled(False)
        self.b_отмена.setText("Новая оценка")

    def ушло(self, код, текст=""):
        self.отправлено = True
        self.номер.setText(str(код or "—"))
        self.итог_текст.setText(текст or "Сделка создаётся. Номер появится здесь.")
        self.правая.setCurrentIndex(СТР_ГОТОВО)
        self.b_печать.setEnabled(True)
        self.b_отправить.setEnabled(False)
        self.b_отмена.setText("Новая оценка")

    def сделка_создана(self, номер):
        """Номер сделки из Оценки. Приходит через сервер, через секунду-другую после
        отправки: сделку создаёт бот, и до этого номера попросту нет."""
        self.итог_текст.setText(f"Сделка № {номер} создана — она уже у оценщика в боте.")

    def сделка_не_вышла(self, почему):
        """Бот не смог создать сделку. Говорим словами и даём отправить заново.

        Молчать тут нельзя: на экране написано «отправлено», сотрудник ждёт номера, а
        его не будет — и узнает он об этом, только когда клиент уже ушёл."""
        self.отправлено = False
        self.итог_текст.setText("Сделка не создалась: " + str(почему or "причина неизвестна")
                                + "\nИсправьте и отправьте ещё раз.")
        self.b_отправить.setEnabled(self._годно())
        self.b_отправить.setText("Отправить в Оценку")

    def занято(self, текст=""):
        self.b_отправить.setEnabled(not текст and self._годно())
        self.b_отправить.setText(текст or "Отправить в Оценку")

    # ---------- данные ----------
    def данные(self):
        """Цены здесь нет: её считает бот Оценки по своему прайсу (google_price), и наша
        цифра всё равно была бы другой."""
        return {"имя": self.имя.text().strip(), "телефон": нормальный_телефон(self.телефон.text()),
                "коробка": self.коробка.isChecked(), "шнур": self.шнур.isChecked(),
                "sim": self.sim.currentText(),
                "комментарий": self.комментарий.toPlainText().strip(),
                "тест": dict(self.тест), "тест_пропущен": self.тест_пропущен,
                "ручная": ocenka_media.разобрать(self.ручная)}

    def _годно(self):
        """Чего ждём перед отправкой. Порядок на экране такой же, как в жизни: проверка
        кабелем → тест на телефоне клиента → проверки руками → фото и видео в боте →
        чек клиенту → отправка.

        Тест на телефоне обязателен: кабель не нажмёт на экран, не послушает динамик и не
        посмотрит в камеру, а узнать об этом после выкупа дороже, чем задержать сделку на
        две минуты. Если телефона нет в нашей сети, сотрудник говорит об этом кнопкой —
        тогда сделка уходит человеку, а не получает автоцену.

        Фото и видео тоже обязательны, и ждать их надо здесь: бот без видео сделку не
        создаёт, и карточка, ушедшая в группу раньше медиа, означает только одно — её
        придётся собирать заново, уже отдав телефон клиенту.

        Проверки руками — третье обязательное: кнопки, вибрацию, SIM и целость проклейки
        не видит ни кабель, ни браузер на телефоне клиента. Отмечают их здесь же, на
        экране, и без всех отметок сделки нет — ровно как раньше в боте."""
        d = self.данные()
        return bool(self.готово and not self.отправлено and d["имя"] and d["телефон"]
                    and self._тест_закрыт() and ocenka_media.готова(self.ручная)
                    and self._медиа_готовы())

    def почему_нельзя(self) -> str:
        """Что мешает отправить — словами, для подсказки под кнопкой."""
        if self.отправлено or not self.готово:
            return ""
        d = self.данные()
        if not (d["имя"] and d["телефон"]):
            return "Впишите имя и телефон клиента."
        if not self._тест_закрыт():
            осталось = [имя for _, имя in phonetest.пропущенные(self.тест)]
            return ("Нужен тест на телефоне клиента: " + ", ".join(осталось[:4])
                    + (f" и ещё {len(осталось) - 4}" if len(осталось) > 4 else "")
                    + ". Телефона нет в нашей сети — скажите об этом кнопкой.")
        if not ocenka_media.готова(self.ручная):
            осталось = ocenka_media.не_отмечено(self.ручная)
            return ("Отметьте проверки руками (карточка «Проверьте руками»): "
                    + ", ".join(осталось[:4])
                    + (f" и ещё {len(осталось) - 4}" if len(осталось) > 4 else "") + ".")
        if not self._медиа_готовы():
            нет = ocenka_media.чего_нет(self.медиа_состояние)
            если = ("Сканируйте QR справа и пришлите боту медиа. " if not self.медиа_состояние
                    or not self.медиа_состояние.get("начали") else "")
            return (если + "Ждём в боте: " + ", ".join(нет) if нет
                    else если + "Ждём фото и видео в боте.")
        return ""

    def _печать_можно(self) -> bool:
        """Чек печатаем, как только фото и видео дошли до бота, — не дожидаясь отправки.

        Клиент стоит у кассы и уходит с бумагой; раньше кнопка оживала только после
        «Отправить в Оценку», и на этот один шаг его держали зря. В чеке нет ничего, что
        появляется при создании сделки: номер в нём — код обмена с этого же экрана.
        """
        return bool(self.готово and (self.отправлено or self._медиа_готовы()))

    def _проверить(self):
        d = self.данные()
        плохой = bool(self.телефон.text().strip() and not d["телефон"])
        self.телефон.setProperty("плохо", "да" if плохой else "нет")
        self.телефон.style().unpolish(self.телефон)
        self.телефон.style().polish(self.телефон)
        self.b_отправить.setEnabled(self._годно())
        self.b_печать.setEnabled(self._печать_можно())
        if not self.отправлено:
            мешает = self.почему_нельзя()
            # Затираем только свою же подсказку: на этой строке живут и сообщения о беде
            # («тест не прошёл», «телефон с заменой»), и потерять их нельзя.
            if мешает or self.ошибка.text() == getattr(self, "_подсказка", ""):
                self.сказать(мешает, беда=False)
                self._подсказка = мешает
        return self._годно()

    def _отправить(self):
        d = self.данные()
        нет = [имя for имя, есть in (("имя клиента", d["имя"]), ("телефон клиента", d["телефон"]),
                                     ("результат проверки", self.готово),
                                     ("тест на телефоне", self._тест_закрыт()),
                                     ("проверки руками", ocenka_media.готова(self.ручная)),
                                     ("фото и видео в боте", self._медиа_готовы())) if not есть]
        if нет:
            self.сказать("Не хватает: " + ", ".join(нет))
            return
        self.ошибка.setText("")
        self.отправить.emit(d)
