# -*- coding: utf-8 -*-
"""Вёрстка экранов точки: ничего не обрезано и ничто ни на что не наезжает.

Зачем такой тест. Экраны свёрстаны на 1920×1080 и плотные: три колонки, карточки с QR,
списки проверок. Любая новая строка или кнопка отнимает место у соседей, и ломается это
молча — на машине разработчика окно просто перерисовывается, а на точке сотрудник читает
«Детали и обслуживание:» без конца фразы или видит текст поверх текста. Так уже было
дважды: подписи пунктов обрывались на полуслове, а итог прошлой проверки ложился поверх
нового (старые подписи удалялись через `deleteLater` и до следующего круга цикла событий
оставались на экране).

Проверяем ровно две вещи на всех экранах и во всех состояниях:

* **обрезано** — виджету не хватает места на его собственный текст;
* **наезд** — два видимых соседа пересекаются прямоугольниками.

Числа подписей и размеры шрифтов тест не знает: он сравнивает запрошенное у шрифта с тем,
что дал слой вёрстки, и поэтому переживает любую правку текстов.
"""
import os
import tempfile

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())

from PySide6.QtWidgets import QApplication, QLabel, QPushButton    # noqa: E402

from pintel_core import phonetest, reference                        # noqa: E402
from pintel_core.analysis import report as report_mod               # noqa: E402
from pintel_core.devicelink import snapshot                         # noqa: E402
from pintel_kiosk import ui, ui_admin, ui_deal, ui_start            # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ЭТАЛОН = os.path.join(HERE, "fixtures_real", "эталоны", "эталон_iPhone-14-Pro_iOS26.5.zip")
# запас на поля кнопки: надпись, прижатая к самому краю, читается как вылезшая за него
ПОЛЯ_КНОПКИ = 24


# Ссылку на приложение держим в модуле: если его соберёт сборщик мусора раньше окон,
# Qt падает уже на выходе из интерпретатора, и прогон кончается ненулевым кодом при всех
# пройденных тестах.
_ПРИЛОЖЕНИЕ = None


@pytest.fixture(scope="module")
def приложение():
    global _ПРИЛОЖЕНИЕ
    _ПРИЛОЖЕНИЕ = QApplication.instance() or QApplication([])
    ui.load_fonts()
    _ПРИЛОЖЕНИЕ.setFont(ui.app_font())
    _ПРИЛОЖЕНИЕ.setStyleSheet(ui.QSS)
    return _ПРИЛОЖЕНИЕ


@pytest.fixture(scope="module")
def отчёт():
    snap, _ = reference.load_bundle(ЭТАЛОН, loads=snapshot.loads)
    return report_mod.build(snap)


def _обрезано(w):
    """Текст виджета не помещается в отведённый ему прямоугольник? → почему или пусто."""
    if isinstance(w, QLabel):
        if not w.text() or w.pixmap() is not None:
            return ""
        if w.wordWrap():
            надо = w.heightForWidth(w.width())
            if надо > w.height() + 1:
                return f"нужно {надо} px высоты, дано {w.height()}"
        else:
            надо = w.fontMetrics().horizontalAdvance(w.text())
            if надо > w.width() + 1:
                return f"нужно {надо} px ширины, дано {w.width()}"
            if w.fontMetrics().height() > w.height() + 1:
                return f"нужно {w.fontMetrics().height()} px высоты, дано {w.height()}"
    elif isinstance(w, QPushButton) and w.text():
        надо = w.fontMetrics().horizontalAdvance(w.text()) + ПОЛЯ_КНОПКИ
        if надо > w.width() + 1:
            return f"надпись просит {надо} px с полями, дано {w.width()}"
    return ""


def _замечания(корень):
    """Все обрезанные подписи и все наезды соседей внутри экрана."""
    QApplication.sendPostedEvents()
    if корень.layout() is not None:
        корень.layout().activate()
    QApplication.processEvents()
    беда = []
    видимые = [w for w in корень.findChildren(QLabel) + корень.findChildren(QPushButton)
               if w.isVisible()]
    for w in видимые:
        почему = _обрезано(w)
        if почему:
            беда.append(f"обрезано: «{(w.text() or '')[:44]}» — {почему}")
    по_родителям = {}
    for w in видимые:
        if not w.geometry().isEmpty():
            по_родителям.setdefault(id(w.parent()), []).append(w)
    for соседи in по_родителям.values():
        for i, a in enumerate(соседи):
            for b in соседи[i + 1:]:
                общее = a.geometry().intersected(b.geometry())
                if общее.width() > 2 and общее.height() > 2:
                    беда.append(f"наезд: «{(a.text() or '')[:26]}» на «{(b.text() or '')[:26]}» "
                                f"({общее.width()}×{общее.height()} px)")
    return sorted(set(беда))


