# -*- coding: utf-8 -*-
"""Рабочий экран сделки: телефон слева, текущий шаг в центре, клиент справа.

За экраном работает сотрудник, но смотрит на него и клиент — поэтому главное правило одно:
**на экране один главный шаг**. Он стоит в центре, крупно и в светящейся рамке; всё
остальное приглушено и лежит по бокам как справка.

* **Сверху — шаги сделки** одной строкой: проверка → тест на телефоне → проверка руками →
  фото и видео → отправка. Это и карта, и навигация: по шагу можно нажать. Раньше ради этого
  в каждой карточке стояли кнопки «К тесту», «К фото» — их больше нет.
* **Слева — телефон**: пока он читается, идут шаги проверки; когда прочитан — кольцо батареи,
  вердикт одним словом и список деталей.
* **В центре — то, что нужно сделать прямо сейчас**: QR теста, отметки руками, QR для медиа.
* **Справа — клиент и комплект**: имя и телефон уже вписаны на анкете, здесь их можно поправить.

Поля сделки — ровно те, что хранит Оценка. Фото и видео программа не видит вовсе: их
принимает бот по коду с этого экрана, он же проверяет видео и создаёт сделку.
"""
import html
import re

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QSizePolicy, QStackedWidget, QTextEdit,
                               QVBoxLayout, QWidget)

from pintel_core import colours
from pintel_core import history as история_мод
from pintel_core import phonetest
from pintel_core.external import ocenka_media

from .ui import (C, FONT_HEAD, FONT_NUM, FONT_TEXT, QrBlock, Ring, Screen, SheenButton, StepRow,
                 STEPS, Stepper, W, font, kicker, label, logo_label, point_text, qr_pixmap, Успех)

QSS_DEAL = """
QLineEdit, QComboBox, QTextEdit { background: %(field)s; border: 1px solid %(line)s; border-radius: 14px;
    padding: 11px 15px; font-size: 21px; color: %(ink)s; selection-background-color: %(action)s; }
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border-color: %(action)s; }
QLineEdit[плохо="да"] { border-color: %(bad)s; }
QComboBox::drop-down { border: none; width: 38px; }
QComboBox QAbstractItemView { background: %(card_hi)s; color: %(ink)s; border: 1px solid %(line)s;
    selection-background-color: %(tint)s; selection-color: %(ink)s; outline: none; }
QCheckBox { font-size: 21px; font-weight: 600; spacing: 12px; color: %(ink)s; }
QCheckBox::indicator { width: 26px; height: 26px; border: 2px solid %(ring)s; border-radius: 8px;
    background: %(field)s; }
QCheckBox::indicator:checked { background: %(action)s; border-color: %(cyan)s; }
QPushButton#ghost { background: transparent; color: %(body)s; border: 1px solid %(line)s;
    border-radius: 14px; font-size: 21px; font-weight: 700; min-height: 56px; padding: 0 28px; }
QPushButton#ghost:pressed { background: %(card_hi)s; }
QPushButton#ghost:disabled { color: %(ghost)s; border-color: %(border)s; }
QPushButton#small { background: %(tint)s; color: %(brand)s; border: none; border-radius: 12px;
    font-size: 19px; font-weight: 700; min-height: 48px; padding: 0 22px; }
QPushButton#small:pressed { background: %(tint_border)s; }
QFrame#карточка { background: %(card)s; border: 1px solid %(border)s; border-radius: 22px; }
QFrame#фокус { background: %(card_hi)s; border: 2px solid %(tint_border)s; border-radius: 26px; }
QFrame#всплывашка { background: #FFFFFF; border: 2px solid %(tint_border)s; border-radius: 20px; }
QFrame#плашка_истории { background: %(card)s; border: 1px solid %(line)s; border-radius: 19px; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
""" % C

СОСТОЯНИЕ = {"ok": ("оригинальная", C["ok"]), "repaired": ("меняли, оригинал Apple", C["warntext"]),
             "used": ("б/у деталь", C["warntext"]), "bad": ("не подтверждена", C["badtext"])}

# Вердикт одним словом — так, как его поймёт и клиент, а не только сотрудник.
ВЕРДИКТЫ = {"ИДЕАЛ": ("Идеальный", C["ok"]), "ХОРОШИЙ": ("Хороший", C["ok"]),
            "ПРОБЛЕМНЫЙ": ("Есть проблемы", C["badtext"]),
            "ПРОВЕРКА НЕПОЛНАЯ": ("Проверка неполная", C["warntext"])}

# Страницы центральной карточки. Раньше индексы стояли числами в семи местах, и добавить
# между ними ещё одну страницу было нельзя, не переставив все.
СТР_APPLE, СТР_ТЕСТ, СТР_РУЧНАЯ, СТР_ЦЕНА, СТР_МЕДИА, СТР_ГОТОВО = 0, 1, 2, 3, 4, 5
# Шаги сверху и страница, на которую ведёт нажатие по каждому («Проверка» — не страница,
# по ней не нажимают).
#
# Порядок с 12.11.2026: цена — ДО медиа. Сотрудник привязал сделку к себе ещё до анкеты
# (экран привязки), поэтому после проверок касса сразу показывает автооценку, а фото и
# видео бот просит у него сам — после «Отправить на оценку». QR для медиа остался только у
# сделки без привязки (сервер не видел бота): там порядок прежний, медиа перед отправкой.
ШАГИ_СДЕЛКИ = ("Проверка", "Тест на телефоне", "Проверка руками", "Автооценка", "Фото и видео")
# строка итога длиннее этого в одну линию рядом с подписью не помещается — её переносим
ДЛИННАЯ_СТРОКА_ИТОГА = 40
СТРАНИЦА_ШАГА = {1: СТР_ТЕСТ, 2: СТР_РУЧНАЯ, 3: СТР_ЦЕНА, 4: СТР_МЕДИА}
ШАГ_СТРАНИЦЫ = {СТР_APPLE: 0, СТР_ТЕСТ: 1, СТР_РУЧНАЯ: 2, СТР_ЦЕНА: 3, СТР_МЕДИА: 4,
                СТР_ГОТОВО: 4}
ОТПРАВИТЬ = "Отправить на оценку"
# Пока считается цена и пока сотрудник называет сумму в боте, экран говорит только это:
# на него смотрит и клиент, а цена из прайса — подсказка сотруднику, не ему (13.11.2026).
ПОДОЖДИТЕ = "Пожалуйста, подождите"


def деньги(сумма) -> str:
    """185000 → «185 000 ₸»."""
    return f"{int(сумма):,}".replace(",", " ") + " ₸"
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


def без_значка(текст) -> str:
    """Надпись кнопки Оценки без эмодзи в начале: «📱 Б/у телефон…» → «Б/у телефон…».

    В боте значок помогает найти кнопку, а на экране кассы эмодзи выглядят чужими — у них
    своя палитра и своя насечка, и на Windows шрифт с ними может оказаться другим."""
    return re.sub(r"^[^\wА-Яа-яЁё«(]+", "", str(текст or "")).strip()


def циклов(n) -> str:
    """«1 цикл», «3 цикла», «1064 цикла», «25 циклов»."""
    n = int(n)
    хвост = n % 100
    if 11 <= хвост <= 14:
        слово = "циклов"
    elif хвост % 10 == 1:
        слово = "цикл"
    elif хвост % 10 in (2, 3, 4):
        слово = "цикла"
    else:
        слово = "циклов"
    return f"{n} {слово}"


# Размеры надписей кнопок. Те же числа стоят в QSS (там они красят), но ширину кнопки Qt
# считает по шрифту самого виджета: пока он оставался шрифтом приложения, «Отправить в
# Оценку» не помещалась в кнопку и вылезала за её край.
РАЗМЕР_КНОПКИ = {"primary": 26, "ghost": 21, "small": 19}


def _кнопка(текст, вид="primary"):
    b = SheenButton(текст) if вид == "primary" else QPushButton(текст)
    b.setObjectName(вид)
    b.setCursor(Qt.PointingHandCursor)
    b.setFont(font(FONT_TEXT, РАЗМЕР_КНОПКИ.get(вид, 21), W.Bold))
    return b


# Кнопки выбора цвета: слово из словаря и кружок-образец. Выбранная — рамкой и фоном, как
# активный ряд на остальных экранах.
QSS_ЦВЕТА = f"""
QPushButton#chip {{ background: {C['field']}; border: 1px solid {C['line']}; border-radius: 12px;
                    padding: 9px 12px; text-align: left; color: {C['ink']}; }}
QPushButton#chip:hover {{ border: 1px solid {C['pale']}; }}
QPushButton#chip:checked {{ background: {C['tint']}; border: 2px solid {C['action']};
                            padding: 8px 11px; color: {C['brand']}; }}
QPushButton#chip_more {{ background: transparent; border: 1px dashed {C['ring']}; border-radius: 12px;
                         padding: 9px 12px; text-align: left; color: {C['muted']}; }}
"""


def _образец(имя, размер=18):
    """Кружок цвета на кнопке. Слово главное, кружок — подсказка глазу."""
    pm = QPixmap(размер * 2, размер * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(C["ring"]), 1))
    p.setBrush(QColor(colours.ОБРАЗЦЫ.get(имя, C["ground"])))
    p.drawEllipse(QRectF(1, 1, размер - 2, размер - 2))
    p.end()
    return QIcon(pm)


