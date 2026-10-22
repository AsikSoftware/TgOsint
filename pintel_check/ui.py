# -*- coding: utf-8 -*-
"""Настольный интерфейс Pintel Проверки. Qt (PySide6), без веба и серверов:
кнопки зовут функции core/* напрямую, долгие операции — в рабочих потоках,
чтобы окно не замерзало.

Палитра и формы — те же, что в Оценке Pintel.kz: светлый фон, белые карточки
с рамкой, тёмно-синие кнопки.
"""
import json, os, sys

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from core import apple, device, price, setup, sickw, store, verdict
from core.paths import bundled

# ─────────────────────────── внешний вид ───────────────────────────

QSS = """
* { font-family: 'Segoe UI', 'Manrope', sans-serif; font-size: 14px; }
QMainWindow, QScrollArea, #page { background: #F6F9FC; }
#header { background: #FFFFFF; border-bottom: 1px solid #DCE6F0; }
#title { font-size: 17px; font-weight: 800; color: #122A44; }
QPushButton[nav="true"] {
  background: #FFFFFF; color: #5B7392; border: 1.5px solid #DCE6F0;
  border-radius: 999px; padding: 7px 16px; font-weight: 700;
}
QPushButton[nav="true"]:checked { background: #1A549D; color: white; border-color: #1A549D; }
QPushButton[nav="true"]:hover:!checked { border-color: #1A549D; color: #1A549D; }
#card {
  background: #FFFFFF; border: 1.5px solid #DCE6F0; border-radius: 16px;
}
QLabel[cardtitle="true"] {
  color: #5B7392; font-size: 12px; font-weight: 800; letter-spacing: 1px;
}
QLabel[k="true"]  { color: #5B7392; font-weight: 600; }
QLabel[v="true"]  { color: #122A44; font-weight: 700; }
QLabel[v="ok"]    { color: #0F7F70; font-weight: 700; }
QLabel[v="warn"]  { color: #A8671A; font-weight: 700; }
QLabel[v="bad"]   { color: #C0352B; font-weight: 700; }
QLabel[muted="true"] { color: #5B7392; }
QLabel[h="true"]  { font-size: 22px; font-weight: 800; }
QLabel[price="true"] { font-size: 30px; font-weight: 800; color: #0F7F70; }
QLabel[box="ok"]   { background: #E7F5F2; border: 1.5px solid #9FD5CB; color: #0B5F54;
                     border-radius: 14px; padding: 11px 13px; font-weight: 600; }
QLabel[box="warn"] { background: #FDF3E3; border: 1.5px solid #E8C68C; color: #7A4A12;
                     border-radius: 14px; padding: 11px 13px; font-weight: 600; }
QLabel[box="bad"]  { background: #FBECEA; border: 1.5px solid #E8A9A3; color: #8E2219;
                     border-radius: 14px; padding: 11px 13px; font-weight: 600; }
QLabel[box="info"] { background: #E8F4FB; border: 1.5px solid #B8DEF2; color: #0F6B96;
                     border-radius: 14px; padding: 11px 13px; font-weight: 600; }
QPushButton {
  background: #1A549D; color: white; border: none; border-radius: 14px;
  padding: 13px 20px; font-weight: 800; font-size: 14px;
}
QPushButton:hover:enabled { background: #123C74; }
QPushButton:disabled { background: #A9BDD6; }
QPushButton[sec="true"] {
  background: #FFFFFF; color: #122A44; border: 1.5px solid #DCE6F0;
}
QPushButton[sec="true"]:hover:enabled { background: #F6F9FC; border-color: #1A549D; }
QLineEdit, QTextEdit, QComboBox {
  background: white; border: 1.5px solid #DCE6F0; border-radius: 12px;
  padding: 10px 12px; color: #122A44; font-weight: 600;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border-color: #1A549D; }
QCheckBox { font-weight: 600; color: #122A44; padding: 9px 10px;
            border: 1.5px solid #DCE6F0; border-radius: 12px; background: white; }
QCheckBox:checked { border-color: #1A549D; background: #E8F4FB; }
QCheckBox::indicator { width: 17px; height: 17px; }
"""


