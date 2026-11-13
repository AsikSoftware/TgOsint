# -*- coding: utf-8 -*-
"""Чек на A4: клиент уносит его с собой, значит в нём не должно быть ни лишнего,
ни недосказанного. Содержимое проверяем здесь, вёрстку — глазами на печати."""
import os
import re

from pintel_core import receipt, reference
from pintel_core.devicelink import snapshot

HERE = os.path.dirname(os.path.abspath(__file__))


def _отчёт(архив="эталон_iPhone-14-Pro_iOS26.5.zip"):
    from pintel_core.analysis import report as report_mod
    snap, _ = reference.load_bundle(os.path.join(HERE, "fixtures_real", "эталоны", архив),
                                    loads=snapshot.loads)
    return report_mod.build(snap)


СДЕЛКА = {"номер": 7093, "клиент": "Зама",
          "телефон": "+77058837953", "сотрудник": "Асылбек", "точка": "16/38 Pintel",
          "коробка": True, "шнур": False}


def test_receipt_is_a_document_not_a_printout():
    """Клиент уносит это с собой: на листе должны быть логотип и реквизиты, иначе бумага
    ничья. Логотип вшит в страницу — чек открывается без интернета и соседних файлов.
    В шапке телефон и сайт; адрес и БИН не печатаем — так решил владелец."""
    txt = receipt.html({**СДЕЛКА, "фирма": {"название": "Pintel", "бин": "123456789012",
                                            "телефон": "+7 777 000 00 00", "адрес": "Алматы, Абая 1",
                                            "сайт": "pintel.kz"}},
                       _отчёт())
    assert "data:image/png;base64," in txt and "БИН" not in txt and "123456789012" not in txt
    assert "Алматы, Абая 1" not in txt
    assert "<div class=\"реквизиты\">+7 777 000 00 00<br>pintel.kz</div>" in txt
    assert txt.count("подпись") == 2                 # подписывают обе стороны


def test_receipt_shows_everything_the_check_saw():
    """Прошлый чек печатал шесть строк «оригинальная» и ни слова о блокировках. Клиент
    должен видеть, за что ему назвали цену."""
    txt = receipt.html(СДЕЛКА, _отчёт())
    for раздел in ("Телефон", "Проверка подлинности", "Аккумулятор", "Блокировки и история"):
        assert раздел in txt, раздел
    assert "Циклов заряда" in txt and "Найти iPhone" in txt
    assert "Серийный номер" in txt and "Комплект" in txt


def test_receipt_has_nothing_the_owner_removed():
    """Форму листа владелец собрал сам (13.11.2026) и убрал с него: итог проверки одной
    строкой, плашку «Apple подтвердила…», блок «На что обратить внимание» с комментарием
    оценщика, свободную память, пояснения у QR и сноску. «Для полноты» они не возвращаются."""
    rep = _отчёт("эталон_iPhone-15-Pro_iOS26.6.1.zip")            # проблемный: поводов больше всего
    txt = receipt.html({**СДЕЛКА, "комментарий": "скол у камеры", "ссылка": "https://kiosk.example/c/x"}, rep)
    for лишнее in ("Итог проверки", "ПРОБЛЕМНЫЙ", "Apple подтвердила", "не подтвердила",
                   "На что обратить внимание", "скол у камеры", "Свободно", "Этот чек в интернете",
                   "Наведите камеру", "kiosk.example", "не является договором", "по кабелю: прочитаны"):
        assert лишнее not in txt, лишнее
    assert "<svg" in txt                              # сам QR на месте


def test_receipt_has_no_price_at_all():
    """Цену называет Оценка по своему прайсу уже после создания сделки. Напечатать на
    бумаге сумму, которой ещё нет, значит пообещать то, что потом не совпадёт."""
    txt = receipt.html(СДЕЛКА, _отчёт())
    for слово in ("₸", "Цена", "цена", "250 000", "Действительна"):
        assert слово not in txt, слово


def test_receipt_shows_device_and_people():
    rep = _отчёт()
    txt = receipt.html(СДЕЛКА, rep)
    assert "iPhone 14 Pro" in txt and "№ 7093" in txt
    assert "Зама" in txt and "Асылбек" in txt and "16/38 Pintel" in txt
    assert "Клиент" in txt and "Оценку провёл" in txt