def _кнопка_цвета(имя, размер=15, модель=None):
    """На кнопке — название Apple для этой модели («Natural Titanium»): по нему сотрудник
    узнаёт телефон. В сделку уходит слово словаря (`слово` — NATURAL)."""
    b = QPushButton(colours.название(имя, модель))
    b.setProperty("слово", имя)
    b.setObjectName("chip")
    b.setCheckable(True)
    b.setCursor(Qt.PointingHandCursor)
    b.setFont(font(FONT_TEXT, размер, W.DemiBold))
    b.setIcon(_образец(имя))
    b.setIconSize(QSize(18, 18))
    return b


class ВыборЦвета(QDialog):
    """Весь словарь цветов — когда модели нет в нашем списке или нужного цвета нет среди её
    кнопок. Тоже кнопками: клавиатуры в выборе цвета нет нигде."""

    def __init__(self, parent=None, выбран=None):
        super().__init__(parent)
        self.setWindowTitle("Цвет телефона")
        self.setModal(True)
        self.выбран = None
        self.setStyleSheet(f"QDialog {{ background: {C['ground']}; }}" + QSS_ЦВЕТА)
        л = QVBoxLayout(self)
        л.setContentsMargins(32, 28, 32, 28)
        л.setSpacing(14)
        л.addWidget(label("Цвет телефона", font_=font(FONT_HEAD, 26, W.Bold)))
        л.addWidget(label("Выберите цвет корпуса. Так он будет записан в сделке и в названии товара.",
                          wrap=True, font_=font(FONT_TEXT, 16), color=C["muted"]))
        сетка = QGridLayout()
        сетка.setSpacing(10)
        for n, имя in enumerate(colours.ВСЕ_ЦВЕТА):
            b = _кнопка_цвета(имя, 16)
            b.setMinimumWidth(214)
            b.setChecked(имя == выбран)
            b.clicked.connect(lambda _=False, имя=имя: self._взять(имя))
            сетка.addWidget(b, n // 4, n % 4)
        л.addLayout(сетка)
        низ = QHBoxLayout()
        низ.addStretch(1)
        отмена = _кнопка("Отмена", "small")
        отмена.clicked.connect(self.reject)
        низ.addWidget(отмена)
        л.addLayout(низ)

    def _взять(self, имя):
        self.выбран = имя
        self.accept()


ПОЧИНИТЬ_СВЯЗЬ = "Телефон не виден? Починить связь"
НАПОМНИТЬ = "Напомнить в боте"
ПАУЗА_НАПОМНИТЬ_МС = 20_000           # столько же держит паузу сервер


def _плашка(текст, фон, цвет):
    l = label(текст, font_=font(FONT_TEXT, 18, W.Bold))
    l.setStyleSheet(f"background: {фон}; color: {цвет}; border-radius: 14px; padding: 6px 16px;")
    return l


# Подсказки под заголовками карточек. Короткие намеренно: длинный текст на этом экране никто
# не читает, а место он отнимает у QR и у строк результата.
ПОДСКАЗКА_МЕДИА = "Сотрудник сканирует код своим телефоном — бот проведёт по шагам."
ПОДСКАЗКА_МЕДИА_БОТ = "Бот Оценки сам напишет вам и проведёт по шагам — код сканировать не нужно."
ПОДСКАЗКА_ТЕСТА = "Клиент сканирует код телефоном, который сдаёт."

# Вид пункта по ответу: подпись состояния, цвет текста, фон и рамка ряда.
ВИД_ПУНКТА = {None: ("не отмечено", C["muted"], C["field"], C["line"]),
              True: ("работает", C["ok"], C["okbg"], "#8FD3B7"),
              False: ("НЕ работает", C["badtext"], C["badbg"], "#F0A29C")}


class Отметка(QWidget):
    """Квадратик состояния: пусто · галочка · крест. Рисуется, а не набирается значком.

    Эмодзи ⬜✅❌ выглядели на экране точки чужеродно — у них своя палитра, свой размер и
    своя насечка. Здесь те же три состояния нарисованы цветами остального окна и одинаково
    на любой машине: шрифт с эмодзи на Windows может оказаться другим, а рисунок — нет.
    """

    def __init__(self, сторона=30):
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
        цвет = {True: C["okdot"], False: C["bad"]}.get(self.ответ)
        p.setPen(QPen(QColor(цвет or C["ring"]), 2))
        p.setBrush(QColor(цвет) if цвет else QColor(C["field"]))
        p.drawRoundedRect(поле, 8, 8)
        if self.ответ is None:
            return
        p.setPen(QPen(QColor(C["на_цвете"]), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if self.ответ:                       # галочка
            p.drawPolyline([поле.topLeft() + QPointF(6, с * 0.52),
                            поле.topLeft() + QPointF(с * 0.40, с * 0.72),
                            поле.topLeft() + QPointF(с - 10, с * 0.28)])
        else:                                # крест
            k = с * 0.30
            p.drawLine(поле.topLeft() + QPointF(k, k), поле.bottomRight() - QPointF(k, k))
            p.drawLine(поле.topRight() + QPointF(-k, k), поле.bottomLeft() + QPointF(k, -k))


class ПунктРяд(QFrame):
    """Один пункт ручной проверки: квадратик состояния, название и чем его проверить.

    Нажатие по всей плитке, а не по маленькому квадратику: сотрудник держит телефон клиента
    в одной руке. Состояний три — не отмечено, работает, не работает, — и «не проверял»
    среди них нет намеренно: нечем проверить значит «не работает», и сделку смотрит человек.
    Состояние говорится и словами: по одному цвету его читать нельзя.
    """

    нажали = Signal(str)

    def __init__(self, ключ, имя, подробно):
        super().__init__()
        self.ключ = ключ
        # имя объекта и селектор по нему: иначе рамка и фон достаются и подписям внутри —
        # стиль QFrame без селектора наследуется всеми детьми
        self.setObjectName("checkrow")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        self.setMinimumHeight(72)
        ряд = QHBoxLayout(self)
        ряд.setContentsMargins(16, 8, 14, 8)
        ряд.setSpacing(14)
        self.значок = Отметка()
        текст = QVBoxLayout()
        текст.setContentsMargins(0, 0, 0, 0)
        текст.setSpacing(2)
        текст.addStretch(1)
        # Состояние словами — в одну строку с названием, а не отдельной колонкой справа:
        # колонка съедала ширину у подписи, и та обрывалась на полуслове.
        верх = QHBoxLayout()
        верх.setContentsMargins(0, 0, 0, 0)
        верх.setSpacing(10)
        self.имя = label(имя, font_=font(FONT_TEXT, 21, W.Bold))
        self.состояние = label("", font_=font(FONT_TEXT, 16, W.Bold))
        верх.addWidget(self.имя)
        верх.addWidget(self.состояние)
        верх.addStretch(1)
        текст.addLayout(верх)
        self.подробно = label(подробно, wrap=True, font_=font(FONT_TEXT, 15), color=C["muted"])
        текст.addWidget(self.подробно)
        текст.addStretch(1)
        ряд.addWidget(self.значок, 0, Qt.AlignVCenter)
        ряд.addLayout(текст, 1)
        # Нажимают по всей плитке, поэтому её содержимое мышь не ловит вовсе
        for внутри in (self.значок, self.имя, self.состояние, self.подробно):
            внутри.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.set(None)

    def set(self, ответ):
        подпись, цвет, фон, рамка = ВИД_ПУНКТА.get(ответ, ВИД_ПУНКТА[None])
        self.значок.set(ответ)
        self.setStyleSheet(f"QFrame#checkrow {{ background: {фон}; border: 1px solid {рамка}; "
                           "border-radius: 16px; }")
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
        # Палец увели с плитки, не отпуская, — это не нажатие, а передумали
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.нажали.emit(self.ключ)
            e.accept()
            return
        super().mouseReleaseEvent(e)


def _карточка(заголовок):
    """Боковая карточка с надзаголовком: внутрь кладут содержимое."""
    рамка = QFrame()
    рамка.setObjectName("карточка")
    рамка.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
    внутри = QVBoxLayout(рамка)
    внутри.setContentsMargins(24, 20, 24, 20)
    внутри.setSpacing(12)
    внутри.addWidget(kicker(заголовок, 14, 2.4, C["brand"]))
    return рамка, внутри


def _фокус(заголовок):
    """Центральная карточка шага: крупный заголовок и светящаяся рамка — это главное на
    экране, и глаз должен находить её первой."""
    рамка = QFrame()
    рамка.setObjectName("фокус")
    рамка.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
    внутри = QVBoxLayout(рамка)
    внутри.setContentsMargins(34, 26, 34, 26)
    внутри.setSpacing(12)
    внутри.addWidget(label(заголовок, wrap=True, font_=font(FONT_HEAD, 30, W.Bold)))
    return рамка, внутри


class ПлашкаИстории(QFrame):
    """Окошко в углу: сколько мы уже знаем про этот телефон.

    Стоит всегда — и когда истории нет, и когда её не удалось спросить: «ничего не нашли» и
    «Оценка не ответила» сотрудник обязан различать, иначе второе он примет за первое и
    назовёт цену с нуля. По нажатию разворачивается список, по второму нажатию угол снова
    пустой: список длинный, а нужен он ровно в ту минуту, когда называют цену.
    """

    нажали = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("плашка_истории")
        self.setCursor(Qt.PointingHandCursor)
        сл = QHBoxLayout(self)
        сл.setContentsMargins(16, 7, 16, 7)
        сл.setSpacing(10)
        self.текст = label("История телефона", font_=font(FONT_TEXT, 17, W.Bold))
        self.значок = label("·", font_=font(FONT_TEXT, 17, W.Bold), color=C["muted"])
        сл.addWidget(self.текст)
        сл.addWidget(self.значок)

    def set(self, вид, открыто=False):
        self.текст.setText(вид["подпись"])
        if вид["беда"] and not вид["строки"]:
            цвет = C["badtext"]
        elif вид["беда"]:
            цвет = C["warntext"]
        elif вид["строки"]:
            цвет = C["brand"]
        else:
            цвет = C["muted"]
        self.текст.setStyleSheet(f"color: {цвет}")
        self.значок.setText("▾" if открыто else ("▸" if вид["строки"] else "·"))

    def mousePressEvent(self, e):                                # noqa: N802 — имя от Qt
        self.нажали.emit()


class ПанельИстории(QFrame):
    """Сам список: заявки с сайта, сделки Оценки, наши прошлые проверки.

    Лежит поверх экрана, а не в разметке: развёрнутый список иначе двигал бы колонки и
    выталкивал кнопки отправки за край.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("всплывашка")
        self.setAutoFillBackground(True)
        сл = QVBoxLayout(self)
        сл.setContentsMargins(24, 18, 24, 20)
        сл.setSpacing(10)
        сл.addWidget(kicker("ИСТОРИЯ ЭТОГО ТЕЛЕФОНА", 14, 2.2, C["brand"]))
        self.текст = label("", wrap=True, font_=font(FONT_TEXT, 18))
        self.текст.setTextFormat(Qt.RichText)
        сл.addWidget(self.текст)
        self.беда = label("", wrap=True, font_=font(FONT_TEXT, 16), color=C["badtext"])
        self.беда.hide()
        сл.addWidget(self.беда)

    def наполнить(self, вид):
        """Первая строка записи — крупно и светлым, подробности — под ней приглушённо."""
        куски = []
        for первая, второе in вид["строки"]:
            кусок = f"<b>{html.escape(первая)}</b>"
            if второе:
                кусок += f"<br><span style='color:{C['muted']}'>{html.escape(второе)}</span>"
            куски.append(кусок)
        self.текст.setText("<br><br>".join(куски))
        self.беда.setText(вид["беда"])
        self.беда.setVisible(bool(вид["беда"]))

    def высота_для(self, ширина) -> int:
        """Сколько высоты нужно при такой ширине. `adjustSize` этого не умеет: у подписи с
        переносом высота зависит от ширины, и без явного счёта панель выходила ниже своего
        текста — первая и последняя строки истории обрезались."""
        return self.layout().totalHeightForWidth(int(ширина))


class WorkScreen(Screen):
    """Всё, что делает сотрудник после анкеты."""

    отправить = Signal(dict)
    печать = Signal()
    заново = Signal()
    пропустить_apple = Signal()
    новый_код = Signal()
    новый_тест = Signal()                 # другой одноразовый код для теста на телефоне
    пропустить_тест = Signal()            # телефона нет в нашей сети — сделка уйдёт человеку
    перепроверить = Signal()              # прочитать телефон заново, не брать прошлую проверку
    починить_связь = Signal()             # телефон не виден — перезапустить службу Apple
    напомнить = Signal()                  # бот ждёт фото и видео, а сотрудник потерял запрос
    проверки_руками = Signal()            # отметку руками поменяли — пересчитать состояние

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
        # к кому привязана сделка (имя из бота); None — привязки нет, медиа идут по-старому
        self.привязка = None
        # автооценка от бота: {} — не спрашивали, {"считаем": True}, {"цена": …, "почему": …}
        self.цена = {}
        self.root.setContentsMargins(48, 26, 48, 28)
        self.root.setSpacing(0)

        шапка = QHBoxLayout()
        шапка.setSpacing(16)
        шапка.addWidget(logo_label(42))
        self.аппарат = label("Подключите телефон кабелем", font_=font(FONT_HEAD, 26, W.DemiBold))
        # состояние, выбранное сотрудником до диагностики — кнопка Оценки; проверка может его
        # изменить, и тогда здесь же видно, на что и почему
        self.состояние = _плашка("", C["tint"], C["brand"])
        self.состояние.setWordWrap(True)
        self.состояние.hide()
        self.точка = label(point_text(point), font_=font(FONT_TEXT, 17, W.Medium), color=C["muted"])
        # Угол экрана: история этого телефона. Плашка в шапке, список — поверх экрана.
        self.история = {}
        self.история_плашка = ПлашкаИстории()
        self.история_плашка.нажали.connect(self.история_переключить)
        self.история_панель = ПанельИстории(self)
        self.история_панель.hide()
        # Модель и память — крупно, это и есть «какой телефон». iOS и IMEI нужны для сверки,
        # а не для чтения с двух метров, поэтому они мелкой строкой ниже.
        self.аппарат_подробно = label("", font_=font(FONT_TEXT, 16, W.Medium), color=C["muted"])
        имя_аппарата = QVBoxLayout()
        имя_аппарата.setSpacing(0)
        имя_аппарата.addWidget(self.аппарат)
        имя_аппарата.addWidget(self.аппарат_подробно)
        шапка.addLayout(имя_аппарата, 2)
        шапка.addWidget(self.состояние, 3)
        шапка.addWidget(self.история_плашка)
        шапка.addWidget(self.точка)
        self.root.addLayout(шапка)
        self.root.addSpacing(12)

        # Шаги сделки: карта и навигация одной строкой
        self.степпер = Stepper(ШАГИ_СДЕЛКИ)
        self.степпер.выбран.connect(self._к_шагу)
        self.root.addWidget(self.степпер)
        self.root.addSpacing(6)

        # Второстепенные факты проверки: взята прошлая, Apple подтвердила, отчёт о панике
        self.плашки = QHBoxLayout()
        self.плашки.setSpacing(10)
        self.плашки.addStretch(1)
        self.root.addLayout(self.плашки)
        self.root.addSpacing(10)

        тело = QHBoxLayout()
        тело.setSpacing(20)
        тело.addWidget(self._проверка(), 52)
        тело.addWidget(self._справа(), 84)
        тело.addWidget(self._сделка(), 46)
        self.root.addLayout(тело, 1)
        self.root.addSpacing(16)

        низ = QHBoxLayout()
        низ.setSpacing(16)
        self.b_отмена = _кнопка("Отменить", "ghost")
        self.b_отмена.clicked.connect(self.заново.emit)
        # Что мешает отправить — здесь же, между кнопками: рядом с той, которой не нажать
        self.ошибка = label("", wrap=True, font_=font(FONT_TEXT, 18, W.Medium), color=C["badtext"])
        self.ошибка.setAlignment(Qt.AlignCenter)
        self.b_печать = _кнопка("Печать чека", "ghost")
        self.b_печать.clicked.connect(self.печать.emit)
        self.b_отправить = _кнопка(ОТПРАВИТЬ)
        self.b_отправить.clicked.connect(self._отправить)
        низ.addWidget(self.b_отмена)
        низ.addWidget(self.ошибка, 1)
        низ.addWidget(self.b_печать)
        низ.addWidget(self.b_отправить)
        self.root.addLayout(низ)
        self.начать()

    # ---------- колонки ----------
    def _проверка(self):
        """Слева — телефон: пока читается, шаги проверки; прочитан — кольцо, вердикт, детали."""
        рамка, внутри = _карточка("ТЕЛЕФОН")
        self.стопка = QStackedWidget()
        шаги = QWidget()
        сл = QVBoxLayout(шаги)
        сл.setContentsMargins(0, 0, 0, 0)
        сл.setSpacing(4)
        self.шаги = {}
        for ключ, имя in STEPS:
            r = StepRow(имя)
            self.шаги[ключ] = r
            сл.addWidget(r)
        self.подсказка = label("Не отключайте кабель. Обычно это занимает около минуты.", "muted", wrap=True)
        сл.addSpacing(8)
        сл.addWidget(self.подсказка)
        сл.addStretch(1)
        # Телефон подключён, а программа его не видит — сотрудник чинит связь сам, одной кнопкой,
        # не уходя со сделки. Показывает её приложение (только на Windows: служба Apple там).
        self.b_связь = _кнопка(ПОЧИНИТЬ_СВЯЗЬ, "small")
        self.b_связь.clicked.connect(self.починить_связь.emit)
        self.b_связь.hide()
        сл.addWidget(self.b_связь, 0, Qt.AlignLeft)

        итог = QWidget()
        ил = QVBoxLayout(итог)
        ил.setContentsMargins(0, 0, 0, 0)
        ил.setSpacing(0)
        верх = QHBoxLayout()
        верх.setSpacing(20)
        self.кольцо = Ring(136)
        слова = QVBoxLayout()
        слова.setSpacing(4)
        слова.addStretch(1)
        слова.addWidget(kicker("БАТАРЕЯ", 13, 2.0))
        self.вердикт_подпись = label("", wrap=True, font_=font(FONT_TEXT, 18, W.Medium), color=C["body"])
        слова.addWidget(self.вердикт_подпись)
        слова.addSpacing(10)
        слова.addWidget(kicker("ИТОГ ПРОВЕРКИ", 13, 2.0))
        self.вердикт = label("", wrap=True, font_=font(FONT_HEAD, 28, W.Bold))
        слова.addWidget(self.вердикт)
        слова.addStretch(1)
        верх.addWidget(self.кольцо, 0, Qt.AlignVCenter)
        верх.addLayout(слова, 1)
        ил.addLayout(верх)
        ил.addSpacing(16)
        self.итоги = QGridLayout()
        self.итоги.setHorizontalSpacing(14)
        self.итоги.setVerticalSpacing(3)
        self.итоги.setColumnStretch(0, 1)
        ил.addLayout(self.итоги)
        ил.addStretch(1)
        # Проверку могли взять готовой, прошлую (этот же телефон приносили час назад). Это
        # обязано быть видно словами, и выход должен быть рядом: кнопка читает телефон заново.
        self.повтор_текст = label("", wrap=True, font_=font(FONT_TEXT, 16), color=C["warntext"])
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
        """Справа — клиент и комплект. Имя и телефон пришли с анкеты; здесь их можно поправить."""
        рамка, внутри = _карточка("КЛИЕНТ")
        self.имя = QLineEdit()
        self.имя.setPlaceholderText("Имя клиента")
        self.телефон = QLineEdit()
        self.телефон.setPlaceholderText("+7 7XX XXX XX XX")
        for поле in (self.имя, self.телефон):
            поле.textChanged.connect(self._проверить)
            внутри.addWidget(поле)

        внутри.addSpacing(8)
        внутри.addWidget(kicker("КОМПЛЕКТ", 14, 2.4, C["brand"]))
        ряд = QHBoxLayout()
        ряд.setSpacing(22)
        self.коробка = QCheckBox("Коробка")
        self.шнур = QCheckBox("Шнур")
        # Тип SIM не выбирают: вопрос один — есть ли SIM-лоток. Лотка нет — в Оценке это
        # строка прайса «(Esim)», другая цена.
        self.лоток = QCheckBox("SIM-лоток")
        self.лоток.setChecked(True)
        ряд.addWidget(self.коробка)
        ряд.addWidget(self.шнур)
        ряд.addWidget(self.лоток)
        ряд.addStretch(1)
        внутри.addLayout(ряд)
        # Про лоток кассе спрашивать не надо: его видно по кабелю (SIMTrayStatus, профиль
        # eSIM, второй IMEI). Подпись появляется, только когда по кабелю не вышло и отметить
        # должен сотрудник; когда определилось само — молчим, галочка и так стоит как надо.
        self.sim_подпись = label("", wrap=True, font_=font(FONT_TEXT, 15), color=C["muted"])
        self.sim_подпись.hide()
        внутри.addWidget(self.sim_подпись)

        # Цвет касса берёт из базы IMEI. Блок появляется, только когда база цвета не дала:
        # тогда его выбирает сотрудник — кнопкой из словаря (pintel_core.colours), без ввода.
        self.цвет_нужен, self.цвет_выбран, self.цвет_кнопки, self.цвет_модель = False, None, {}, None
        self.цвет_блок = QWidget()
        self.цвет_блок.setStyleSheet(QSS_ЦВЕТА)
        цл = QVBoxLayout(self.цвет_блок)
        цл.setContentsMargins(0, 8, 0, 0)
        цл.setSpacing(8)
        цл.addWidget(kicker("ЦВЕТ", 14, 2.4, C["brand"]))
        self.цвет_подпись = label("", wrap=True, font_=font(FONT_TEXT, 15), color=C["muted"])
        цл.addWidget(self.цвет_подпись)
        self.цвет_сетка = QGridLayout()
        self.цвет_сетка.setSpacing(8)
        цл.addLayout(self.цвет_сетка)
        self.цвет_блок.hide()
        внутри.addWidget(self.цвет_блок)

        внутри.addSpacing(8)
        внутри.addWidget(kicker("ЗАМЕТКА", 14, 2.4, C["brand"]))
        self.комментарий = QTextEdit()
        self.комментарий.setPlaceholderText("Сколы, состояние корпуса")
        внутри.addWidget(self.комментарий, 1)
        return рамка

    def _справа(self):
        """В центре — что нужно сделать прямо сейчас. Одна страница на шаг."""
        self.правая = QStackedWidget()
        self.правая.currentChanged.connect(lambda _=0: self._шаги_обновить())

        # --- шаг Apple: один раздел на телефоне
        apple, ал = _фокус("Откройте на телефоне «Об этом устройстве»")
        ал.addWidget(label("Apple сама скажет, что менялось.", "muted", wrap=True))
        ал.addSpacing(10)
        for i, t in enumerate(("Настройки → Основные", "Об этом устройстве",
                               "«Детали и обслуживание» — если она есть"), 1):
            строка = QHBoxLayout()
            строка.setSpacing(16)
            номер = label(str(i), font_=font(FONT_NUM, 22, W.Bold), color=C["cyan"])
            номер.setFixedWidth(26)
            строка.addWidget(номер)
            строка.addWidget(label(t, wrap=True, font_=font(FONT_TEXT, 24, W.DemiBold)), 1)
            ал.addLayout(строка)
        ал.addStretch(1)
        ал.addWidget(label("Строки может не быть: Apple показывает её, только если деталь меняли.",
                           "muted", wrap=True))
        b_пропуск = _кнопка("Сделает сотрудник", "small")
        b_пропуск.clicked.connect(self.пропустить_apple.emit)
        ал.addWidget(b_пропуск, 0, Qt.AlignLeft)

        # --- тест на телефоне клиента: QR слева, результат справа
        тест, тл = _фокус("Тест на телефоне клиента")
        self.тест_подсказка = label(ПОДСКАЗКА_ТЕСТА, "muted", wrap=True)
        тл.addWidget(self.тест_подсказка)
        тл.addSpacing(6)
        пара = QHBoxLayout()
        пара.setSpacing(34)
        код_теста = QVBoxLayout()
        код_теста.setSpacing(8)
        self.qr_тест = QrBlock(230)
        код_теста.addWidget(self.qr_тест, 0, Qt.AlignHCenter)
        self.тест_ссылка = label("", wrap=True, font_=font(FONT_TEXT, 15), color=C["muted"])
        self.тест_ссылка.setAlignment(Qt.AlignHCenter)
        код_теста.addWidget(self.тест_ссылка)
        код_теста.addStretch(1)
        пара.addLayout(код_теста, 5)
        результат = QVBoxLayout()
        результат.setSpacing(0)
        результат.addWidget(kicker("РЕЗУЛЬТАТ", 13, 2.0))
        результат.addSpacing(8)
        self.тест_список = QVBoxLayout()
        self.тест_список.setSpacing(5)
        результат.addLayout(self.тест_список)
        результат.addStretch(1)
        пара.addLayout(результат, 6)
        тл.addLayout(пара, 1)
        ряд_теста = QHBoxLayout()
        ряд_теста.setSpacing(10)
        for надпись, что in (("Нет в нашей сети", self.пропустить_тест.emit),
                             ("Другой код", self.новый_тест.emit)):
            b = _кнопка(надпись, "small")
            b.clicked.connect(что)
            ряд_теста.addWidget(b)
        ряд_теста.addStretch(1)
        тл.addLayout(ряд_теста)

        # --- проверки руками: восемь плиток в две колонки
        ручная, рл = _фокус("Проверьте руками")
        рл.addWidget(label("Нажмите по плитке — «работает». Ещё раз — «не работает».",
                           "muted", wrap=True))
        рл.addSpacing(4)
        сетка = QGridLayout()
        сетка.setContentsMargins(0, 0, 0, 0)
        сетка.setHorizontalSpacing(12)
        сетка.setVerticalSpacing(10)
        self.пункты_ряды = {}
        for n, (ключ, имя, подробно) in enumerate(ocenka_media.ПУНКТЫ):
            r = ПунктРяд(ключ, имя, подробно)
            r.нажали.connect(self.отметить)
            self.пункты_ряды[ключ] = r
            сетка.addWidget(r, n // 2, n % 2)
        сетка.setColumnStretch(0, 1)
        сетка.setColumnStretch(1, 1)
        рл.addLayout(сетка, 1)
        self.ручная_итог = label("", wrap=True, font_=font(FONT_TEXT, 18, W.Bold))
        self.ручная_итог.setAlignment(Qt.AlignHCenter)
        рл.addWidget(self.ручная_итог)

        # --- автооценка: прайс подсказывает сотруднику в боте, касса показывает его сумму
        # До 13.11.2026 касса показывала цену из прайса крупно, как готовое предложение. Теперь
        # цена из прайса уходит подсказкой в бот — тому, кто оценивает, на его телефон; он
        # там же пишет, какую сумму показать клиенту. Касса всё это время говорит одно:
        # «Пожалуйста, подождите», — и потом показывает сумму сотрудника. Самой автоцены на
        # экране нет: на него смотрит и клиент.
        цена, цл = _фокус("Автооценка")
        цл.addStretch(2)
        self.цена_число = label("—", font_=font(FONT_NUM, 92, W.Bold))
        self.цена_число.setAlignment(Qt.AlignHCenter)
        цл.addWidget(self.цена_число)
        цл.addSpacing(4)
        self.цена_подпись = label("", wrap=True, font_=font(FONT_TEXT, 21, W.Medium),
                                  color=C["muted"])
        self.цена_подпись.setAlignment(Qt.AlignHCenter)
        цл.addWidget(self.цена_подпись)
        # Сотрудник не заметил вопрос бота — по кнопке бот напишет ему ещё раз.
        self.b_напомнить_сумму = _кнопка(НАПОМНИТЬ, "small")
        self.b_напомнить_сумму.clicked.connect(self.напомнить.emit)
        self.b_напомнить_сумму.hide()
        цл.addSpacing(10)
        цл.addWidget(self.b_напомнить_сумму, 0, Qt.AlignHCenter)
        self.напомнить_сумму_итог = label("", wrap=True, font_=font(FONT_TEXT, 16), color=C["muted"])
        self.напомнить_сумму_итог.setAlignment(Qt.AlignHCenter)
        self.напомнить_сумму_итог.hide()
        цл.addWidget(self.напомнить_сумму_итог)
        цл.addStretch(3)
        self.цена_дальше = label("", wrap=True, font_=font(FONT_TEXT, 20, W.Medium))
        цл.addWidget(self.цена_дальше)
        # «Пожалуйста, подождите…» с бегущими точками: видно, что программа жива
        self._точки, self._точек = QTimer(self), 0
        self._точки.setInterval(450)
        self._точки.timeout.connect(self._шаг_точек)

        # --- фото и видео: QR слева (только без привязки), что уже дошло до бота — справа
        медиа, мл = _фокус("Фото и видео — через бота")
        self.медиа = label(ПОДСКАЗКА_МЕДИА, "muted", wrap=True)
        мл.addWidget(self.медиа)
        мл.addSpacing(6)
        пара_м = QHBoxLayout()
        пара_м.setSpacing(34)
        # QR для медиа нужен только сделке без привязки. Привязанной бот пишет сам, и на
        # месте кода стоит то, что сотруднику делать: открыть бота.
        self.медиа_код = QWidget()
        код_медиа = QVBoxLayout(self.медиа_код)
        код_медиа.setContentsMargins(0, 0, 0, 0)
        код_медиа.setSpacing(6)
        self.qr = QrBlock(230)
        код_медиа.addWidget(self.qr, 0, Qt.AlignHCenter)
        self.код = label("—", font_=font(FONT_NUM, 34, W.Bold))
        self.код.setAlignment(Qt.AlignHCenter)
        код_медиа.addWidget(self.код)
        # Адреса бота под кодом нет: если QR не считался, сотрудник вводит боту сам код
        self.адрес_бота = ""
        код_медиа.addStretch(1)
        пара_м.addWidget(self.медиа_код, 5)
        self.медиа_бот = QWidget()
        бот_сл = QVBoxLayout(self.медиа_бот)
        бот_сл.setContentsMargins(0, 0, 0, 0)
        бот_сл.setSpacing(8)
        бот_сл.addWidget(kicker("НА ВАШЕМ ТЕЛЕФОНЕ", 13, 2.0))
        self.медиа_бот_заголовок = label("Откройте бота Оценки", wrap=True,
                                         font_=font(FONT_HEAD, 30, W.Bold))
        бот_сл.addWidget(self.медиа_бот_заголовок)
        self.медиа_бот_текст = label("", wrap=True, font_=font(FONT_TEXT, 20, W.Medium),
                                     color=C["body"])
        бот_сл.addWidget(self.медиа_бот_текст)
        # Сотрудник нажал в боте что-то другое, и запрос фото и видео уехал вверх по чату.
        # Сделка цела, но ему это неоткуда узнать: по кнопке бот пишет ему ещё раз.
        self.b_напомнить = _кнопка(НАПОМНИТЬ, "small")
        self.b_напомнить.clicked.connect(self.напомнить.emit)
        self.b_напомнить.hide()
        бот_сл.addSpacing(6)
        бот_сл.addWidget(self.b_напомнить, 0, Qt.AlignLeft)
        self.напомнить_итог = label("", wrap=True, font_=font(FONT_TEXT, 16), color=C["muted"])
        self.напомнить_итог.hide()
        бот_сл.addWidget(self.напомнить_итог)
        бот_сл.addStretch(1)
        пара_м.addWidget(self.медиа_бот, 5)
        self.медиа_бот.hide()
        дошло = QVBoxLayout()
        дошло.setSpacing(0)
        дошло.addWidget(kicker("ЧТО УЖЕ ДОШЛО", 13, 2.0))
        дошло.addSpacing(8)
        # Что уже дошло до бота — живьём. Касса спрашивает об этом сервер (он читает базу
        # Оценки), и пока фото, видео и отметки не собраны, «Отправить в Оценку» не
        # нажимается: иначе карточка уходит в группу без медиа, а отказ прилетает минутой
        # позже, когда телефон клиента уже в руках.
        self.медиа_список = QVBoxLayout()
        self.медиа_список.setSpacing(8)
        дошло.addLayout(self.медиа_список)
        дошло.addStretch(1)
        пара_м.addLayout(дошло, 6)
        мл.addLayout(пара_м, 1)
        ряд_медиа = QHBoxLayout()
        self.b_другой_код = _кнопка("Другой код", "small")
        self.b_другой_код.clicked.connect(self.новый_код.emit)
        ряд_медиа.addWidget(self.b_другой_код)
        ряд_медиа.addStretch(1)
        мл.addLayout(ряд_медиа)

        # --- отправлено
        готово, гл = _фокус("Сделка отправлена")
        гл.addStretch(1)
        self.успех = Успех()
        гл.addWidget(self.успех, 0, Qt.AlignHCenter)
        гл.addSpacing(10)
        self.номер = label("—", font_=font(FONT_NUM, 52, W.Bold))
        self.номер.setAlignment(Qt.AlignHCenter)
        гл.addWidget(self.номер)
        self.итог_текст = label("", "muted", wrap=True)
        self.итог_текст.setAlignment(Qt.AlignHCenter)
        гл.addWidget(self.итог_текст)
        гл.addStretch(1)

        for w in (apple, тест, ручная, цена, медиа, готово):   # порядок — СТР_APPLE…СТР_ГОТОВО
            self.правая.addWidget(w)
        return self.правая

    # ---------- шаги сделки ----------
    def _к_шагу(self, шаг):
        """Нажали по шагу сверху — показываем его страницу."""
        if not self.отправлено and шаг in СТРАНИЦА_ШАГА:
            self.правая.setCurrentIndex(СТРАНИЦА_ШАГА[шаг])

    def _шаги_обновить(self):
        """Строка шагов: что сделано, что идёт, где мы сейчас."""
        if not hasattr(self, "степпер") or not hasattr(self, "правая"):
            return
        с = self.медиа_состояние or {}
        # «Автооценка» закрыта, когда бот ответил, почему цены нет, — или сотрудник назвал
        # в боте сумму клиенту. У сделки без привязки цены на кассе нет: её назовёт бот,
        # когда создаст сделку, — поэтому шаг зеленеет только после отправки. Зелёный без
        # цены был бы неправдой.
        цена_есть = bool(self.цена.get("готово")) if self.привязка is not None else False
        сделано = [bool(self.готово), self._тест_закрыт(), ocenka_media.готова(self.ручная),
                   bool(цена_есть or self.отправлено),
                   bool(с.get("известно") and с.get("готово"))]
        текущий = ШАГ_СТРАНИЦЫ.get(self.правая.currentIndex(), 0)
        self.степпер.set(сделано, текущий,
                         доступны=() if self.отправлено else tuple(СТРАНИЦА_ШАГА),
                         идут=() if self.готово else (0,))

    # ---------- состояния ----------
    def начать(self):
        """Новая сделка: поля пустые, проверка с нуля."""
        self.rep, self.готово, self.отправлено = {}, False, False
        self.тест, self.тест_пропущен = {}, ""
        self.ручная = {}
        self.медиа_состояние, self._подсказка = {}, ""
        self.цена = {}
        self.set_привязка(None)
        self.история = {}                              # угол чистый: это другой телефон
        self.история_панель.hide()
        self.история_плашка.set(история_мод.словами({}), False)
        self._нарисовать_ручную()
        self._нарисовать_тест()
        self._нарисовать_медиа()
        self.имя.clear()
        self.телефон.clear()
        self.комментарий.clear()
        self.коробка.setChecked(False)
        self.шнур.setChecked(False)
        self.лоток.setChecked(True)
        self.sim_подпись.setText("")
        self.sim_подпись.hide()
        self.цвет_нужен, self.цвет_выбран = False, None
        self.цвет_блок.hide()
        self.b_напомнить.hide()
        self.b_напомнить.setEnabled(True)
        self.напомнить_итог.hide()
        self.аппарат.setText("Подключите телефон кабелем")
        self.аппарат_подробно.setText("")
        self.ошибка.setText("")
        self._нарисовать_повтор({})
        self.подсказка.setText("Не отключайте кабель. Обычно это занимает около минуты.")
        for r in self.шаги.values():
            r.set("wait", "")
        self.кольцо.set(None)
        self.вердикт.setText("")
        self.вердикт_подпись.setText("")
        self.set_состояние("")
        self.режим(False)
        self.стопка.setCurrentIndex(0)
        self.правая.setCurrentIndex(СТР_ТЕСТ)
        self._очистить_итоги()
        self._нарисовать_цену()
        self.b_отправить.setText(ОТПРАВИТЬ)
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
        """Плашка состояния: выбор сотрудника, а если проверка его изменила — новое состояние
        цветом внимания. Причину на экран не пишем: строка выходила длиннее самой плашки, а
        оценщику она и так уходит в карточку сделки."""
        if not текст:
            self.состояние.hide()
            return
        текст = без_значка(текст)
        if причина:
            self.состояние.setText(str(текст))
            self.состояние.setStyleSheet(f"background: {C['warnbg']}; color: {C['warntext']}; "
                                         "border-radius: 14px; padding: 6px 16px;")
        else:
            self.состояние.setText(str(текст))
            self.состояние.setStyleSheet(f"background: {C['tint']}; color: {C['brand']}; "
                                         "border-radius: 14px; padding: 6px 16px;")
        self.состояние.show()

    # ---------- история телефона ----------
    def set_история(self, данные):
        """Ответ сервера (или None, пока спрашиваем) → плашка в углу и список под ней."""
        self.история = данные
        вид = история_мод.словами(данные)
        if not вид["строки"]:
            self.история_панель.hide()
        self.история_плашка.set(вид, not self.история_панель.isHidden())
        self.история_панель.наполнить(вид)
        if not self.история_панель.isHidden():
            self._историю_положить()

    def история_переключить(self):
        """Нажали по плашке: список развернулся. Нажали снова — угол опять пустой."""
        вид = история_мод.словами(self.история)
        открыть = bool(вид["строки"]) and self.история_панель.isHidden()
        if открыть:
            self.история_панель.наполнить(вид)
            self._историю_положить()
            self.история_панель.show()
            self.история_панель.raise_()
        else:
            self.история_панель.hide()
        self.история_плашка.set(вид, открыть)

    def _историю_положить(self):
        """Панель — под плашкой, у правого края экрана."""
        ширина = min(820, max(420, int(self.width() * 0.42)))
        self.история_панель.setFixedSize(ширина, self.история_панель.высота_для(ширина))
        угол = self.история_плашка.mapTo(self, self.история_плашка.rect().bottomRight())
        self.история_панель.move(max(16, угол.x() - ширина), угол.y() + 10)

    def resizeEvent(self, e):                                    # noqa: N802 — имя от Qt
        super().resizeEvent(e)
        if not self.история_панель.isHidden():
            self._историю_положить()

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
            self.правая.setCurrentIndex(self._стр_после_проверок())
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
        self.адрес_бота = str(ссылка or "")
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
            self.правая.setCurrentIndex(self._стр_после_проверок()
                                        if ocenka_media.готова(self.ручная) else СТР_РУЧНАЯ)
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
                                             font_=font(FONT_TEXT, 20, W.Medium)))

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
            self.правая.setCurrentIndex(self._стр_после_проверок())
        self._проверить()
        # Отказ по пункту — это «Есть видимые дефекты», и плашка состояния обязана
        # измениться сразу, пока сотрудник смотрит на экран.
        self.проверки_руками.emit()

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
    # ---------- привязка и автооценка ----------
    def set_привязка(self, имя):
        """К кому привязана сделка. None — привязки нет: медиа собираем по QR, как раньше,
        и цену касса не показывает (её назовёт бот после создания сделки)."""
        self.привязка = None if имя is None else str(имя or "").strip()
        привязана = self.привязка is not None
        if hasattr(self, "медиа_код"):
            self.медиа_код.setVisible(not привязана)
            self.медиа_бот.setVisible(привязана)
            self.b_другой_код.setVisible(not привязана)
            self.медиа.setText(ПОДСКАЗКА_МЕДИА_БОТ if привязана else ПОДСКАЗКА_МЕДИА)
            self._нарисовать_медиа()
            self._нарисовать_цену()

    def проверки_закрыты(self) -> bool:
        """Кабель, тест на телефоне и проверки руками — всё, от чего зависит цена."""
        return bool(self.готово and self._тест_закрыт() and ocenka_media.готова(self.ручная))

    def _стр_после_проверок(self) -> int:
        """Куда вести после проверок: привязанную сделку — к цене, без привязки — к QR."""
        return СТР_ЦЕНА if self.привязка is not None else СТР_МЕДИА

    def set_цена(self, цена):
        """Что бот ответил о цене.

        {} — ещё не спрашивали; {"считаем": True} — ждём ответа бота;
        {"ждём_сумму": True, "цена": 185000} — бот посчитал и спросил сотрудника, какую сумму
        показать клиенту (в `беда` — почему он не смог ему написать);
        {"готово": True, "цена": 185000, "сумма": 170000} — сотрудник назвал сумму;
        {"готово": True, "цена": None, "почему": …} — автоцены нет, оценит человек;
        {"готово": True, "цена": 185000} без суммы — бот прежней версии: он сумму не
        спрашивает, показываем цену из прайса, как раньше."""
        self.цена = dict(цена or {})
        self._нарисовать_цену()
        self._проверить()

    def _автоцена(self):
        """Цена из прайса, которую назвал бот. None — её нет или бот ещё не ответил."""
        цена = self.цена.get("цена") if (self.цена.get("готово") or self.цена.get("ждём_сумму")) else None
        return int(цена) if цена else None

    def сумма_клиенту(self):
        """Сумма, которую сотрудник назвал в боте и которую показываем клиенту. → число/None."""
        сумма = self.цена.get("сумма") if self.цена.get("готово") else None
        return int(сумма) if сумма else None

    def _ждём_цену(self) -> bool:
        """Бот считает цену или сотрудник ещё не назвал сумму — экран просит подождать."""
        return bool(self.цена.get("считаем") or self.цена.get("ждём_сумму"))

    def _шаг_точек(self):
        self._точек = (self._точек + 1) % 4
        if self._ждём_цену() and self.цена_число.text().startswith(ПОДОЖДИТЕ):
            self.цена_число.setText(ПОДОЖДИТЕ + "." * self._точек)

    def _нарисовать_цену(self):
        if not hasattr(self, "цена_число"):
            return
        # внизу страницы — только к кому привязана сделка; имя не склоняем, пишем отдельно
        дальше = f"Сделка привязана к: {self.привязка}." if self.привязка else ""
        ждём, напомнить = False, False
        if self.привязка is None:
            число, цвет = "—", C["ghost"]
            подпись = "Сделка не привязана к сотруднику — цену назовёт бот после отправки."
            дальше = "Пришлите боту фото и видео по коду на следующем шаге, затем отправьте оценку."
        elif not self.проверки_закрыты():
            число, цвет = "—", C["ghost"]
            подпись = "Появится, когда закончатся проверка, тест на телефоне и проверки руками."
        elif self.цена.get("готово") and self.сумма_клиенту():
            число, цвет = деньги(self.сумма_клиенту()), C["ok"]
            подпись = ""                               # сумма говорит сама за себя
        elif self.цена.get("готово") and self.цена.get("цена"):
            число, цвет = деньги(self.цена["цена"]), C["ok"]     # бот прежней версии
            подпись = ""
        elif self.цена.get("готово"):
            число, цвет = "Оценит человек", C["warntext"]
            подпись = ("Автоцены нет: " + str(self.цена.get("почему") or "причина не названа")
                       + ". Сделка уйдёт оценщику.")
        elif self.цена.get("ждём_сумму"):
            число, цвет, ждём, напомнить = ПОДОЖДИТЕ, C["muted"], True, True
            подпись = str(self.цена.get("беда") or "")          # бот не смог написать сотруднику
        else:
            число, цвет, ждём = ПОДОЖДИТЕ, C["muted"], True
            подпись = ""
        # длинные «Оценит человек» и «Пожалуйста, подождите» в размер цены не помещаются
        self.цена_число.setFont(font(FONT_NUM if число[:1].isdigit() else FONT_HEAD,
                                     92 if число[:1].isdigit() else 56, W.Bold))
        if not (ждём and self.цена_число.text().startswith(ПОДОЖДИТЕ)):
            self.цена_число.setText(число)             # точки бегут сами — не сбрасываем их
        self.цена_число.setStyleSheet(f"color: {цвет}")
        self.цена_подпись.setText(подпись)
        self.цена_подпись.setStyleSheet(
            f"color: {C['warntext'] if (ждём and подпись) else C['muted']}")
        self.цена_дальше.setText(дальше)
        self.b_напомнить_сумму.setVisible(напомнить and not self.отправлено)
        if not напомнить:
            self.напомнить_сумму_итог.hide()
        if ждём and not self._точки.isActive():
            self._точки.start()
        elif not ждём:
            self._точки.stop()

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
        if self.привязка is not None and hasattr(self, "медиа_бот_текст"):
            # имя не склоняем — ставим его отдельной фразой
            кому = f" Привязано: {self.привязка}." if self.привязка else ""
            if not self.отправлено:
                self.медиа_бот_заголовок.setText("Сначала — отправка")
                self.медиа_бот_текст.setText(
                    f"Нажмите «{ОТПРАВИТЬ}» внизу. Бот сразу напишет вам и попросит фото и "
                    "видео." + кому)
            elif с.get("медиа_просили") or с.get("фото") or с.get("видео"):
                self.b_напомнить.setVisible(not с.get("сделка") and not с.get("готово"))
                self.медиа_бот_заголовок.setText("Откройте бота Оценки")
                self.медиа_бот_текст.setText(
                    "Бот ждёт от вас по одному: фото экрана с *#06#, лицевую сторону, заднюю и "
                    "видео. После видео сделка создастся сама." + кому)
            else:
                self.медиа_бот_заголовок.setText("Бот пишет вам…")
                self.медиа_бот_текст.setText(
                    "Сообщение придёт в бот Оценки через пару секунд." + кому)
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
                             else f"Проверки руками — все {len(ocenka_media.КЛЮЧИ)}"),
                      ocenka_media.готова(self.ручная)))
        for текст, есть in строки:
            значок, цвет = ("✓", C["ok"]) if есть else ("○", C["warntext"])
            строка = label(f"{значок}  {текст}", wrap=True, color=цвет,
                           font_=font(FONT_TEXT, 21, W.Bold if not есть else W.Medium))
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
        self.итоги.addWidget(label(ключ, font_=font(FONT_TEXT, 18), color=C["muted"]), n, 0,
                             Qt.AlignLeft | Qt.AlignTop)
        текст = label(значение, font_=font(FONT_TEXT, 18, W.DemiBold), color=цвет)
        if len(str(значение or "")) > ДЛИННАЯ_СТРОКА_ИТОГА:
            # Длинное («Apple: аккумулятор требует обслуживания (износ, деталь родная)»)
            # край карточки обрезал на полуслове. Такая строка занимает весь ряд и
            # переносится; короткие стоят как стояли — справа, в одну строку.
            текст.setWordWrap(True)
            текст.setAlignment(Qt.AlignRight | Qt.AlignTop)
            self.итоги.addWidget(текст, n, 0 if not ключ else 1, 1, 2 if not ключ else 1)
        else:
            self.итоги.addWidget(текст, n, 1, Qt.AlignRight)

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
            пас.get("модель"), f"{пам.get('объём_гб')} ГБ" if пам.get("объём_гб") else None) if x))
        self.аппарат_подробно.setText(" · ".join(x for x in (
            f"iOS {пас.get('ios')}" if пас.get("ios") else None,
            f"IMEI {пас.get('imei')}" if пас.get("imei") else None) if x))
        self._очистить_итоги()

        # Главное — крупно в паспорте: кольцо батареи и вердикт одним словом. Раньше оба
        # сидели мелкими плашками в общем ряду, и глаз искал их среди пяти одинаковых.
        слово, цвет_слова = ВЕРДИКТЫ.get(итог, (итог.capitalize() or "Проверка", C["warntext"]))
        self.вердикт.setText(слово)
        self.вердикт.setStyleSheet(f"color: {цвет_слова}")
        здоровье = бат.get("здоровье_%")
        self.кольцо.set(здоровье)
        if здоровье is None:
            self.вердикт_подпись.setText("не прочиталась")
        else:
            self.вердикт_подпись.setText(циклов(бат["циклы"]) if бат.get("циклы") is not None
                                         else "циклы не прочитались")
        плашки = []
        повтор = self.rep.get("повторная_проверка") or {}
        if повтор:
            плашки.append(("Проверка прошлая · " + str(повтор.get("словами") or ""),
                           C["warnbg"], C["warntext"]))
        self._нарисовать_повтор(повтор)
        if вердикт.get("apple_подтверждено"):
            плашки.append(("Apple подтвердила детали", C["tint"], C["brand"]))
        пан = self.rep.get("паника") or {}
        if пан.get("panic_full"):
            плашки.append(("Сбои ядра: есть отчёт", C["badbg"], C["badtext"]))
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
        self.лоток.setChecked(ocenka.sim_для_оценки(пас) == ocenka.SIM_ЛОТОК)
        self._сказать_про_sim(пас)
        self._спросить_цвет(пас)
        if not self.отправлено:
            # проверка кабелем кончилась — теперь тест на телефоне, он идёт перед медиа
            self.правая.setCurrentIndex(self._стр_после_проверок() if self._тест_закрыт()
                                        else СТР_ТЕСТ)
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
        self.аппарат_подробно.setText("")
        self.подсказка.setText("Не отключайте кабель. Обычно это занимает около минуты.")
        self.сказать("", беда=False)
        self._проверить()

    def _сказать_про_sim(self, пас):
        """Есть ли SIM-лоток, читается по кабелю, а не спрашивается у сотрудника. Подпись —
        только когда прочитать не вышло и галочку надо поставить самому."""
        from pintel_core.external import ocenka
        if self.rep.get("запечатанный"):
            подпись = "Запечатанный: SIM-лоток по кабелю не читается — отметьте сами."
        elif ocenka.лоток_определён(пас):
            подпись = ""
        else:
            подпись = "SIM-лоток по телефону не определился — отметьте сами."
        self.sim_подпись.setText(подпись)
        self.sim_подпись.setVisible(bool(подпись))

    # ---------- цвет ----------
    def _спросить_цвет(self, пас):
        """Кнопки цвета — только когда цвет не определился сам. Определился — блока нет, и
        спрашивать сотрудника не о чем.

        Отчёт на экране перерисовывается не раз (поздний вердикт Apple, ответ базы IMEI),
        поэтому уже сделанный выбор здесь не сбрасывается: его снимает только новая сделка."""
        self.цвет_нужен = not colours.цвет(пас.get("цвет"))
        self.цвет_модель = пас.get("модель")
        self.цвет_блок.setVisible(self.цвет_нужен)
        if not self.цвет_нужен:
            self.цвет_выбран = None                    # база ответила — берём её слово
            return
        имена = colours.цвета_модели(пас.get("модель"))
        if self.цвет_выбран and self.цвет_выбран not in имена:
            имена = имена + (self.цвет_выбран,)        # взят из полного списка — остаётся кнопкой
        self._кнопки_цвета(имена)
        self._показать_выбор()

    def _кнопки_цвета(self, имена):
        """Кнопки цветов модели в два столбца и «Другой цвет» последней. Модели нет в списке —
        остаётся одна кнопка, она открывает весь словарь."""
        while self.цвет_сетка.count():
            w = self.цвет_сетка.takeAt(0).widget()
            if w is not None:
                w.setParent(None)                     # сразу с экрана: deleteLater уберёт позже,
                w.deleteLater()                       # и прежние кнопки рисовались бы под новыми
        self.цвет_кнопки = {}
        for n, имя in enumerate(имена):
            b = _кнопка_цвета(имя, модель=self.цвет_модель)
            b.clicked.connect(lambda _=False, имя=имя: self._цвет_нажат(имя))
            self.цвет_сетка.addWidget(b, n // 2, n % 2)
            self.цвет_кнопки[имя] = b
        self.цвет_другой = QPushButton("Другой цвет…" if имена else "Выбрать цвет…")
        self.цвет_другой.setObjectName("chip_more")
        self.цвет_другой.setCursor(Qt.PointingHandCursor)
        self.цвет_другой.setFont(font(FONT_TEXT, 15, W.DemiBold))
        self.цвет_другой.clicked.connect(self._другой_цвет)
        self.цвет_сетка.addWidget(self.цвет_другой, len(имена) // 2, len(имена) % 2)

    def _показать_выбор(self):
        for k, b in self.цвет_кнопки.items():
            b.setChecked(k == self.цвет_выбран)
        # Подсказка — пока цвет не выбран. Выбран — её нет: какое слово уйдёт в сделку, на
        # экране не пишем (так решил владелец), выбор видно по самой кнопке.
        self.цвет_подпись.setText("" if self.цвет_выбран else "По базе цвет не определился — выберите.")
        self.цвет_подпись.setVisible(not self.цвет_выбран)

    def _цвет_нажат(self, имя):
        """Сотрудник выбрал цвет — кнопкой модели или в полном списке."""
        if имя not in colours.КАНОН:
            return                                    # в сделку идёт только слово словаря
        self.цвет_выбран = имя
        if имя not in self.цвет_кнопки:               # взят из полного списка — ставим кнопкой
            self._кнопки_цвета(tuple(self.цвет_кнопки) + (имя,))
        self._показать_выбор()
        self._проверить()

    def _другой_цвет(self):
        окно = ВыборЦвета(self, self.цвет_выбран)
        if окно.exec() and окно.выбран:
            self._цвет_нажат(окно.выбран)

    def напоминание(self, итог):
        """Что вышло с напоминанием в боте. `None` — запрос ушёл, ждём ответа сервера.

        Кнопок две, дело одно: на шаге «Автооценка» бот повторяет вопрос о сумме клиенту, на
        шаге «Фото и видео» — просьбу о медиа. Что именно напомнить, решает сервер по тому,
        чего сделка ждёт; здесь итог пишется под той кнопкой, которая сейчас на экране."""
        кнопки = (self.b_напомнить, self.b_напомнить_сумму)
        подпись = self.напомнить_сумму_итог if self.цена.get("ждём_сумму") else self.напомнить_итог
        if итог is None:
            for b in кнопки:
                b.setEnabled(False)
            подпись.setText("Пишем вам в бот…")
            подпись.setStyleSheet(f"color: {C['muted']}")
            подпись.show()
            return
        ок = bool((итог or {}).get("отправлено"))
        подпись.setText("Бот написал вам ещё раз — откройте его." if ок else
                        "Не вышло: " + str((итог or {}).get("почему") or "сервер не ответил"))
        подпись.setStyleSheet(f"color: {C['ok'] if ок else C['warntext']}")
        подпись.show()
        # подряд не жмём: бот не должен засыпать сотрудника одинаковыми сообщениями
        QTimer.singleShot(ПАУЗА_НАПОМНИТЬ_МС if ок else 3000,
                          lambda: [b.setEnabled(True) for b in кнопки])

    def показать_починку(self, видно, занято=False, текст=""):
        """Кнопка «Починить связь» в карточке телефона: видна, пока телефон не прочитан."""
        self.b_связь.setVisible(bool(видно))
        self.b_связь.setEnabled(not занято)
        self.b_связь.setText(текст or ПОЧИНИТЬ_СВЯЗЬ)

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

    def ушло(self, код, текст="", ждём_медиа=False):
        """Оценка отправлена. `ждём_медиа` — сделка привязана, и бот сейчас попросит у
        сотрудника фото и видео: показываем их приход, а «готово» — когда сделка создана."""
        self.отправлено = True
        self.номер.setText(str(код or "—"))
        self.итог_текст.setText(текст or "Сделка создаётся. Номер появится здесь.")
        self.правая.setCurrentIndex(СТР_МЕДИА if ждём_медиа else СТР_ГОТОВО)
        self.b_печать.setEnabled(True)
        self.b_отправить.setEnabled(False)
        self.b_отправить.setText("Отправлено" if ждём_медиа else ОТПРАВИТЬ)
        self.b_отмена.setText("Новая оценка")
        self._нарисовать_цену()
        self._нарисовать_медиа()
        self._шаги_обновить()

    def сделка_создана(self, номер):
        """Номер сделки из Оценки. Приходит через сервер: сделку создаёт бот — сразу после
        отправки, а у привязанной сделки — как только сотрудник прислал последнее медиа."""
        # На экране — только то, что назвали клиенту. Цена из прайса сюда не идёт: она была
        # подсказкой сотруднику. Бот прежней версии суммы не спрашивал — тогда цена из прайса.
        цена, сумма = self._автоцена(), self.сумма_клиенту()
        деньгами = (f"\nСумма клиенту: {деньги(сумма)}" if сумма
                    else f"\nАвтооценка: {деньги(цена)}" if цена else "")
        self.итог_текст.setText(f"Сделка № {номер} создана — она уже у оценщика в боте." + деньгами)
        self.правая.setCurrentIndex(СТР_ГОТОВО)
        self._шаги_обновить()

    def сделка_не_вышла(self, почему):
        """Бот не смог создать сделку. Говорим словами и даём отправить заново.

        Молчать тут нельзя: на экране написано «отправлено», сотрудник ждёт номера, а
        его не будет — и узнает он об этом, только когда клиент уже ушёл."""
        self.отправлено = False
        self.итог_текст.setText("Сделка не создалась: " + str(почему or "причина неизвестна")
                                + "\nИсправьте и отправьте ещё раз.")
        self.b_отправить.setEnabled(self._годно())
        self.b_отправить.setText(ОТПРАВИТЬ)
        if self.привязка is not None:
            # причина видна там, где сотрудник ждал сообщение бота, а не на пустом «готово»
            self.правая.setCurrentIndex(СТР_ЦЕНА)
            self.сказать("Сделка не создалась: " + str(почему or "причина неизвестна"))
        self._нарисовать_цену()
        self._нарисовать_медиа()
        self._шаги_обновить()

    def занято(self, текст=""):
        self.b_отправить.setEnabled(not текст and self._годно())
        self.b_отправить.setText(текст or ОТПРАВИТЬ)

    # ---------- данные ----------
    def данные(self):
        """Автоцену считает бот Оценки по своему прайсу (google_price) — здесь она только
        пересказана. Сумму клиенту сотрудник называет в боте, касса её показывает."""
        return {"имя": self.имя.text().strip(), "телефон": нормальный_телефон(self.телефон.text()),
                "коробка": self.коробка.isChecked(), "шнур": self.шнур.isChecked(),
                "sim": "Стандарт" if self.лоток.isChecked() else "E-sim",   # есть лоток / нет
                "цвет": self.цвет_выбран,                # только когда выбирал сотрудник
                # что сотрудник назвал клиенту (в боте) и что ему подсказал прайс
                "сумма_клиенту": self.сумма_клиенту(), "автоцена": self._автоцена(),
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
        # Привязанной сделке медиа перед отправкой не нужны: бот попросит их сам, после неё.
        медиа = True if self.привязка is not None else self._медиа_готовы()
        # Цвет, которого не дала база, сотрудник выбирает здесь: в боте его больше не спросят.
        цвет = bool(self.цвет_выбран) or not self.цвет_нужен
        return bool(self.готово and not self.отправлено and d["имя"] and d["телефон"] and цвет
                    and self._тест_закрыт() and ocenka_media.готова(self.ручная) and медиа
                    and self._цена_не_держит())

    def _цена_не_держит(self) -> bool:
        """Привязанная сделка ждёт, пока бот считает цену и пока сотрудник называет сумму.

        Не спрашивали вовсе (сервер не видит бота, посылку не собрать) — не держим: цену
        такой сделке назовёт оценщик, как и раньше. Молчит сам бот — тоже не держим: через
        полминуты касса запишет «бот не ответил». А вот сотрудника ждём, сколько нужно:
        сумму клиенту, кроме него, назвать некому."""
        return self.привязка is None or not self._ждём_цену()

    def почему_нельзя(self) -> str:
        """Что мешает отправить — словами. На экран из этого идёт только «впишите клиента»
        (см. _проверить): остальное уже сказано шагами сверху и карточкой шага."""
        if self.отправлено or not self.готово:
            return ""
        d = self.данные()
        if not (d["имя"] and d["телефон"]):
            return "Впишите имя и телефон клиента."
        if self.цвет_нужен and not self.цвет_выбран:
            return "Выберите цвет телефона."
        if not self._тест_закрыт():
            осталось = [имя for _, имя in phonetest.пропущенные(self.тест)]
            return ("Нужен тест на телефоне клиента: " + ", ".join(осталось[:4])
                    + (f" и ещё {len(осталось) - 4}" if len(осталось) > 4 else "")
                    + ". Телефона нет в нашей сети — скажите об этом кнопкой.")
        if not ocenka_media.готова(self.ручная):
            осталось = ocenka_media.не_отмечено(self.ручная)
            return ("Отметьте проверки руками: "
                    + ", ".join(осталось[:4])
                    + (f" и ещё {len(осталось) - 4}" if len(осталось) > 4 else "") + ".")
        if not self._цена_не_держит():
            return ("Ждём ответа бота Оценки." if self.цена.get("считаем")
                    else "Ждём сумму: её называет сотрудник в боте Оценки.")
        if self.привязка is None and not self._медиа_готовы():
            нет = ocenka_media.чего_нет(self.медиа_состояние)
            если = ("Сканируйте QR и пришлите боту фото и видео. " if not self.медиа_состояние
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
        if self.привязка is not None:
            # у привязанной сделки медиа идут после отправки: чек — как только всё проверено
            return bool(self.отправлено or self.проверки_закрыты())
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
            # Что осталось на шаге, видно по шагам сверху и в карточке шага («Осталось
            # отметить 8 из 8», «Что уже дошло»). Третий раз, строкой внизу, это был шум.
            # Внизу говорим только то, чего на экране больше нет: не вписан клиент.
            d = self.данные()
            цвет_есть = bool(self.цвет_выбран) or not self.цвет_нужен
            мешает = "" if (d["имя"] and d["телефон"] and цвет_есть) else self.почему_нельзя()
            # Затираем только свою же подсказку: на этой строке живут и сообщения о беде
            # («тест не прошёл», «телефон с заменой»), и потерять их нельзя.
            if мешает or self.ошибка.text() == getattr(self, "_подсказка", ""):
                self.сказать(мешает, беда=False)
                self._подсказка = мешает
        self._шаги_обновить()
        return self._годно()

    def _отправить(self):
        d = self.данные()
        нет = [имя for имя, есть in (("имя клиента", d["имя"]), ("телефон клиента", d["телефон"]),
                                     ("результат проверки", self.готово),
                                     ("цвет телефона", bool(self.цвет_выбран) or not self.цвет_нужен),
                                     ("тест на телефоне", self._тест_закрыт()),
                                     ("проверки руками", ocenka_media.готова(self.ручная)),
                                     ("сумма клиенту — назовите её в боте Оценки",
                                      self._цена_не_держит()),
                                     ("фото и видео в боте",
                                      self.привязка is not None or self._медиа_готовы()))
               if not есть]
        if нет:
            self.сказать("Не хватает: " + ", ".join(нет))
            return
        self.ошибка.setText("")
        self.отправить.emit(d)
