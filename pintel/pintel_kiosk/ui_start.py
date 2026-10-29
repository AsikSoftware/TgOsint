# -*- coding: utf-8 -*-
"""Анкета до диагностики: состояние телефона — четырьмя кнопками Оценки — и клиент.

Это первый экран сделки, до кабеля: так же начинает и продавец в боте Оценки (имя,
телефон, потом «Выбери статус состояния телефона»). Состояние решает, что будет дальше:

* «Б/у телефон в нормальном состоянии» — телефон читается кабелем, и если проверка найдёт
  замену, неоригинальную батарею или другой стоп, состояние меняется само
  (ocenka.переклассифицировать) — сделка уйдёт на ручную оценку, а не получит автоцену;
* «Телефон был в ремонте», «Есть видимые дефекты» — та же проверка кабелем, сделка уйдёт
  на ручную оценку;
* «Запечатанный (новый)» — кабеля нет: IMEI с коробки → база IMEI (Sickw) → реестр РФС →
  сделка. Поэтому для него здесь же поля IMEI.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from pintel_core.external import ocenka, sickw

from .ui import C, FONT_HEAD, Screen, W, font, kicker, label, point_text
from .ui_deal import QSS_DEAL, _карточка, _кнопка, нормальный_телефон

QSS_START = """
QPushButton#выбор { background: #FFFFFF; color: %(ink)s; border: 2px solid %(border)s; border-radius: 18px;
    font-size: 24px; font-weight: 700; min-height: 104px; padding: 0 26px; text-align: left; }
QPushButton#выбор:checked { background: %(tint)s; border-color: %(action)s; color: %(brand)s; }
QPushButton#выбор:pressed { background: %(ground)s; }
""" % C

ПОДСКАЗКИ = {
    "новый": "Коробку не вскрываем и кабель не нужен: введите IMEI с коробки — модель, объём и цвет "
             "придут из базы IMEI, оба IMEI сверим с реестром РФС. Сделка уйдёт на ручную оценку.",
    "ремонт": "Подключим кабелем и проверим. Сделка уйдёт администратору на ручную оценку.",
    "дефект": "Подключим кабелем и проверим. Сделка уйдёт администратору на ручную оценку.",
    "норма": "Подключим кабелем. Найдётся замена, неоригинальная батарея или другой стоп — состояние "
             "изменится само, и сделка уйдёт на ручную оценку вместо автоцены.",
}


def чистый_imei(текст) -> str:
    """Со сканера или с клавиатуры → 15 цифр; пусто — не IMEI."""
    цифры = "".join(ch for ch in str(текст or "") if ch.isdigit())
    return цифры if len(цифры) == 15 and sickw.luhn_ok(цифры) else ""


class StartScreen(Screen):
    """Состояние и клиент — до того, как телефон коснётся кабеля."""

    далее = Signal(dict)
    отмена = Signal()

    def __init__(self, point=""):
        super().__init__(gray=True)
        self.setStyleSheet(QSS_DEAL + QSS_START)
        self.root.setContentsMargins(56, 40, 56, 36)
        шапка = QHBoxLayout()
        шапка.addWidget(label("Новая оценка", font_=font(FONT_HEAD, 34, W.Bold)), 1)
        self.точка = label(point_text(point), "muted")
        шапка.addWidget(self.точка)
        self.root.addLayout(шапка)
        self.root.addSpacing(18)

        тело = QHBoxLayout()
        тело.setSpacing(22)
        тело.addWidget(self._состояние(), 115)
        тело.addWidget(self._клиент(), 85)
        self.root.addLayout(тело, 1)

        self.ошибка = label("", wrap=True, color=C["badtext"])
        self.root.addSpacing(10)
        self.root.addWidget(self.ошибка)
        низ = QHBoxLayout()
        низ.setSpacing(14)
        self.b_отмена = _кнопка("Отменить", "ghost")
        self.b_отмена.clicked.connect(self.отмена.emit)
        self.b_далее = _кнопка("Далее")
        self.b_далее.clicked.connect(self._далее)
        низ.addWidget(self.b_отмена)
        низ.addStretch(1)
        низ.addWidget(self.b_далее)
        self.root.addSpacing(16)
        self.root.addLayout(низ)
        self.начать()

    # ---------- колонки ----------
    def _состояние(self):
        рамка, внутри = _карточка("СОСТОЯНИЕ ТЕЛЕФОНА — КНОПКИ ОЦЕНКИ")
        сетка = QGridLayout()
        сетка.setHorizontalSpacing(14)
        сетка.setVerticalSpacing(14)
        self.группа = QButtonGroup(self)
        self.группа.setExclusive(True)
        self.кнопки = {}
        for n, (ключ, (надпись, _статус)) in enumerate(ocenka.СОСТОЯНИЯ.items()):
            b = QPushButton(надпись)
            b.setObjectName("выбор")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.toggled.connect(self._проверить)
            self.группа.addButton(b)
            self.кнопки[ключ] = b
            сетка.addWidget(b, n // 2, n % 2)
        внутри.addLayout(сетка)
        self.подсказка = label("", "muted", wrap=True)
        внутри.addSpacing(12)
        внутри.addWidget(self.подсказка)
        внутри.addStretch(1)
        return рамка

    def _клиент(self):
        рамка, внутри = _карточка("КЛИЕНТ")
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

        # IMEI — только для запечатанного: кабеля нет, аппарат узнаём по коробке
        self.imei_блок = QWidget()
        бл = QVBoxLayout(self.imei_блок)
        бл.setContentsMargins(0, 0, 0, 0)
        бл.setSpacing(6)
        бл.addWidget(kicker("IMEI С КОРОБКИ", 13, 2.0))
        self.imei1 = QLineEdit()
        self.imei1.setPlaceholderText("IMEI — 15 цифр")
        self.imei2 = QLineEdit()
        self.imei2.setPlaceholderText("IMEI 2 — если есть на коробке")
        for поле in (self.imei1, self.imei2):
            поле.setMaxLength(20)
            поле.textChanged.connect(self._проверить)
            бл.addWidget(поле)
        бл.addWidget(label("Отсканируйте штрихкод коробки или наберите цифры. Модель, объём и цвет "
                           "возьмём из базы IMEI, оба номера сверим с реестром РФС.", "muted", wrap=True))
        внутри.addSpacing(12)
        внутри.addWidget(self.imei_блок)
        внутри.addStretch(1)
        return рамка

    # ---------- состояния ----------
    def начать(self):
        self.группа.setExclusive(False)
        for b in self.кнопки.values():
            b.setChecked(False)
        self.группа.setExclusive(True)
        for поле in (self.имя, self.телефон, self.imei1, self.imei2):
            поле.clear()
        self.ошибка.setText("")
        self.подсказка.setText("Выберите состояние — как в боте Оценки. Клиента записываем здесь же, "
                               "до того как телефон коснётся кабеля.")
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
        self.подсказка.setText(ПОДСКАЗКИ.get(с) or "Выберите состояние — как в боте Оценки.")
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