def test_parts_are_a_table_with_maker_code_and_year():
    """По каждой детали: производитель, код, год выпуска и результат. Производитель известен
    не у всех (подтверждён только экран) — тогда остаются код и год; серийника нет вовсе —
    только результат. Код — первые три знака серийника детали, год — из него же."""
    rep = _отчёт()
    rep["детали"] = [
        {"деталь": "Экран (панель)", "серийник": "G9N2301ABCDEFGHJK", "дата": "2022-08-14", "производитель": "Samsung"},
        {"деталь": "Аккумулятор", "серийник": "F8Y2251ABCDEFGHJK", "дата": "2022-07-02", "производитель": None},
        {"деталь": "Основная камера", "серийник": "DN82291ABCDEFGHJK", "дата": "2022-06-20", "производитель": None},
        {"деталь": "Taptic Engine", "серийник": "GH7ABCDEFGHJK", "дата": None, "производитель": None},
        {"деталь": "ИК-камера Face ID", "серийник": "���мусор", "дата": None, "производитель": None},
    ]
    строки = {x["деталь"]: x for x in receipt.данные_из_отчёта(rep)["детали"]}
    assert (строки["Экран"]["производитель"], строки["Экран"]["код"], строки["Экран"]["год"]) == ("Samsung", "G9N", "2022")
    assert (строки["Аккумулятор"]["производитель"], строки["Аккумулятор"]["код"], строки["Аккумулятор"]["год"]) == ("", "F8Y", "2022")
    assert (строки["Камера"]["код"], строки["Камера"]["год"]) == ("DN8", "2022")
    assert (строки["Taptic Engine"]["код"], строки["Taptic Engine"]["год"]) == ("GH7", "")   # года в серийнике нет
    assert (строки["Face ID"]["код"], строки["Face ID"]["год"]) == ("", "")                 # серийник не прочитался
    assert (строки["Верхний модуль"]["код"], строки["Верхний модуль"]["год"]) == ("", "")   # серийника нет вовсе
    assert all(x["результат"] == "оригинальная" for x in строки.values())

    txt = receipt.html(СДЕЛКА, rep)
    for слово in ("Деталь", "Производитель", "Код", "Год выпуска", "Результат"):
        assert f"<span>{слово}</span>" in txt, слово
    assert ("<div class='деталь'><span class='к'>Экран</span><span>Samsung</span><span>G9N</span>"
            "<span>2022</span><span class='з ок'>оригинальная</span></div>") in txt
    assert ("<div class='деталь'><span class='к'>Верхний модуль</span><span></span><span></span>"
            "<span></span><span class='з ок'>оригинальная</span></div>") in txt


def test_receipt_lists_unconfirmed_parts():
    rep = _отчёт("эталон_iPhone-15-Pro_iOS26.6.1.zip")
    txt = receipt.html(СДЕЛКА, rep)
    assert "Экран" in txt and "не подтверждена" in txt and "з плохо" in txt


def test_battery_block_has_the_lifetime_maximum_temperature():
    """Максимальная температура батареи за жизнь — из её же памяти. На iOS 27 телефон этого
    числа не отдаёт: строки тогда просто нет, а не «0 °C»."""
    rep = _отчёт()
    assert rep["батарея"]["макс_температура"] == 59
    assert "Максимальная температура" in receipt.html(СДЕЛКА, rep) and "59 °C" in receipt.html(СДЕЛКА, rep)
    rep["батарея"] = {**rep["батарея"], "макс_температура": None}
    assert "Максимальная температура" not in receipt.html(СДЕЛКА, rep)


def test_first_purchase_date_comes_from_the_imei_database():
    rep = _отчёт()
    assert "Дата первой покупки" not in receipt.html(СДЕЛКА, rep)          # базы не спрашивали
    rep["sickw"] = {"дата_покупки": "2022-10-14"}
    assert ("<span class='к'>Дата первой покупки</span><span class='з '>14.10.2022</span>"
            in receipt.html(СДЕЛКА, rep))


def test_receipt_hides_empty_rows():
    """Пустые поля не печатаем: пустая строка в чеке выглядит как недоработка."""
    rep = _отчёт()
    rep["паспорт"] = {**rep["паспорт"], "цвет": None, "imei2": ""}
    txt = receipt.html(СДЕЛКА, rep)
    assert "Цвет" not in txt and "IMEI 2" not in txt
    assert "IMEI" in txt and "Свободно" not in txt and "Верификация" not in txt


def test_receipt_is_plain_html_without_scripts():
    """Печатаем документ, а не страницу: ни скриптов, ни внешних загрузок."""
    txt = receipt.html({**СДЕЛКА, "ссылка": "https://kiosk.example/c/x"}, _отчёт())
    assert "<script" not in txt.lower() and "http://" not in txt.replace("http://www.w3.org", "")
    assert "https://" not in txt
    assert re.search(r"@page\s*{[^}]*A4", txt)


def test_receipt_escapes_client_input():
    """Имя клиента приходит с клавиатуры — в документе оно должно остаться текстом."""
    сделка = {**СДЕЛКА, "клиент": '<b>Зама</b> & "сын"'}
    txt = receipt.html(сделка, _отчёт())
    assert "&lt;b&gt;Зама&lt;/b&gt;" in txt and "<b>Зама</b>" not in txt


