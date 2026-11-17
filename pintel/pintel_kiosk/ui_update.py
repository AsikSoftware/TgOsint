# -*- coding: utf-8 -*-
"""Скрытый режим обновления МойСклада — экран.

Включается из меню администратора (Ctrl+Shift+A). Клиента в этом режиме нет: сотрудник берёт
телефон со склада, подключает кабель, касса читает его как обычно и находит его товар в
МойСкладе по IMEI. На экране — что в карточке товара было и что станет; запись идёт только
после кнопки «Обновить в МойСкладе». Потом следующий телефон.

Слева — те же шаги проверки по кабелю, что в сделке. Справа — товар: это главное на экране.
Теста на телефоне, проверок руками, цены, фото и видео здесь нет — так решил владелец
(17.11.2026): только кабель.

Экран ничего не знает ни про сеть, ни про МойСклад: ему говорят состояние, он его рисует.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from .ui import (C, FONT_HEAD, FONT_NUM, FONT_TEXT, STEPS, Screen, StepRow, W, font, kicker, label,
                 logo_label, point_text, Успех)
from .ui_deal import QSS_DEAL, _карточка, _кнопка, _фокус

ЗАГОЛОВОК = "Обновление товаров МойСклада"
КНОПКА_ЗАПИСАТЬ = "Обновить в МойСкладе"
КНОПКА_ДАЛЬШЕ = "Следующий телефон"
ПОДКЛЮЧИТЕ = "Подключите телефон со склада"
ИЗМЕНЕНИЙ_НА_ЭКРАНЕ = 11           # больше строк в карточку не помещается — остальное числом
# Последний шаг проверки в сделке называется «Отправка на кассу»; здесь отправляется оценка
# на сервер — оттуда же берётся ссылка для поля «Заключение».
ИМЕНА_ШАГОВ = {"upload": "Сертификат диагностики"}


class UpdateScreen(Screen):
    """Обновление карточки товара: шаги кабеля слева, товар и «было → станет» справа."""

    записать = Signal()             # сотрудник подтвердил изменения
    дальше = Signal()               # этот телефон закончен — ждём следующий
    выйти = Signal()                # выключить режим
    пропустить_apple = Signal()     # не ждать раздел «Об этом устройстве» на телефоне
    починить_связь = Signal()

    def __init__(self, point=""):
        super().__init__(gray=True)
        self.setStyleSheet(QSS_DEAL)
        self.root.setContentsMargins(48, 26, 48, 28)
        self.root.setSpacing(18)
        self.состояние = "ждём"

        шапка = QHBoxLayout()
        шапка.setSpacing(16)
        шапка.addWidget(logo_label(42))
        названия = QVBoxLayout()
        названия.setSpacing(0)
        названия.addWidget(label(ЗАГОЛОВОК, font_=font(FONT_HEAD, 28, W.Bold)))
        self.подзаголовок = label("Скрытый режим · сделки и клиента здесь нет",
                                  font_=font(FONT_TEXT, 16, W.Medium), color=C["muted"])
        названия.addWidget(self.подзаголовок)
        шапка.addLayout(названия, 1)
        self.кто = label("", font_=font(FONT_TEXT, 18, W.DemiBold), color=C["brand"])
        шапка.addWidget(self.кто)
        self.точка = label(point_text(point), font_=font(FONT_TEXT, 17, W.Medium), color=C["muted"])
        шапка.addWidget(self.точка)
        self.root.addLayout(шапка)

        тело = QHBoxLayout()
        тело.setSpacing(22)

        # --- слева: телефон и шаги чтения
        левая, лв = _карточка("ТЕЛЕФОН")
        левая.setFixedWidth(680)      # шире, чем в сделке: подпись шага Apple длинная и обрезалась
        self.аппарат = label(ПОДКЛЮЧИТЕ, wrap=True, font_=font(FONT_HEAD, 26, W.Bold))
        лв.addWidget(self.аппарат)
        self.аппарат_подробно = label("", wrap=True, font_=font(FONT_TEXT, 16, W.Medium), color=C["muted"])
        лв.addWidget(self.аппарат_подробно)
        лв.addSpacing(6)
        self.шаги = {}
        for ключ, имя in STEPS:
            ряд = StepRow(ИМЕНА_ШАГОВ.get(ключ, имя))
            self.шаги[ключ] = ряд
            лв.addWidget(ряд)
        self.подсказка = label("", wrap=True, font_=font(FONT_TEXT, 16, W.Medium), color=C["muted"])
        лв.addWidget(self.подсказка)
        ряд_кнопок = QHBoxLayout()
        self.b_apple = _кнопка("Не ждать Apple", "small")
        self.b_apple.clicked.connect(self.пропустить_apple.emit)
        self.b_apple.hide()
        self.b_связь = _кнопка("Починить связь", "small")
        self.b_связь.clicked.connect(self.починить_связь.emit)
        self.b_связь.hide()
        ряд_кнопок.addWidget(self.b_apple)
        ряд_кнопок.addWidget(self.b_связь)
        ряд_кнопок.addStretch(1)
        лв.addLayout(ряд_кнопок)
        лв.addStretch(1)
        тело.addWidget(левая)

        # --- справа: товар в МойСкладе
        правая, пв = _фокус("Товар в МойСкладе")
        self.товар = label("", wrap=True, font_=font(FONT_HEAD, 24, W.Bold))
        self.товар_подробно = label("", wrap=True, font_=font(FONT_TEXT, 16, W.Medium), color=C["muted"])
        пв.addWidget(self.товар)
        пв.addWidget(self.товар_подробно)
        self.успех = Успех(96)
        self.успех.hide()
        пв.addWidget(self.успех, 0, Qt.AlignLeft)
        self.главное = label(ПОДКЛЮЧИТЕ, wrap=True, font_=font(FONT_HEAD, 34, W.Bold), color=C["ghost"])
        пв.addWidget(self.главное)
        self.пояснение = label("", wrap=True, font_=font(FONT_TEXT, 19, W.Medium), color=C["body"])
        пв.addWidget(self.пояснение)
        # таблица «поле · было · станет»
        self.таблица_рамка = QWidget()
        self.таблица = QGridLayout(self.таблица_рамка)
        self.таблица.setContentsMargins(0, 6, 0, 0)
        self.таблица.setHorizontalSpacing(22)
        self.таблица.setVerticalSpacing(7)
        self.таблица.setColumnStretch(0, 3)
        self.таблица.setColumnStretch(1, 4)
        self.таблица.setColumnStretch(2, 5)
        self.таблица_рамка.hide()
        пв.addWidget(self.таблица_рамка)
        self.заметки = label("", wrap=True, font_=font(FONT_TEXT, 16, W.Medium), color=C["warntext"])
        self.заметки.hide()
        пв.addWidget(self.заметки)
        пв.addStretch(1)
        тело.addWidget(правая, 1)
        self.root.addLayout(тело, 1)

        низ = QHBoxLayout()
        низ.setSpacing(16)
        self.b_выйти = _кнопка("Выйти из режима", "ghost")
        self.b_выйти.clicked.connect(self.выйти.emit)
        низ.addWidget(self.b_выйти)
        низ.addStretch(1)
        self.b_дальше = _кнопка(КНОПКА_ДАЛЬШЕ, "ghost")
        self.b_дальше.clicked.connect(self.дальше.emit)
        self.b_дальше.hide()
        низ.addWidget(self.b_дальше)
        self.b_записать = _кнопка(КНОПКА_ЗАПИСАТЬ)
        self.b_записать.clicked.connect(self.записать.emit)
        self.b_записать.setEnabled(False)
        низ.addWidget(self.b_записать)
        self.root.addLayout(низ)
        self.ждать()

    # ---------- кто и где ----------
    def set_point(self, point):
        self.точка.setText(point_text(point))

    def set_сотрудник(self, имя):
        имя = str(имя or "").strip()
        self.кто.setText(f"Обновляет: {имя}" if имя else "")

    # ---------- левая колонка: телефон ----------
    def set_step(self, key, state, text):
        if key in self.шаги:
            self.шаги[key].set(state, text)
        if key == "apple":
            self.b_apple.setVisible(state == "run" and self.состояние == "читаем")

    def set_trouble(self, text):
        self.подсказка.setText(text or "")

    def показать_починку(self, видно, занято=False):
        self.b_связь.setVisible(bool(видно))
        self.b_связь.setEnabled(not занято)

    def set_телефон(self, rep):
        """Телефон прочитан: что это за аппарат — одной строкой над шагами."""
        пас, пам, бат = (rep or {}).get("паспорт") or {}, (rep or {}).get("память") or {}, (rep or {}).get("батарея") or {}
        self.аппарат.setText(" · ".join(str(x) for x in (
            пас.get("модель"), f"{пам.get('объём_гб')} ГБ" if пам.get("объём_гб") else None) if x) or "Телефон")
        хвост = [f"iOS {пас.get('ios')}" if пас.get("ios") else None,
                 f"IMEI {пас.get('imei')}" if пас.get("imei") else None,
                 f"АКБ {бат.get('здоровье_%')}%" if бат.get("здоровье_%") is not None else None]
        self.аппарат_подробно.setText(" · ".join(x for x in хвост if x))

    # ---------- правая колонка: состояния ----------
    def _сбросить_право(self):
        while self.таблица.count():
            w = self.таблица.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for w in (self.таблица_рамка, self.заметки, self.успех, self.b_дальше):
            w.hide()
        self.товар.setText("")
        self.товар_подробно.setText("")
        self.главное.setText("")
        self.главное.show()
        self.пояснение.setText("")
        self.b_записать.setEnabled(False)
        self.b_записать.setText(КНОПКА_ЗАПИСАТЬ)
        self.b_записать.show()

    def _сказать(self, главное, пояснение="", цвет=None):
        self.главное.setText(главное)
        self.главное.setStyleSheet(f"color: {цвет or C['ink']}")
        self.главное.setVisible(bool(главное))
        self.пояснение.setText(пояснение)

    def ждать(self, почему=""):
        """Телефона на кабеле нет: ждём следующий."""
        self.состояние = "ждём"
        self._сбросить_право()
        for ключ in self.шаги:
            self.шаги[ключ].set("wait", "")
        self.аппарат.setText(ПОДКЛЮЧИТЕ)
        self.аппарат_подробно.setText("")
        self.b_apple.hide()
        self.set_trouble(почему)
        self._сказать(ПОДКЛЮЧИТЕ, "Касса прочитает его, найдёт товар по IMEI и покажет, что изменится "
                                  "в карточке. Без вашего подтверждения ничего не записывается.", C["ghost"])

    def читаем(self):
        self.состояние = "читаем"
        self._сбросить_право()
        self.аппарат.setText("Читаем телефон…")
        self.set_trouble("Не отключайте кабель. Обычно это занимает около минуты.")
        self._сказать("Читаем телефон…", "Товар поищем, как только телефон прочитается.", C["ghost"])

    def ищем(self):
        self.состояние = "ищем"
        self._сбросить_право()
        self.b_apple.hide()
        self.set_trouble("")
        self._сказать("Ищем товар по IMEI…", "Спрашиваем МойСклад через бота Оценки.", C["ghost"])

    def беда(self, текст, можно_дальше=True):
        """Товар не нашёлся, бот не ответил, телефон не прочитался — словами."""
        self.состояние = "беда"
        self._сбросить_право()
        self.b_apple.hide()
        self._сказать("Не получилось", str(текст or "причина неизвестна"), C["warntext"])
        self.b_записать.hide()
        self.b_дальше.setVisible(bool(можно_дальше))

    def показать_товар(self, мс: dict):
        """Товар найден: что в карточке было и что станет. Запись — только по кнопке."""
        self.состояние = "найден"
        self._сбросить_право()
        self._товар(мс)
        изменения = list(мс.get("изменения") or [])
        if not изменения:
            self._сказать("Менять нечего", "Карточка товара уже совпадает с телефоном.", C["ok"])
            self.b_записать.hide()
            self.b_дальше.show()
        else:
            self.главное.hide()
            self.пояснение.setText("Проверьте и подтвердите — после кнопки изменения уйдут в МойСклад.")
            self._таблица(изменения)
            self.b_записать.setEnabled(True)
        self._заметки(мс)

    def пишем(self):
        self.состояние = "пишем"
        self.b_записать.setEnabled(False)
        self.b_записать.setText("Записываем…")

    def записано(self, мс: dict):
        """Карточка обновлена. Дальше — следующий телефон."""
        self.состояние = "записано"
        self._сбросить_право()
        self._товар(мс)
        self.успех.show()
        сколько = len(мс.get("изменения") or [])
        self._сказать("Товар обновлён" if сколько else "Менять было нечего",
                      "Отключите телефон и подключите следующий.", C["ok"])
        self._таблица(list(мс.get("изменения") or []))
        self._заметки(мс)
        self.b_записать.hide()
        self.b_дальше.show()

    # ---------- части правой колонки ----------
    def _товар(self, мс):
        товар = мс.get("товар") or {}
        self.товар.setText(" · ".join(x for x in (
            f"Код {товар.get('код')}" if товар.get("код") else "", товар.get("название") or "") if x))
        self.товар_подробно.setText(str(товар.get("папка") or ""))

    def _таблица(self, изменения):
        if not изменения:
            return
        for колонка, имя in enumerate(("ПОЛЕ", "БЫЛО", "СТАНЕТ")):
            self.таблица.addWidget(kicker(имя, 13, 2.0), 0, колонка)
        for ряд, и in enumerate(изменения[:ИЗМЕНЕНИЙ_НА_ЭКРАНЕ], 1):
            self.таблица.addWidget(label(str(и.get("поле") or ""), font_=font(FONT_TEXT, 19, W.DemiBold)), ряд, 0)
            self.таблица.addWidget(label(str(и.get("было") or "—"), wrap=True, font_=font(FONT_TEXT, 19),
                                         color=C["muted"]), ряд, 1)
            self.таблица.addWidget(label(str(и.get("станет") or ""), wrap=True,
                                         font_=font(FONT_NUM, 19, W.Bold), color=C["ok"]), ряд, 2)
        лишние = len(изменения) - ИЗМЕНЕНИЙ_НА_ЭКРАНЕ
        if лишние > 0:
            self.таблица.addWidget(label(f"…и ещё {лишние}", font_=font(FONT_TEXT, 17), color=C["muted"]),
                                   ИЗМЕНЕНИЙ_НА_ЭКРАНЕ + 1, 0, 1, 3)
        self.таблица_рамка.show()

    def _заметки(self, мс):
        заметки = [str(з) for з in (мс.get("заметки") or []) if str(з or "").strip()]
        self.заметки.setText("\n".join(заметки[:4]))
        self.заметки.setVisible(bool(заметки))