def verdict_tone(v):
    """Цвет вердикта. Отсутствие данных НЕ красим в плохое:
    «не прочиталось» и «заменено» — разные вещи."""
    import re
    v = str(v or "")
    if re.search(r"ОРИГИНАЛ|ИСПРАВЕН|ИДЕАЛ|ХОРОШИЙ", v):
        return "ok"
    if re.search(r"ЗАМЕН|НЕОРИГ|СБОИ|ПРОБЛЕМ", v):
        return "bad"
    if re.search(r"ВОПРОС|НЕПОЛНАЯ|РЕМОНТ", v):
        return "warn"
    return "true"


def money(n, cur="₸"):
    if n is None:
        return "—"
    return f"{n:,}".replace(",", " ") + " " + (cur or "₸")


class Worker(QThread):
    """Долгая операция вне главного потока: окно не замерзает."""
    done = Signal(object)
    fail = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as e:
            self.fail.emit(f"{type(e).__name__}: {e}")


# ─────────────────────────── кирпичики ───────────────────────────

def vclear(layout):
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w:
            w.deleteLater()
        elif it.layout():
            vclear(it.layout())


def card(title=None):
    f = QFrame(objectName="card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(8)
    if title:
        t = QLabel(title.upper())
        t.setProperty("cardtitle", True)
        lay.addWidget(t)
    return f, lay


def row(k, v, tone="true"):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 3, 0, 3)
    kl = QLabel(str(k)); kl.setProperty("k", True)
    vl = QLabel(str(v)); vl.setProperty("v", tone)
    vl.setWordWrap(True)
    vl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    vl.setTextInteractionFlags(Qt.TextSelectableByMouse)   # серийники копируют
    h.addWidget(kl)
    h.addStretch(1)
    h.addWidget(vl, 2)
    return w


def box(text, kind="info"):
    l = QLabel(str(text))
    l.setProperty("box", kind)
    l.setWordWrap(True)
    l.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return l


def hint(text):
    l = QLabel(str(text))
    l.setProperty("muted", True)
    l.setWordWrap(True)
    return l


def page_scroll():
    """Страница = прокручиваемая колонка карточек."""
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setFrameShape(QFrame.NoFrame)
    inner = QWidget(objectName="page")
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(22, 18, 22, 30)
    lay.setSpacing(12)
    lay.addStretch(1)          # прижимаем карточки кверху
    sc.setWidget(inner)
    return sc, lay


def add_card(lay, frame):
    lay.insertWidget(lay.count() - 1, frame)


MANUAL = [
    ("экран_пятна",    "Экран: пятна, засветы, выгорание"),
    ("экран_битые",    "Экран: битые пиксели"),
    ("тач_мертвые",    "Тачскрин: мёртвые зоны"),
    ("корпус",         "Корпус: вмятины, сколы, глубокие царапины"),
    ("стекло_зад",     "Заднее стекло: трещины"),
    ("камеры_рабочие", "Камеры дают картинку (основная, широкая, фронтальная)"),
    ("динамик",        "Динамик и микрофон работают"),
    ("вибро",          "Вибрация работает"),
    ("кнопки",         "Кнопки и переключатель звука работают"),
    ("зарядка",        "Заряжается и держит кабель"),
    ("faceid_работ",   "Face ID разблокирует"),
    ("влага",          "Признаки влаги или вскрытия на вид"),
]