def test_the_registry_answer_stands_under_its_own_imei():
    """Реестр РФС отвечает по каждому IMEI сам, и ответы бывают разные. Строка стоит под
    своим номером — «Верификация IMEI 1 / 2», — со сроком временного доступа: клиент должен
    знать, что после него телефон перестанет работать в сетях Казахстана."""
    rep = _отчёт()
    первый, второй = rep["паспорт"]["imei"], rep["паспорт"]["imei2"]
    rep["рфс"] = [{"imei": первый, "verdict": "verified", "ok": True, "deadline": None},
                  {"imei": второй, "verdict": "not_verified", "ok": True, "deadline": "31.12.2026"}]
    txt = receipt.html(СДЕЛКА, rep)
    assert "<span class='к'>Верификация IMEI 1</span><span class='з ок'>верифицирован</span>" in txt
    assert "<span class='к'>Верификация IMEI 2</span><span class='з внимание'>не верифицирован" in txt
    assert "до 31.12.2026" in txt and "Реестр РФС" not in txt
    assert txt.index(f">{первый}<") < txt.index("Верификация IMEI 1") < txt.index(f">{второй}<") \
        < txt.index("Верификация IMEI 2")

    rep["рфс"] = [{"imei": первый, "verdict": "blocked", "ok": True}, {"imei": второй, "ok": False}]
    txt = receipt.html(СДЕЛКА, rep)
    assert "<span class='з плохо'>ЗАБЛОКИРОВАН</span>" in txt and "реестр не ответил" in txt


def test_the_test_report_is_at_the_bottom():
    """Внизу листа — отчёт по тестам: тест на телефоне клиента и проверки руками. Галочка —
    прошёл, крест — нет, прочерк — не проверяли."""
    from pintel_core import phonetest
    from pintel_core.external import ocenka_media
    тест = {k: phonetest.ОК for k in phonetest.КЛЮЧИ}
    тест.update({"speaker": phonetest.ПЛОХО, "mic": phonetest.ПРОПУСК, "заметка": "хрипит"})
    ручная = {k: True for k in ocenka_media.КЛЮЧИ}
    ручная["glue"] = False
    txt = receipt.html({**СДЕЛКА, "тест": тест, "ручная": ручная}, _отчёт())
    assert "Тест на телефоне" in txt and "Проверка руками" in txt
    assert "<span class='т'>Сенсор</span>" in txt and "<span class='т сбой'>Динамик</span>" in txt
    assert "<span class='т пропуск'>Микрофон</span>" in txt
    assert "<span class='т'>Кнопки</span>" in txt and "<span class='т сбой'>Герметик</span>" in txt
    assert txt.count("<span class='т") == len(phonetest.КЛЮЧИ) + len(ocenka_media.КЛЮЧИ)
    assert "хрипит" not in txt                        # заметка со страницы теста — не для чека
    assert txt.index("Проверка подлинности") < txt.index("Тест на телефоне") < txt.index("Оценку провёл")

    пропущен = receipt.html({**СДЕЛКА, "тест": {}, "тест_пропущен": "телефон не в нашей сети"}, _отчёт())
    assert "Не проводился: телефон не в нашей сети" in пропущен

    # данных нет вовсе (касса прежней сборки) — блока нет: сетка из прочерков читалась бы
    # как «ничего не работает»
    пусто = receipt.html(СДЕЛКА, _отчёт())
    assert "Тест на телефоне" not in пусто and "Проверка руками" not in пусто and "<span class='т" not in пусто


def test_sealed_receipt_says_the_box_was_not_opened():
    """Запечатанный кабелем не читался — чек не должен делать вид, что читался."""
    from pintel_core.analysis import sealed
    rep = sealed.build({"модель": "iPhone 15 Pro", "объём_гб": 256, "цвет": "натуральный титан",
                        "активация": "Not Activated", "активирован": False, "в_чёрном_списке": False},
                       ["350585886690250"], [{"imei": "350585886690250", "verdict": "verified", "ok": True}])
    txt = receipt.html({**СДЕЛКА, "ручная": {"sealed": True}}, rep)
    assert "Коробка не вскрыта" in txt and "кабелем аппарат не читался" in txt and "по базе IMEI" in txt
    assert "Производитель" not in txt and "<span class='т" not in txt      # ни таблицы деталей, ни тестов
    assert "iPhone 15 Pro" in txt and "Not Activated" in txt and "256 ГБ" in txt and "NATURAL" in txt
    assert "Верификация IMEI 1" in txt and "верифицирован" in txt


def test_the_receipt_says_when_the_check_was_not_repeated():
    """Проверку могли взять прошлую — на бумаге, которую клиент уносит, это должно быть
    написано.

    Иначе чек выглядит как результат чтения, сделанного при клиенте, а данные в нём — от
    прошлого визита того же телефона. Сноску с листа владелец убрал, поэтому строка стоит
    под заголовком и появляется только в этом случае."""
    rep = _отчёт()
    rep["повторная_проверка"] = {"словами": "сегодня в 13:20, 40 мин назад", "возраст_мин": 40,
                                 "сверка": "сошлась"}
    txt = receipt.html(СДЕЛКА, rep)
    assert "сегодня в 13:20, 40 мин назад" in txt and "не перечитывали" in txt
    assert "не перечитывали" not in receipt.html(СДЕЛКА, _отчёт())
