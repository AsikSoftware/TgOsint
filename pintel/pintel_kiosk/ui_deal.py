# -*- coding: utf-8 -*-
"""Экраны сделки: клиент → оценка → чек.

Приложение работает само по себе, без нашего сервера: имя клиента сотрудник вводит в
начале, оценку оформляет здесь же, отсюда же сделка уходит в Оценку и печатается чек.

Поля экрана оценки — ровно те, что хранит Оценка: комплектность, SIM её словарём, цена,
комментарий, фото и видео. Видео обязательно: без него Оценка не открывает сделку
(её код берёт video_phone без проверки), и честнее сказать это здесь, чем создать
карточку, которую оценщик не сможет развернуть.
"""
import os
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QSizePolicy, QTextEdit, QVBoxLayout, QWidget)

from .ui import C, FONT_HEAD, FONT_NUM, FONT_TEXT, Screen, W, font, header, kicker, label, point_text

QSS_DEAL = """
QLineEdit, QComboBox, QTextEdit { background: #FFFFFF; border: 2px solid %(border)s; border-radius: 16px;
    padding: 18px 22px; font-size: 26px; color: %(ink)s; selection-background-color: %(tint)s; }
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border-color: %(action)s; }
QLineEdit[плохо="да"] { border-color: %(bad)s; }
QComboBox::drop-down { border: none; width: 44px; }
QCheckBox { font-size: 26px; font-weight: 600; spacing: 16px; }
QCheckBox::indicator { width: 34px; height: 34px; border: 2px solid %(ring)s; border-radius: 10px;
    background: #FFFFFF; }
QCheckBox::indicator:checked { background: %(action)s; border-color: %(action)s; }
QPushButton#ghost { background: transparent; color: %(body)s; border: 2px solid %(border)s;
    border-radius: 18px; font-size: 24px; font-weight: 700; min-height: 70px; padding: 0 32px; }
QPushButton#ghost:pressed { background: %(ground)s; }
QPushButton#file { background: %(tint)s; color: %(brand)s; border: none; border-radius: 16px;
    font-size: 22px; font-weight: 700; min-height: 62px; padding: 0 26px; }
QFrame#карточка { background: #FFFFFF; border: 2px solid %(border)s; border-radius: 24px; }
""" % C

ТЕЛЕФОН = re.compile(r"^\+?7\d{10}$")


def _кнопка(текст, главная=True):
    b = QPushButton(текст)
    b.setObjectName("primary" if главная else "ghost")
    b.setCursor(Qt.PointingHandCursor)
    return b


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


class ClientScreen(Screen):
    """Второй экран: имя и телефон клиента. Без них сделку в Оценку не создать."""

    дальше = Signal(str, str)
    назад = Signal()

    def __init__(self, point=""):
        super().__init__()
        self.setStyleSheet(QSS_DEAL)
        self.root.addLayout(header(label(point_text(point), "muted")))
        self.root.addSpacing(40)
        self.root.addWidget(label("Кто сдаёт телефон", font_=font(FONT_HEAD, 64, W.Bold, -1.0)))
        self.root.addSpacing(8)
        self.root.addWidget(label("Имя и номер нужны, чтобы оформить сделку и вернуть телефон владельцу.",
                                  "lead", wrap=True))
        self.root.addSpacing(44)
        сетка = QGridLayout()
        сетка.setHorizontalSpacing(40)
        сетка.setVerticalSpacing(14)
        self.имя = QLineEdit()
        self.имя.setPlaceholderText("Имя клиента")
        self.телефон = QLineEdit()
        self.телефон.setPlaceholderText("+7 7XX XXX XX XX")
        for столбец, (подпись, поле) in enumerate(((("ИМЯ"), self.имя), ("ТЕЛЕФОН", self.телефон))):
            поле.setMinimumWidth(620)
            поле.returnPressed.connect(self._дальше)
            поле.textChanged.connect(self._проверить)
            сетка.addWidget(kicker(подпись), 0, столбец)
            сетка.addWidget(поле, 1, столбец)
        self.root.addLayout(сетка)
        self.подсказка = label("", "muted", wrap=True)
        self.root.addSpacing(10)
        self.root.addWidget(self.подсказка)
        self.root.addStretch(1)
        ряд = QHBoxLayout()
        ряд.setSpacing(20)
        b_назад = _кнопка("Назад", главная=False)
        b_назад.clicked.connect(self.назад.emit)
        self.b_дальше = _кнопка("Далее — подключить телефон")
        self.b_дальше.clicked.connect(self._дальше)
        ряд.addWidget(b_назад)
        ряд.addStretch(1)
        ряд.addWidget(self.b_дальше)
        self.root.addLayout(ряд)
        self._проверить()

    def сбросить(self):
        self.имя.clear()
        self.телефон.clear()
        self.имя.setFocus()

    def _проверить(self):
        имя = self.имя.text().strip()
        тел = нормальный_телефон(self.телефон.text())
        годно = bool(имя) and bool(тел)
        self.b_дальше.setEnabled(годно)
        self.телефон.setProperty("плохо", "да" if (self.телефон.text().strip() and not тел) else "нет")
        self.телефон.style().unpolish(self.телефон)
        self.телефон.style().polish(self.телефон)
        self.подсказка.setText("" if годно else "Заполните имя и номер в формате +7 7XX XXX XX XX")
        return годно

    def _дальше(self):
        if self._проверить():
            self.дальше.emit(self.имя.text().strip(), нормальный_телефон(self.телефон.text()))


