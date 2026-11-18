# -*- coding: utf-8 -*-
"""Скрытый режим обновления МойСклада — экран.

Включается из меню администратора (Ctrl+Shift+A). Клиента в этом режиме нет: сотрудник берёт
телефон со склада, подключает кабель, касса читает его как обычно и находит его товар в
МойСкладе по IMEI. На экране — что в карточке товара было и что станет; запись идёт только
после кнопки «Обновить в МойСкладе». Потом следующий телефон.

Слева — те же шаги проверки по кабелю, что в сделке, под ними тест на телефоне и проверки
руками (18.11.2026, просьба владельца: «добавь в обновление данных тесты и ручные как и в
диагностике»). Справа — товар: это главное на экране. Цены, фото и видео здесь нет: ни
клиента, ни сделки в этом режиме не бывает.

Тест открывают НА ТОМ ЖЕ телефоне, который проверяют: код сканируют им, а не телефоном
сотрудника. Проверки руками показываются прямо на кассе — здесь это можно, клиент на экран
не смотрит.

Экран ничего не знает ни про сеть, ни про МойСклад: ему говорят состояние, он его рисует.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from pintel_core import phonetest
from pintel_core.external import ocenka_media

from .ui import (C, FONT_HEAD, FONT_NUM, FONT_TEXT, STEPS, QrBlock, Screen, StepRow, W, font,
                 kicker, label, logo_label, point_text, qr_pixmap, Успех)
from .ui_deal import QSS_DEAL, ВИД_ОТВЕТА, ПунктРяд, _карточка, _кнопка, _фокус

ЗАГОЛОВОК = "Обновление товаров МойСклада"
КНОПКА_ЗАПИСАТЬ = "Обновить в МойСкладе"
КНОПКА_ДАЛЬШЕ = "Следующий телефон"
ПОДКЛЮЧИТЕ = "Подключите телефон со склада"
# В сделке код сканирует клиент телефоном, который сдаёт. Здесь клиента нет, и сканировать
# должен сам проверяемый телефон — иначе тест пройдёт не тот аппарат.
ПОДСКАЗКА_ТЕСТА_СКЛАД = "Отсканируйте код ТЕМ телефоном, который проверяете."
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
    новый_тест = Signal()               # другой одноразовый код для теста на телефоне

    def __init__(self, point=""):
        super().__init__(gray=True)
        self.setStyleSheet(QSS_DEAL)
        self.root.setContentsMargins(48, 26, 48, 28)
        self.root.setSpacing(18)
        self.состояние = "ждём"
        # отметки этого телефона: тест на нём самом и проверки руками. Пустые — значит в
        # этот проход их не снимали, и бот такие поля карточки не тронет (замена поблочная).
        self.тест, self.ручная = {}, {}

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


        # --- середина: проверки этого телефона (18.11.2026)
        # Своя колонка, а не продолжение левой карточки: в левой не хватает высоты —
        # шесть шагов чтения, QR и восемь плиток в 1080 по вертикали не укладываются,
        # и QR наезжал на подписи (поймано тестом вёрстки).
        проверки_карточка, пров = _карточка("ПРОВЕРКИ ЭТОГО ТЕЛЕФОНА")
        проверки_карточка.setFixedWidth(430)
        # --- тест на самом телефоне: QR слева, результат справа
        self.тест_подсказка = label(ПОДСКАЗКА_ТЕСТА_СКЛАД, "muted", wrap=True)
        пров.addWidget(self.тест_подсказка)
        пара = QHBoxLayout()
        пара.setSpacing(18)
        слева_qr = QVBoxLayout()
        слева_qr.setSpacing(6)
        self.qr_тест = QrBlock(150)
        слева_qr.addWidget(self.qr_тест, 0, Qt.AlignHCenter)
        self.тест_ссылка = label("", wrap=True, font_=font(FONT_TEXT, 13), color=C["muted"])
        self.тест_ссылка.setAlignment(Qt.AlignHCenter)
        слева_qr.addWidget(self.тест_ссылка)
        b_код = _кнопка("Другой код", "small")
        b_код.clicked.connect(self.новый_тест.emit)
        слева_qr.addWidget(b_код, 0, Qt.AlignHCenter)
        слева_qr.addStretch(1)
        пара.addLayout(слева_qr, 4)
        self.тест_список = QVBoxLayout()
        self.тест_список.setSpacing(3)
        пара.addLayout(self.тест_список, 6)
        пров.addLayout(пара)

        # --- проверки руками: те же восемь пунктов, что в сделке
        пров.addSpacing(8)
        пров.addWidget(kicker("ПРОВЕРЬТЕ РУКАМИ", 13, 2.0, C["brand"]))
        пров.addWidget(label("Нажмите по плитке — «работает». Ещё раз — «не работает». "
                             "Отметить нужно все восемь: запись заменяет поля целиком.",
                             "muted", wrap=True))
        сетка = QGridLayout()
        сетка.setContentsMargins(0, 4, 0, 0)
        сетка.setHorizontalSpacing(10)
        сетка.setVerticalSpacing(6)
        self.пункты_ряды = {}
        for n, (ключ, имя, подробно) in enumerate(ocenka_media.ПУНКТЫ):
            r = ПунктРяд(ключ, имя, подробно)
            r.нажали.connect(self.отметить)
            self.пункты_ряды[ключ] = r
            сетка.addWidget(r, n // 2, n % 2)
        сетка.setColumnStretch(0, 1)
        сетка.setColumnStretch(1, 1)
        пров.addLayout(сетка)
        self.ручная_итог = label("", wrap=True, font_=font(FONT_TEXT, 15, W.Bold))
        пров.addWidget(self.ручная_итог)
        пров.addStretch(1)
        тело.addWidget(проверки_карточка)

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
        # отметки этого телефона: тест на нём самом и проверки руками. Пустые — значит в
        # этот проход их не снимали, и бот такие поля карточки не тронет (замена поблочная).
        self.тест, self.ручная = {}, {}
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
            чего = self.чего_не_хватает()
            self.пояснение.setText(
                "Проверьте и подтвердите — после кнопки изменения уйдут в МойСклад."
                if not чего else
                "Сначала закончите проверки, иначе в карточку уедет пустота вместо данных. "
                "Осталось: " + "; ".join(чего))
            self._таблица(изменения)
            self.b_записать.setEnabled(not чего)
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

    # ---------- тест на телефоне и проверки руками (18.11.2026) ----------
    # Телефон со склада проверяют тем же порядком, что в сделке, но проверки здесь
    # необязательные: сотрудник может прогнать аппарат одним кабелем. Что не снимали — то
    # в карточке и не меняется (бот заменяет поля блоками), поэтому экран ничего не требует.

    def show_prompt(self, on):
        """Телефон просит открыть «Детали и обслуживание» — без этого журнал Apple не придёт.

        В сделке под это отведена отдельная страница правой колонки; здесь экран один, и
        просьба идёт строкой под шагами чтения, рядом с кнопкой «Не ждать Apple». Пять
        деталей — плата, корпус, заднее стекло, верхний модуль и LiDAR — известны ТОЛЬКО из
        этого журнала, и при замене они очистятся, если раздел не открыть."""
        self.подсказка.setText(
            "Откройте на телефоне: Настройки → Основные → Об этом устройстве → "
            "«Детали и обслуживание». Без этого Apple не подтвердит детали."
            if on else "")
        self.b_apple.setVisible(bool(on))

    def показать_тест(self, ссылка, почему=""):
        """QR на страницу теста. Пустая ссылка — сети нет, и это говорится словами."""
        self.тест_ссылка.setText(str(ссылка or "").replace("http://", ""))
        self.qr_тест.set(qr_pixmap(ссылка) if ссылка else None, "СКАНИРУЙТЕ", rise=False)
        self.тест_подсказка.setText(
            почему or (ПОДСКАЗКА_ТЕСТА_СКЛАД if ссылка else
                       "Касса не в сети — тест на телефоне не открыть, а он обязателен. "
                       "Проверьте интернет на кассе и нажмите «Другой код»."))
        self._нарисовать_тест()

    def set_тест(self, res):
        """Результат теста пришёл с телефона, который проверяют."""
        self.тест = dict(res or {})
        self._нарисовать_тест()
        self._обновить_кнопку()

    def _обновить_кнопку(self):
        """Кнопка записи живёт, только когда товар найден и проверки закончены."""
        if self.состояние != "найден":
            return
        чего = self.чего_не_хватает()
        self.b_записать.setEnabled(not чего)
        if чего:
            self.пояснение.setText("Сначала закончите проверки, иначе в карточку уедет "
                                   "пустота вместо данных. Осталось: " + "; ".join(чего))

    def _нарисовать_тест(self):
        while self.тест_список.count():
            w = self.тест_список.takeAt(0).widget()
            if w:
                # setParent(None) обязателен: deleteLater откладывает удаление до следующего
                # круга цикла событий, и до тех пор старые строки лежат поверх новых
                w.setParent(None)
                w.deleteLater()
        if not self.тест:
            self.тест_список.addWidget(label("Тест обязателен: без него поля теста уедут в "
                                             "карточку пустыми.", "muted", wrap=True))
            return
        for имя, ответ in phonetest.коротко(self.тест):
            значок, цвет, подпись = ВИД_ОТВЕТА.get(ответ, ВИД_ОТВЕТА[None])
            self.тест_список.addWidget(label(f"{значок}  {имя} — {подпись}", color=цвет,
                                             font_=font(FONT_TEXT, 16, W.Medium)))

    def отметить(self, ключ):
        """Нажали по плитке: ⬜ → ✅ → ❌ → ⬜. В этом режиме ничего не требуется и не блокируется."""
        if self.состояние in ("пишем", "записано"):
            return                                    # запись уже ушла — отметки поздно менять
        self.ручная = ocenka_media.переключить(self.ручная, ключ)
        for к, ряд in self.пункты_ряды.items():
            ряд.set(self.ручная.get(к))
        отмечено = sum(1 for к in ocenka_media.КЛЮЧИ if self.ручная.get(к) is not None)
        всего = len(ocenka_media.КЛЮЧИ)
        self.ручная_итог.setText(f"Отмечено {отмечено} из {всего}"
                                 + ("" if отмечено == всего else " — нужны все"))
        self._обновить_кнопку()

    def чего_не_хватает(self) -> list:
        """Что ещё не сделано для записи. Пусто — можно обновлять.

        Проверки в этом режиме ОБЯЗАТЕЛЬНЫЕ (владелец, 18.11.2026): «актуализация на то и
        актуализация, чтобы освежить данные». Запись заменяет поля целиком, и если тест с
        анкетой пропустить, в карточку уедут пустые поля вместо прежних — то есть мы не
        освежим данные, а сотрём их. Поэтому кнопка записи ждёт обоих."""
        чего = []
        if not phonetest.готов(self.тест):
            не_прошли = [и for и, о in phonetest.коротко(self.тест) if о is None]
            чего.append("тест на телефоне" + (f" ({len(не_прошли)} п. не пройдено)"
                                              if self.тест else ""))
        не_отмечено = [и for к, и, _ in ocenka_media.ПУНКТЫ if self.ручная.get(к) is None]
        if не_отмечено:
            чего.append("проверки руками: " + ", ".join(не_отмечено))
        return чего

    def проверки(self):
        """Что снимали с этого телефона. → (тест | None, ручная | None).

        `None` значит «в этот проход не снимали»: бот такие поля карточки не тронет. Пустой
        словарь и `None` здесь одно и то же нарочно — отличить «проверил и всё плохо» от
        «не проверял» по пустоте нельзя, а врать в карточку хуже, чем не писать."""
        return (dict(self.тест) or None), (dict(self.ручная) or None)

    def сбросить_проверки(self):
        """Следующий телефон — отметки прошлого не переносим."""
        self.тест, self.ручная = {}, {}
        for ряд in self.пункты_ряды.values():
            ряд.set(None)
        self.ручная_итог.setText("")
        self._нарисовать_тест()