@pytest.fixture
def открыть(приложение):
    """Открыть экран и закрыть его после теста.

    Убирать за собой обязательно: оставленные окна Qt разрушает уже на выходе из
    интерпретатора, в произвольном порядке, и прогон на сборочной машине падал не тестом,
    а кодом возврата — при том, что все тесты прошли."""
    открытые = []

    def завести(класс, *аргументы):
        w = класс(*аргументы)
        w.setFixedSize(1920, 1080)
        w.show()
        QApplication.processEvents()
        открытые.append(w)
        return w

    yield завести
    for w in открытые:
        w.close()
        w.setParent(None)
        w.deleteLater()
    QApplication.processEvents()


def test_the_idle_screen_fits(открыть):
    """Экран ожидания: статус, кнопка начала и предложение обновиться."""
    экран = открыть(ui.MainScreen, "16/38 Pintel")
    экран.set_status("Автономно: нет связи с сервером ConnectError", ok=False)
    экран.показать_обновление("Обновить программу — не вышло, повторить")
    assert _замечания(экран) == []


def test_the_intake_screen_fits(открыть):
    """Анкета до кабеля: состояние четырьмя кнопками, имя и телефон клиента."""
    экран = открыть(ui_start.StartScreen, "16/38 Pintel")
    экран.начать()
    assert _замечания(экран) == []


def test_every_page_of_the_deal_screen_fits(открыть, отчёт):
    """Рабочее окно во всех состояниях: до проверки, с итогом, на каждой карточке справа.

    Это самый плотный экран программы — три колонки, и в правой живут QR, семь строк теста,
    восемь проверок руками и кнопки."""
    экран = открыть(ui_deal.WorkScreen, "16/38 Pintel")
    assert _замечания(экран) == [], "окно до проверки"

    экран.set_клиент("Зама", "+77058837953")
    экран.показать(отчёт)
    экран.показать_код("P7KQ2M", "https://t.me/PintelOlxBot?start=pP7KQ2M")
    экран.показать_тест("https://kiosk.pintelkz.com/t/ABCDEF1234567890")
    for страница, имя in ((ui_deal.СТР_APPLE, "шаг Apple"), (ui_deal.СТР_ТЕСТ, "тест"),
                          (ui_deal.СТР_РУЧНАЯ, "проверки руками"), (ui_deal.СТР_МЕДИА, "медиа"),
                          (ui_deal.СТР_ГОТОВО, "отправлено")):
        экран.правая.setCurrentIndex(страница)
        assert _замечания(экран) == [], имя

    экран.set_тест({k: phonetest.ОК for k in phonetest.КЛЮЧИ})
    экран.set_медиа({"известно": True, "начали": True, "фото": 2, "видео": False, "готово": False})
    экран.правая.setCurrentIndex(ui_deal.СТР_МЕДИА)
    assert _замечания(экран) == [], "медиа с результатом теста"

    экран.правая.setCurrentIndex(ui_deal.СТР_РУЧНАЯ)
    экран.отметить("keys")                    # работает
    экран.отметить("water")
    экран.отметить("water")                   # НЕ работает — подпись длиннее
    assert _замечания(экран) == [], "проверки руками с отметками"


def test_the_result_is_not_drawn_twice_over_itself(открыть, отчёт):
    """Второй показ итога не оставляет первый на экране.

    `показать` вызывается повторно: когда с телефона приходит журнал Apple и когда взята
    прошлая проверка. Старые подписи удалялись отложенно и до следующего круга цикла
    событий лежали поверх новых — на экране точки это читалось как «текст по тексту»."""
    экран = открыть(ui_deal.WorkScreen, "16/38 Pintel")
    экран.показать(отчёт)
    повтор = dict(отчёт)
    повтор["повторная_проверка"] = {"словами": "сегодня в 13:20, 40 мин назад",
                                    "возраст_мин": 40, "сверка": "не сверили: телефон не ответил"}
    экран.показать(повтор)
    экран.показать(повтор)
    assert _замечания(экран) == []


def test_the_sealed_deal_screen_fits(открыть):
    """Запечатанный: шагов кабеля нет, зато в шапке два IMEI с коробки."""
    экран = открыть(ui_deal.WorkScreen, "16/38 Pintel")
    экран.режим(True, ["350585886690250", "350585881725184"])
    assert _замечания(экран) == []


def test_the_setup_and_admin_screens_fit(открыть):
    """Первая настройка (выбор точки и токен) и меню администратора."""
    токен = открыть(ui_admin.TokenScreen)
    токен.показать_точки([{"id": 1, "название": "16/38 Pintel"},
                          {"id": 2, "название": "ТРЦ Астана", "литера": "АС"}])
    assert _замечания(токен) == []

    админ = открыть(ui_admin.AdminScreen)
    админ.показать({"Сервер": "https://kiosk.pintelkz.com", "Точка": "16/38 Pintel (id 14)",
                    "Этот компьютер": "KASSA-14", "Токен": "pk_abc…", "Версия": "doctor-67",
                    "Оценок в очереди": 0, "Бот Оценки": "PintelOlxBot"})
    assert _замечания(админ) == []
