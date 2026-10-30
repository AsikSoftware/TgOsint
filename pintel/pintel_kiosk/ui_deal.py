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
"""
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLineEdit,
                               QPushButton, QSizePolicy, QStackedWidget, QTextEdit, QVBoxLayout,
                               QWidget)

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


def _кнопка(текст, вид="primary"):
    b = QPushButton(текст)
    b.setObjectName(вид)
    b.setCursor(Qt.PointingHandCursor)
    return b


def _плашка(текст, фон, цвет):
    l = label(текст, font_=font(FONT_TEXT, 20, W.Bold))
    l.setStyleSheet(f"background: {фон}; color: {цвет}; border-radius: 16px; padding: 7px 18px;")
    return l


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

    def __init__(self, point=""):
        super().__init__(gray=True)
        self.setStyleSheet(QSS_DEAL)
        self.rep, self.готово, self.отправлено = {}, False, False
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
        тело.addWidget(self._проверка(), 105)
        тело.addWidget(self._сделка(), 100)
        тело.addWidget(self._справа(), 80)
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
        b_пропуск = QPushButton("Сделает сотрудник")
        b_пропуск.setObjectName("small")
        b_пропуск.clicked.connect(self.пропустить_apple.emit)
        ал.addWidget(b_пропуск, 0, Qt.AlignLeft)

        медиа, мл = _карточка("ФОТО И ВИДЕО — ЧЕРЕЗ БОТА")
        self.qr = QrBlock()
        мл.addWidget(self.qr, 0, Qt.AlignHCenter)
        self.код = label("—", font_=font(FONT_NUM, 30, W.Bold))
        self.код.setAlignment(Qt.AlignHCenter)
        мл.addWidget(self.код)
        self.ссылка = label("", "muted", wrap=True)
        self.ссылка.setAlignment(Qt.AlignHCenter)
        мл.addWidget(self.ссылка)
        self.медиа = label("Сканируйте телефоном. Бот проведёт по шагам: фото с *#06#, лицевая, "
                           "задняя, потом видео. Кто прислал — тот и оценщик.",
                           "muted", wrap=True)
        self.медиа.setAlignment(Qt.AlignHCenter)
        мл.addWidget(self.медиа)
        мл.addStretch(1)
        b_код = QPushButton("Другой код")
        b_код.setObjectName("small")
        b_код.clicked.connect(self.новый_код.emit)
        мл.addWidget(b_код, 0, Qt.AlignHCenter)

        готово, гл = _карточка("ОТПРАВЛЕНО")
        гл.addStretch(1)
        self.номер = label("—", font_=font(FONT_NUM, 44, W.Bold))
        self.номер.setAlignment(Qt.AlignHCenter)
        гл.addWidget(self.номер)
        self.итог_текст = label("", "muted", wrap=True)
        self.итог_текст.setAlignment(Qt.AlignHCenter)
        гл.addWidget(self.итог_текст)
        гл.addStretch(1)

        for w in (apple, медиа, готово):
            self.правая.addWidget(w)
        return self.правая

    # ---------- состояния ----------
    def начать(self):
        """Новая сделка: поля пустые, проверка с нуля."""
        self.rep, self.готово, self.отправлено = {}, False, False
        self.имя.clear()
        self.телефон.clear()
        self.комментарий.clear()
        self.коробка.setChecked(False)
        self.шнур.setChecked(False)
        self.sim.setCurrentIndex(0)
        self.аппарат.setText("Подключите телефон кабелем")
        self.ошибка.setText("")
        self.подсказка.setText("Не отключайте кабель. Обычно это занимает около минуты.")
        for r in self.шаги.values():
            r.set("wait", "")
        self.set_состояние("")
        self.режим(False)
        self.стопка.setCurrentIndex(0)
        self.правая.setCurrentIndex(1)
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
            self.правая.setCurrentIndex(1)
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
        self.правая.setCurrentIndex(0 if on else 1)

    def показать_код(self, код, ссылка):
        self.код.setText(код or "—")
        # под QR достаточно короткого адреса: он нужен, только если QR не считался
        self.ссылка.setText(str(ссылка or "").replace("https://", ""))
        self.qr.set(qr_pixmap(ссылка) if ссылка else None, "СКАНИРУЙТЕ", rise=False)

    def _очистить_итоги(self):
        while self.итоги.count():
            w = self.итоги.takeAt(0).widget()
            if w:
                w.deleteLater()
        while self.плашки.count() > 1:
            w = self.плашки.takeAt(0).widget()
            if w:
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
        if not self.отправлено:
            self.правая.setCurrentIndex(1)
        self._проверить()

    def отказ(self, текст):
        """Телефон с заменой: сделку не оформляем, слепок уже сохранён."""
        self.готово = False
        self.ошибка.setText(текст)
        self.b_отправить.setEnabled(False)
        self.b_отмена.setText("Новая оценка")

    def ушло(self, код, текст=""):
        self.отправлено = True
        self.номер.setText(str(код or "—"))
        self.итог_текст.setText(текст or "Оценщик подтверждает сделку в Telegram — там появится её номер.")
        self.правая.setCurrentIndex(2)
        self.b_печать.setEnabled(True)
        self.b_отправить.setEnabled(False)
        self.b_отмена.setText("Новая оценка")

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
                "комментарий": self.комментарий.toPlainText().strip()}

    def _годно(self):
        d = self.данные()
        return bool(self.готово and not self.отправлено and d["имя"] and d["телефон"])

    def _проверить(self):
        d = self.данные()
        плохой = bool(self.телефон.text().strip() and not d["телефон"])
        self.телефон.setProperty("плохо", "да" if плохой else "нет")
        self.телефон.style().unpolish(self.телефон)
        self.телефон.style().polish(self.телефон)
        self.b_отправить.setEnabled(self._годно())
        return self._годно()

    def _отправить(self):
        d = self.данные()
        нет = [имя for имя, есть in (("имя клиента", d["имя"]), ("телефон клиента", d["телефон"]),
                                     ("результат проверки", self.готово)) if not есть]
        if нет:
            self.ошибка.setText("Не хватает: " + ", ".join(нет))
            return
        self.ошибка.setText("")
        self.отправить.emit(d)