# ─────────────────────────── главное окно ───────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pintel Проверка")
        self.resize(1180, 840)
        self.setMinimumSize(940, 640)
        ico = bundled("web", "icon.ico")
        if os.path.exists(ico):
            self.setWindowIcon(QIcon(ico))

        # Состояние приёмки
        self.cid = None
        self.res = None          # вердикты этапа 1
        self.est = None          # оценка
        self.apple_items = None
        self.sickw_data = None
        self._workers = []       # живые потоки, чтобы их не съел сборщик

        root = QWidget()
        rv = QVBoxLayout(root)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        self.setCentralWidget(root)

        # — шапка —
        head = QWidget(objectName="header")
        hh = QHBoxLayout(head)
        hh.setContentsMargins(18, 10, 18, 10)
        logo = QLabel()
        lp = bundled("web", "logo.png")
        if os.path.exists(lp):
            logo.setPixmap(QPixmap(lp).scaledToHeight(26, Qt.SmoothTransformation))
        hh.addWidget(logo)
        hh.addWidget(QLabel("Проверка", objectName="title"))
        hh.addStretch(1)
        self.navgrp = QButtonGroup(self)
        self.navbtns = []
        for i, name in enumerate(["1 · Кабель и оценка", "2 · Ручные проверки",
                                  "3 · Финал", "⚙ Настройки"]):
            b = QPushButton(name)
            b.setProperty("nav", True)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.navgrp.addButton(b, i)
            self.navbtns.append(b)
            hh.addWidget(b)
        self.navgrp.idClicked.connect(self.show_page)
        rv.addWidget(head)

        # — страницы —
        self.stack = QStackedWidget()
        rv.addWidget(self.stack, 1)

        self.p1_scroll, self.p1 = page_scroll()
        self.p2_scroll, self.p2 = page_scroll()
        self.p3_scroll, self.p3 = page_scroll()
        self.p4_scroll, self.p4 = page_scroll()
        for s in (self.p1_scroll, self.p2_scroll, self.p3_scroll, self.p4_scroll):
            self.stack.addWidget(s)

        self.build_stage1_start()
        self.build_settings()
        self.show_page(0)

    # ---------- служебное ----------

    def show_page(self, i):
        self.stack.setCurrentIndex(i)
        self.navbtns[i].setChecked(True)

    def work(self, fn, on_done, on_fail):
        w = Worker(fn, self)
        self._workers.append(w)
        w.done.connect(on_done)
        w.fail.connect(on_fail)
        w.finished.connect(lambda: self._workers.remove(w))
        w.start()

    # ---------- этап 1: старт ----------

    def build_stage1_start(self):
        vclear_target = self.p1
        vclear(vclear_target)
        vclear_target.addStretch(1)

        f, lay = card("Этап 1 — подключение по кабелю")
        try:
            device.udid()
            connected, why = True, ""
        except Exception as e:
            connected, why = False, str(e)
        lay.addWidget(box("Телефон на связи. Можно начинать.", "ok") if connected
                      else box(why, "warn"))
        lay.addWidget(hint("Снимается паспорт аппарата, износ батареи, вердикты по "
                           "деталям, юридический статус. Телефон не отключай до конца проверки."))
        btns = QHBoxLayout()
        go = QPushButton("Снять данные")
        go.setEnabled(connected)
        go.clicked.connect(self.start_stage1)
        refresh = QPushButton("Проверить подключение")
        refresh.setProperty("sec", True)
        refresh.clicked.connect(self.build_stage1_start)
        st = QPushButton("Настройка компьютера")
        st.setProperty("sec", True)
        st.clicked.connect(lambda: (self.show_page(3), self.check_drivers()))
        for b in (go, refresh, st):
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)
        add_card(self.p1, f)

    def start_stage1(self):
        vclear(self.p1)
        self.p1.addStretch(1)
        f, lay = card("Этап 1")
        lay.addWidget(box("Читаю телефон. Это 20–40 секунд…", "info"))
        add_card(self.p1, f)

        def job():
            raw = device.collect()
            res = verdict.build(raw)
            cid = store.create(raw["udid"], res, raw)
            est = price.estimate(res)
            store.update(cid, цена=est["итого"] or 0)
            return {"id": cid, "res": res, "est": est}

        def ok(r):
            self.cid, self.res, self.est = r["id"], r["res"], r["est"]
            self.apple_items = self.sickw_data = None
            self.build_stage1_results()

        def bad(msg):
            vclear(self.p1)
            self.p1.addStretch(1)
            f2, l2 = card("Этап 1")
            l2.addWidget(box("Не получилось: " + msg, "bad"))
            b = QPushButton("Ещё раз"); b.setProperty("sec", True)
            b.clicked.connect(self.build_stage1_start)
            l2.addWidget(b, 0, Qt.AlignLeft)
            add_card(self.p1, f2)

        self.work(job, ok, bad)

    # ---------- этап 1: результаты ----------

    def build_stage1_results(self):
        vclear(self.p1)
        self.p1.addStretch(1)
        r = self.res
        p, b = r["паспорт"], r["батарея"]

        # Итог
        f, lay = card("Итог по аппарату")
        h = QLabel(r["итог"]["вердикт"]); h.setProperty("h", True)
        h.setProperty("v", verdict_tone(r["итог"]["вердикт"]))
        lay.addWidget(h)
        lay.addWidget(hint(r["итог"]["почему"]))
        if r["стоп"]:
            lay.addWidget(box("Не принимать / разобраться:\n" + "\n".join(r["стоп"]), "bad"))
        if r["сделать"]:
            lay.addWidget(box("Сделать до приёмки:\n" + "\n".join(r["сделать"]), "warn"))
        if r["внимание"]:
            lay.addWidget(box("Влияет на цену:\n" + "\n".join(r["внимание"]), "warn"))
        add_card(self.p1, f)

        # Цена
        self.price_card, self.price_lay = card("Предварительная оценка")
        add_card(self.p1, self.price_card)
        self.redraw_price()

        # Сетка карточек
        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)

        fp, lp_ = card("Паспорт")
        for k, v in [("Модель", p["модель"]), ("Номер модели", p["номер_модели"]),
                     ("Серийный номер", p["серийник"]), ("Серийник платы", p["серийник_платы"]),
                     ("IMEI", p["imei"]),
                     ("Память", f'{p["память_гб"]} ГБ (свободно {p["свободно_гб"]})'),
                     ("iOS", p["ios"]),
                     ("Цвет", p["цвет"] or "по кабелю не определяется — впиши глазами")]:
            lp_.addWidget(row(k, v))

        fb, lb = card("Батарея")
        for k, v in [("Износ", f'{b["износ"]}%' if b["износ"] is not None else "не определился"),
                     ("Циклов", b["циклы"]),
                     ("Ёмкость", f'{b["ёмкость"]} из {b["завод"]} мА·ч заводских'),
                     ("Наработка", f'{b.get("наработка_лет", "—")} лет'),
                     ("Грелась до", f'{b.get("макс_темп", "—")}°C')]:
            lb.addWidget(row(k, v))
        if b["подделка"]:
            lb.addWidget(box("\n".join(b["подделка"]), "bad"))

        fd, ld = card("Детали")
        for k, v in r["детали"].items():
            if v["вердикт"] == "НЕТ В МОДЕЛИ":
                continue
            text = v["вердикт"] + (("\n" + v["почему"]) if v.get("почему") else "")
            ld.addWidget(row(k, text, verdict_tone(v["вердикт"])))
        ld.addWidget(hint("Сила доказательства разная: Face ID и Taptic проверены "
                          "сопряжением с платой — подделать, не перепрошив плату, нельзя. "
                          "Камеры и батарея — слабее. Фронтальная камера по кабелю не проверяется."))

        fl, ll = card("Юридический статус")
        ju = r["юридический"]
        for k, v in [("Найти iPhone", ju["найти_iphone"]), ("Активация", ju["активация"]),
                     ("Пароль на телефоне", "стоит — попроси снять" if ju["пароль"] else "нет"),
                     ("Корпоративный надзор", "ЕСТЬ (MDM)" if ju["mdm"] else "нет")]:
            ll.addWidget(row(k, v, "bad" if (k == "Корпоративный надзор" and ju["mdm"]) else "true"))

        grid.addWidget(fp, 0, 0)
        grid.addWidget(fb, 0, 1)
        grid.addWidget(fd, 1, 0)
        grid.addWidget(fl, 1, 1)
        add_card(self.p1, grid_holder)

        # Вердикт Apple
        self.apple_card, self.apple_lay = card("Вердикт Apple по запчастям")
        self.apple_lay.addWidget(hint("Это ответ самой Apple, а не вывод по косвенным "
            "признакам: по каждому узлу «меняли или нет» и «деталь новая или б/у», плюс дата. "
            "Покрывает и то, до чего кабелю не добраться — заднее стекло, корпус, плату."))
        ab = QPushButton("Получить вердикт Apple")
        ab.clicked.connect(self.get_apple)
        self.apple_lay.addWidget(ab, 0, Qt.AlignLeft)
        add_card(self.p1, self.apple_card)

        # Sickw
        self.sickw_card, self.sickw_lay = card("Внешняя база (Sickw)")
        self.draw_sickw_start()
        add_card(self.p1, self.sickw_card)

        # Дальше
        f6, l6 = card()
        nb = QPushButton("Клиент согласен с ценой → этап 2")
        nb.clicked.connect(lambda: (self.build_stage2(), self.show_page(1)))
        l6.addWidget(nb, 0, Qt.AlignLeft)
        add_card(self.p1, f6)

    def redraw_price(self):
        vclear(self.price_lay)
        t = QLabel("ПРЕДВАРИТЕЛЬНАЯ ОЦЕНКА"); t.setProperty("cardtitle", True)
        self.price_lay.addWidget(t)
        e = self.est
        if not e:
            return
        if e["отказ"]:
            self.price_lay.addWidget(box("\n".join(e["отказ"]), "bad"))
        if e["база_известна"]:
            self.price_lay.addWidget(row("База по модели и памяти", money(e["база"], e["валюта"])))
            for d in e["вычеты"]:
                self.price_lay.addWidget(row(d["за_что"], money(d["сумма"], e["валюта"]), "bad"))
            w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 6, 0, 0)
            kl = QLabel("К выплате"); kl.setProperty("k", True)
            vl = QLabel(money(e["итого"], e["валюта"])); vl.setProperty("price", True)
            h.addWidget(kl); h.addStretch(1); h.addWidget(vl)
            self.price_lay.addWidget(w)
        else:
            self.price_lay.addWidget(box("\n".join(e["чего_не_хватает"]) +
                "\nЦифры в prices.json — заглушки: ошибка в базовой цене дороже "
                "ошибки в диагностике.", "warn"))
            for d in e["вычеты"]:
                self.price_lay.addWidget(row(d["за_что"], money(d["сумма"], e["валюта"]), "bad"))

    def reprice(self):
        try:
            self.est = price.estimate(self.res, self.sickw_data, self.apple_items)
            if self.cid:
                store.update(self.cid, цена=self.est["итого"] or 0)
            self.redraw_price()
        except Exception as e:
            self.price_lay.addWidget(box(f"Пересчёт не удался: {e}", "bad"))

    # ---------- вердикт Apple ----------

    def get_apple(self):
        vclear(self.apple_lay)
        t = QLabel("ВЕРДИКТ APPLE ПО ЗАПЧАСТЯМ"); t.setProperty("cardtitle", True)
        self.apple_lay.addWidget(t)
        self.apple_lay.addWidget(box(
            "На телефоне открой:\nНастройки → Основные → Об этом устройстве → "
            "ЗАЙДИ в «Запчасти и история обслуживания».\n"
            "Нужен именно переход внутрь. Если экран уже открыт — выйди назад "
            "и зайди снова: Настройки кэшируют ответ.", "ok"))
        self.apple_lay.addWidget(box("Жду до 60 секунд…", "info"))

        def job():
            u = device.udid()
            items, _ = apple.capture(u, seconds=60)
            if self.cid and items:
                store.update(self.cid, apple=items)
            return items

        def ok(items):
            vclear(self.apple_lay)
            t2 = QLabel("ВЕРДИКТ APPLE ПО ЗАПЧАСТЯМ"); t2.setProperty("cardtitle", True)
            self.apple_lay.addWidget(t2)
            if not items:
                self.apple_lay.addWidget(box(
                    "Вердикт не появился. Либо в раздел не зашли, либо модель его "
                    "не показывает: на iPhone 11 это только батарея и экран, "
                    "на XR/XS/SE — только батарея, старше — ничего.", "warn"))
                b = QPushButton("Попробовать снова"); b.setProperty("sec", True)
                b.clicked.connect(self.get_apple)
                self.apple_lay.addWidget(b, 0, Qt.AlignLeft)
                return
            self.apple_items = items
            for v in sorted(items.values(), key=lambda x: x.get("код", 0)):
                if v["меняли"]:
                    text = "МЕНЯЛИ — " + ("Б/У деталь" if v["бу"] else "новая")
                    if v.get("дата"):
                        text += f'\n{v["дата"]}'
                    self.apple_lay.addWidget(row(v["деталь"], text, "bad"))
                else:
                    self.apple_lay.addWidget(row(v["деталь"], "не меняли", "ok"))
            self.reprice()

        def bad(msg):
            vclear(self.apple_lay)
            self.apple_lay.addWidget(box("Не получилось: " + msg, "bad"))
            b = QPushButton("Попробовать снова"); b.setProperty("sec", True)
            b.clicked.connect(self.get_apple)
            self.apple_lay.addWidget(b, 0, Qt.AlignLeft)

        self.work(job, ok, bad)

    # ---------- Sickw ----------

    def draw_sickw_start(self):
        vclear(self.sickw_lay)
        t = QLabel("ВНЕШНЯЯ БАЗА (SICKW)"); t.setProperty("cardtitle", True)
        self.sickw_lay.addWidget(t)
        self.sickw_lay.addWidget(hint(
            "Чёрный список, цвет, заводская конфигурация, даты покупки и активации, "
            "статусы оператора и iCloud. Независимо от телефона — подделке со стороны "
            "аппарата неподвластно. Запрос платный, около $0.10."))
        if sickw.key_available():
            b = QPushButton("Проверить по IMEI (платно)")
            b.clicked.connect(self.get_sickw)
            self.sickw_lay.addWidget(b, 0, Qt.AlignLeft)
        else:
            self.sickw_lay.addWidget(box(
                "Ключ Sickw не задан. Впиши его в ⚙ Настройках.", "warn"))

    def get_sickw(self):
        imei = self.res["паспорт"]["imei"]
        a = QMessageBox.question(
            self, "Pintel Проверка",
            f"Отправить IMEI {imei} в Sickw?\n\nЗапрос платный (~$0.10) "
            "и списывается даже при неудаче.")
        if a != QMessageBox.Yes:
            return
        vclear(self.sickw_lay)
        self.sickw_lay.addWidget(box("Спрашиваю внешнюю базу…", "info"))

        def job():
            s = sickw.lookup(imei)
            if self.cid:
                store.update(self.cid, sickw=s)
            return s

        def ok(s):
            self.sickw_data = s
            vclear(self.sickw_lay)
            t = QLabel("ВНЕШНЯЯ БАЗА (SICKW)"); t.setProperty("cardtitle", True)
            self.sickw_lay.addWidget(t)
            blk = s.get("чёрный_список") or ""
            bad_list = blk and blk.strip().upper() not in ("CLEAN", "CLEAR")
            if bad_list:
                self.sickw_lay.addWidget(box(f"ЧЁРНЫЙ СПИСОК: {blk} — не принимать", "bad"))
            if (s.get("icloud") or "").strip().upper() == "ON":
                self.sickw_lay.addWidget(box("iCloud включён — клиент должен выйти из Apple ID", "warn"))
            for k, v, tone in [
                    ("Модель с завода", s.get("модель_строка") or "—", "true"),
                    ("Цвет с завода", s.get("цвет") or "не вычленился", "true"),
                    ("Объём с завода", f'{s["объём_гб"]} ГБ' if s.get("объём_гб") else "—", "true"),
                    ("Чёрный список", blk or "—", "bad" if bad_list else "ok"),
                    ("iCloud", s.get("icloud") or "—", "true"),
                    ("SIM-lock", s.get("sim_lock") or "—", "true"),
                    ("Оператор", s.get("оператор") or "—", "true"),
                    ("Гарантия", s.get("гарантия") or "—", "true"),
                    ("Дата покупки", s.get("дата_покупки") or "—", "true")]:
                self.sickw_lay.addWidget(row(k, v, tone))
            self.reprice()

        def bad(msg):
            vclear(self.sickw_lay)
            self.sickw_lay.addWidget(box(msg, "bad"))
            b = QPushButton("Повторить"); b.setProperty("sec", True)
            b.clicked.connect(self.draw_sickw_start)
            self.sickw_lay.addWidget(b, 0, Qt.AlignLeft)

        self.work(job, ok, bad)

    # ---------- этап 2 ----------

    def build_stage2(self):
        vclear(self.p2)
        self.p2.addStretch(1)

        f, lay = card("Этап 2 — то, что по кабелю не проверить")
        lay.addWidget(hint("Кабель отвечает на «оригинал или нет», но не на "
                           "«работает или нет». Эти проверки требуют рук и глаз."))
        lay.addWidget(box("Открой на телефоне веб-тест:  barcode-scan.duckdns.org/apps/diag.html\n"
                          "Экран, тачскрин, мультитач, динамик с микрофоном, обе камеры, "
                          "датчики, геолокация — автоматически в браузере телефона.", "ok"))
        add_card(self.p2, f)

        f2, l2 = card("Отметь найденное")
        self.checks = {}
        for k, t in MANUAL:
            c = QCheckBox(t)
            self.checks[k] = c
            l2.addWidget(c)
        l2.addWidget(hint("Цвет аппарата (по кабелю не определяется)"))
        self.colour = QLineEdit(placeholderText="например: чёрный, синий, титан…")
        l2.addWidget(self.colour)
        l2.addWidget(hint("Заметки приёмщика"))
        self.notes = QTextEdit(); self.notes.setFixedHeight(80)
        l2.addWidget(self.notes)
        add_card(self.p2, f2)

        f3, l3 = card()
        h = QHBoxLayout()
        save = QPushButton("Сохранить и перейти к финалу")
        save.clicked.connect(self.save_stage2)
        back = QPushButton("Назад к этапу 1"); back.setProperty("sec", True)
        back.clicked.connect(lambda: self.show_page(0))
        h.addWidget(save); h.addWidget(back); h.addStretch(1)
        l3.addLayout(h)
        add_card(self.p2, f3)

    def save_stage2(self):
        r = {k: c.isChecked() for k, c in self.checks.items()}
        r["цвет"] = self.colour.text().strip()
        r["заметки"] = self.notes.toPlainText().strip()
        if self.cid:
            store.update(self.cid, этап=2, этап2=r)
        self.build_stage3()
        self.show_page(2)

    # ---------- этап 3 ----------

    def build_stage3(self):
        vclear(self.p3)
        self.p3.addStretch(1)

        f, lay = card("Этап 3 — финал")
        lay.addWidget(hint("Здесь будет связка с Pintel Оценка, Pay и МойСкладом: "
                           "создание сделки, карточка товара, выплата. Пока — ручная "
                           "фиксация, всё уже записано в базу приёмок."))
        p = self.res["паспорт"]
        lay.addWidget(row("Аппарат", f'{p["модель"]} · {p["серийник"]}'))
        lay.addWidget(row("Вердикт", self.res["итог"]["вердикт"],
                          verdict_tone(self.res["итог"]["вердикт"])))
        lay.addWidget(row("Предварительная цена",
                          money(self.est and self.est["итого"],
                                self.est and self.est["валюта"])))
        lay.addWidget(hint("Итоговая цена, согласованная с клиентом"))
        self.final_price = QLineEdit(placeholderText="введи сумму")
        lay.addWidget(self.final_price)
        lay.addWidget(hint("Способ выкупа"))
        self.method = QComboBox()
        self.method.addItems(["Выкуп", "Trade-In"])
        lay.addWidget(self.method)
        h = QHBoxLayout()
        done = QPushButton("Завершить приёмку")
        done.clicked.connect(self.save_stage3)
        back = QPushButton("Назад к этапу 2"); back.setProperty("sec", True)
        back.clicked.connect(lambda: self.show_page(1))
        h.addWidget(done); h.addWidget(back); h.addStretch(1)
        lay.addLayout(h)
        self.done_lay = lay
        add_card(self.p3, f)

    def save_stage3(self):
        if self.cid:
            store.update(self.cid, этап=3, этап3={
                "итоговая_цена": self.final_price.text().strip(),
                "способ": self.method.currentText()})
        self.done_lay.addWidget(box(f"Приёмка №{self.cid} завершена и записана.", "ok"))
        nb = QPushButton("Следующий телефон"); nb.setProperty("sec", True)
        nb.clicked.connect(self.reset_all)
        self.done_lay.addWidget(nb, 0, Qt.AlignLeft)

    def reset_all(self):
        self.cid = self.res = self.est = None
        self.apple_items = self.sickw_data = None
        vclear(self.p2); self.p2.addStretch(1)
        vclear(self.p3); self.p3.addStretch(1)
        self.build_stage1_start()
        self.show_page(0)

    # ---------- настройки ----------

    def build_settings(self):
        vclear(self.p4)
        self.p4.addStretch(1)

        # — ключ Sickw —
        f, lay = card("Ключ Sickw")
        tail = sickw.key_tail()
        lay.addWidget(box(f"Ключ стоит: ····{tail}", "ok") if tail
                      else box("Ключ не задан — проверка по внешней базе выключена.", "warn"))
        h = QHBoxLayout()
        self.key_edit = QLineEdit(placeholderText="вставь ключ API с sickw.com")
        save = QPushButton("Сохранить")
        save.clicked.connect(self.save_sickw_key)
        h.addWidget(self.key_edit, 1)
        h.addWidget(save)
        lay.addLayout(h)
        if tail:
            rm = QPushButton("Убрать ключ"); rm.setProperty("sec", True)
            rm.clicked.connect(self.remove_sickw_key)
            lay.addWidget(rm, 0, Qt.AlignLeft)
        lay.addWidget(hint("Ключ хранится в файле у тебя на компьютере (~/.sickw_key), "
                           "в программу не вшивается. Запросы платные, ~$0.10, "
                           "поэтому всегда по кнопке."))
        add_card(self.p4, f)

        # — драйверы —
        f2, l2 = card("Драйверы и инструменты")
        self.drv_lay = l2
        b = QPushButton("Проверить доступность драйверов")
        b.clicked.connect(self.check_drivers)
        l2.addWidget(b, 0, Qt.AlignLeft)
        add_card(self.p4, f2)

    def save_sickw_key(self):
        k = self.key_edit.text().strip()
        if not k:
            return
        sickw.save_key(k)
        self.build_settings()

    def remove_sickw_key(self):
        a = QMessageBox.question(self, "Pintel Проверка", "Убрать ключ Sickw?")
        if a == QMessageBox.Yes:
            sickw.save_key("")
            self.build_settings()

    def check_drivers(self):
        vclear(self.drv_lay)
        t = QLabel("ДРАЙВЕРЫ И ИНСТРУМЕНТЫ"); t.setProperty("cardtitle", True)
        self.drv_lay.addWidget(t)
        self.drv_lay.addWidget(box("Проверяю…", "info"))

        def ok(r):
            vclear(self.drv_lay)
            t2 = QLabel("ДРАЙВЕРЫ И ИНСТРУМЕНТЫ"); t2.setProperty("cardtitle", True)
            self.drv_lay.addWidget(t2)
            self.drv_lay.addWidget(box("Всё готово. Можно принимать телефоны.", "ok")
                                   if r["всё_готово"] else
                                   box(f'Осталось сделать: {r["осталось"]}. Что именно — ниже.', "warn"))
            for i in r["пункты"]:
                mark = "✅" if i["готово"] else ("⚪" if i.get("необязательно") else "⛔")
                tone = "ok" if i["готово"] else ("true" if i.get("необязательно") else "bad")
                self.drv_lay.addWidget(row(f'{mark} {i["что"]}',
                                           i["где"] or i["почему"] or "", tone))
                if not i["готово"] and i.get("как_починить"):
                    fix = hint(i["как_починить"] + (f'\n{i["ссылка"]}' if i.get("ссылка") else ""))
                    fix.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    self.drv_lay.addWidget(fix)
            self.drv_lay.addWidget(hint(
                f'Система: {r["система"]}, Python {r["python"]}. Программа ничего не '
                "скачивает из интернета сама: это защита кассового компьютера."))
            b = QPushButton("Проверить ещё раз"); b.setProperty("sec", True)
            b.clicked.connect(self.check_drivers)
            self.drv_lay.addWidget(b, 0, Qt.AlignLeft)

        def bad(msg):
            vclear(self.drv_lay)
            self.drv_lay.addWidget(box("Проверка упала: " + msg, "bad"))
            b = QPushButton("Ещё раз"); b.setProperty("sec", True)
            b.clicked.connect(self.check_drivers)
            self.drv_lay.addWidget(b, 0, Qt.AlignLeft)

        self.work(setup.check, ok, bad)


# ─────────────────────────── запуск ───────────────────────────

def run():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    w = MainWindow()
    w.show()
    return app.exec()


def selftest():
    """Для автосборки: окно строится без экрана, инструменты на месте.
    Печатает отчёт и возвращает код выхода."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    w = MainWindow()          # упадёт — selftest провален
    r = setup.check()
    tools = [i for i in r["пункты"] if str(i["что"]).startswith("idevice")]
    ok = len(tools) == 4 and all(i["готово"] for i in tools)
    report = {"ui": "ok", "инструментов": len(tools),
              "готовы": [i["что"] for i in tools if i["готово"]],
              "не_готовы": [i["что"] for i in tools if not i["готово"]]}
    line = ("SELFTEST OK " if ok else "SELFTEST FAIL ") + json.dumps(report, ensure_ascii=False)
    print(line, flush=True)
    # Дублируем в файл: у окна без консоли stdout бывает пуст, а отчёт нужен.
    try:
        from core.paths import beside
        with open(beside("selftest.txt"), "w", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    # Жёсткий выход: уборка Qt без экрана умеет падать в segfault уже ПОСЛЕ
    # теста, и код выхода врал бы. Отчёт записан — просто выходим.
    sys.stdout.flush()
    os._exit(0 if ok else 1)