class EvalScreen(Screen):
    """Окно оценки: то, что раньше было карточкой сделки на сервере."""

    отправить = Signal(dict)
    назад = Signal()

    def __init__(self, point=""):
        super().__init__(gray=True)
        self.setStyleSheet(QSS_DEAL)
        self.фото, self.видео, self.rep = [], "", {}
        self.root.addLayout(header(label(point_text(point), "muted")))
        self.root.addSpacing(24)
        self.root.addWidget(label("Оформление оценки", font_=font(FONT_HEAD, 56, W.Bold, -1.0)))
        self.сводка = label("", "lead_s", wrap=True)
        self.root.addSpacing(6)
        self.root.addWidget(self.сводка)
        self.root.addSpacing(28)

        тело = QHBoxLayout()
        тело.setSpacing(40)
        тело.addLayout(self._левая(), 1)
        тело.addLayout(self._правая(), 1)
        self.root.addLayout(тело, 1)

        self.ошибка = label("", wrap=True, color=C["badtext"])
        self.root.addWidget(self.ошибка)
        ряд = QHBoxLayout()
        ряд.setSpacing(20)
        b_назад = _кнопка("Назад", главная=False)
        b_назад.clicked.connect(self.назад.emit)
        self.b_отправить = _кнопка("Отправить в Оценку")
        self.b_отправить.clicked.connect(self._отправить)
        ряд.addWidget(b_назад)
        ряд.addStretch(1)
        ряд.addWidget(self.b_отправить)
        self.root.addLayout(ряд)

    def _левая(self):
        кол = QVBoxLayout()
        кол.setSpacing(18)
        кол.addWidget(kicker("КОМПЛЕКТНОСТЬ"))
        self.коробка = QCheckBox("Коробка")
        self.шнур = QCheckBox("Шнур")
        кол.addWidget(self.коробка)
        кол.addWidget(self.шнур)
        кол.addSpacing(18)
        кол.addWidget(kicker("SIM"))
        self.sim = QComboBox()
        self.sim.addItems(["Стандарт", "Dual sim", "E-sim", "Прочее"])
        кол.addWidget(self.sim)
        кол.addSpacing(18)
        кол.addWidget(kicker("ЦЕНА, ₸"))
        self.цена = QLineEdit()
        self.цена.setPlaceholderText("Сумма, которую называем клиенту")
        кол.addWidget(self.цена)
        кол.addSpacing(18)
        кол.addWidget(kicker("КОММЕНТАРИЙ"))
        self.комментарий = QTextEdit()
        self.комментарий.setPlaceholderText("Состояние корпуса, сколы, что обещали клиенту")
        self.комментарий.setFixedHeight(150)
        кол.addWidget(self.комментарий)
        кол.addStretch(1)
        return кол

    def _правая(self):
        кол = QVBoxLayout()
        кол.setSpacing(18)
        кол.addWidget(kicker("ФОТО И ВИДЕО"))
        кол.addWidget(label("Видео обязательно: без него Оценка не открывает сделку.", "muted", wrap=True))
        ряд = QHBoxLayout()
        ряд.setSpacing(14)
        b_фото = QPushButton("Добавить фото")
        b_фото.setObjectName("file")
        b_фото.clicked.connect(self._выбрать_фото)
        b_видео = QPushButton("Выбрать видео")
        b_видео.setObjectName("file")
        b_видео.clicked.connect(self._выбрать_видео)
        ряд.addWidget(b_фото)
        ряд.addWidget(b_видео)
        ряд.addStretch(1)
        кол.addLayout(ряд)
        self.медиа = label("Пока ничего не выбрано", "muted", wrap=True)
        кол.addWidget(self.медиа)
        кол.addSpacing(18)
        кол.addWidget(kicker("ЧТО УВИДЕЛА ПРОВЕРКА"))
        карточка = QFrame()
        карточка.setObjectName("карточка")
        карточка.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.итоги = QVBoxLayout(карточка)
        self.итоги.setContentsMargins(28, 24, 28, 24)
        self.итоги.setSpacing(10)
        кол.addWidget(карточка, 1)
        return кол

    # ---------- наполнение ----------
    def показать(self, rep, цена=None):
        self.rep = rep or {}
        пас = self.rep.get("паспорт") or {}
        пам = self.rep.get("память") or {}
        бат = self.rep.get("батарея") or {}
        self.сводка.setText(" · ".join(x for x in (
            пас.get("модель"), f"{пам.get('объём_гб')} ГБ" if пам.get("объём_гб") else None,
            f"аккумулятор {бат.get('здоровье_%')}%" if бат.get("здоровье_%") is not None else None,
            пас.get("серийник")) if x))
        from pintel_core.external import ocenka
        self.sim.setCurrentText(ocenka.sim_для_оценки(пас))
        if цена:
            self.цена.setText(str(int(цена)))
        while self.итоги.count():
            w = self.итоги.takeAt(0).widget()
            if w:
                w.deleteLater()
        вердикт = self.rep.get("детали_вердикт") or {}
        итог = (self.rep.get("итог") or {}).get("вердикт") or ""
        цвет = {"ХОРОШИЙ": C["ok"], "ПРОБЛЕМНЫЙ": C["badtext"]}.get(итог, C["warntext"])
        self.итоги.addWidget(label(итог or "—", font_=font(FONT_HEAD, 34, W.Bold), color=цвет))
        for d in (вердикт.get("детали") or [])[:7]:
            знак = {"ok": "·", "repaired": "!", "used": "!", "bad": "×"}.get(d.get("статус"), "·")
            self.итоги.addWidget(label(f"{знак}  {d.get('деталь')} — {d.get('почему')}", "muted", wrap=True))
        for x in (self.rep.get("внимание") or [])[:4]:
            self.итоги.addWidget(label(f"!  {x}", "muted", wrap=True, color=C["warntext"]))
        self.итоги.addStretch(1)
        self.ошибка.setText("")

    def _выбрать_фото(self):
        пути, _ = QFileDialog.getOpenFileNames(self, "Фото телефона", "",
                                               "Изображения (*.jpg *.jpeg *.png *.heic)")
        self.фото.extend(p for p in пути if p not in self.фото)
        self._обновить_медиа()

    def _выбрать_видео(self):
        путь, _ = QFileDialog.getOpenFileName(self, "Видео телефона", "", "Видео (*.mp4 *.mov *.m4v)")
        if путь:
            self.видео = путь
        self._обновить_медиа()

    def _обновить_медиа(self):
        части = []
        if self.видео:
            части.append("видео: " + os.path.basename(self.видео))
        if self.фото:
            части.append(f"фото: {len(self.фото)} шт.")
        self.медиа.setText(" · ".join(части) or "Пока ничего не выбрано")

    def данные(self):
        цена = re.sub(r"\D", "", self.цена.text())
        return {"коробка": self.коробка.isChecked(), "шнур": self.шнур.isChecked(),
                "sim": self.sim.currentText(), "цена": int(цена) if цена else None,
                "комментарий": self.комментарий.toPlainText().strip(),
                "фото_пути": list(self.фото), "видео_путь": self.видео}

    def _отправить(self):
        d = self.данные()
        нет = []
        if not d["видео_путь"]:
            нет.append("видео телефона")
        if not d["цена"]:
            нет.append("цена")
        if нет:
            self.ошибка.setText("Не хватает: " + ", ".join(нет))
            return
        self.ошибка.setText("")
        self.отправить.emit(d)

    def занято(self, текст=""):
        """Пока идёт отправка — кнопка недоступна, видно что происходит."""
        self.b_отправить.setEnabled(not текст)
        self.b_отправить.setText(текст or "Отправить в Оценку")


class DoneScreen(Screen):
    """Сделка ушла: номер, печать чека, новая оценка."""

    печать = Signal()
    заново = Signal()

    def __init__(self):
        super().__init__(gray=True)
        self.setStyleSheet(QSS_DEAL)
        self.root.addStretch(1)
        self.заголовок = label("Сделка создана", font_=font(FONT_HEAD, 64, W.Bold, -1.0))
        self.root.addWidget(self.заголовок, 0, Qt.AlignHCenter)
        self.root.addSpacing(10)
        self.номер = label("", font_=font(FONT_NUM, 120, W.Bold))
        self.root.addWidget(self.номер, 0, Qt.AlignHCenter)
        self.подпись = label("", "lead", wrap=True)
        self.подпись.setAlignment(Qt.AlignHCenter)
        self.root.addSpacing(10)
        self.root.addWidget(self.подпись)
        self.root.addSpacing(48)
        ряд = QHBoxLayout()
        ряд.setSpacing(20)
        ряд.addStretch(1)
        b_печать = _кнопка("Печать чека", главная=False)
        b_печать.clicked.connect(self.печать.emit)
        b_новая = _кнопка("Новая оценка")
        b_новая.clicked.connect(self.заново.emit)
        ряд.addWidget(b_печать)
        ряд.addWidget(b_новая)
        ряд.addStretch(1)
        self.root.addLayout(ряд)
        self.root.addStretch(1)

    def показать(self, номер, подпись=""):
        self.номер.setText(f"№ {номер}" if номер else "")
        self.подпись.setText(подпись)
