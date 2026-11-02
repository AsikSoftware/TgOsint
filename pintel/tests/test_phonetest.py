# -*- coding: utf-8 -*-
"""Тест на телефоне клиента: словарь ответов и мини-сервер, который их принимает.

Страница открывается на аппарате, которого мы не знаем, по сети, где есть и другие
устройства. Поэтому здесь проверяется ровно две вещи: что в сделку из этого не попадёт
ничего, кроме наших же ключей и наших же трёх ответов, и что результат нельзя подбросить в
чужую сделку. Qt тут не нужен — ни одна из этих частей его не касается.
"""
import json
import os
import urllib.error
import urllib.request

from pintel_core import phonetest
from pintel_kiosk import phoneweb

HERE = os.path.dirname(os.path.abspath(__file__))


def _всё(ответ=phonetest.ОК):
    return {k: ответ for k in phonetest.КЛЮЧИ}


def test_only_our_keys_and_our_answers_get_through():
    """Страница открыта на телефоне клиента: в посылку и в базу Оценки отсюда не должно
    попасть ничего чужого — ни лишних полей, ни выдуманных ответов."""
    res = phonetest.разобрать({**_всё(), "screen": "сломан", "чужое": "да",
                               "устройство": "iPhone", "заметка": "микрофон на слух"})
    assert set(res) == set(phonetest.КЛЮЧИ) - {"screen"} | {"устройство", "заметка"}
    assert phonetest.разобрать("не словарь") == {} and phonetest.разобрать(None) == {}
    # длинную заметку обрезаем: она уходит в комментарий сделки, а он не резиновый
    длинная = phonetest.разобрать({"заметка": "я" * 1000})
    assert len(длинная["заметка"]) == phonetest.ПРЕДЕЛ_ЗАМЕТКИ


def test_an_unfinished_test_is_not_a_passed_test():
    """Пока ответов нет по всем тестам, тест не пройден: «не проверили» — это неполная
    проверка, а не «в порядке». Без этого шлюз в кассе пропускал бы сделку на полпути."""
    assert phonetest.готов(_всё()) and not phonetest.готов({"sensor": phonetest.ОК})
    assert not phonetest.был({}) and phonetest.был({"sensor": phonetest.ОК})
    частично = {"sensor": phonetest.ОК, "screen": phonetest.ПРОПУСК}
    пропущены = [имя for _, имя in phonetest.пропущенные(частично)]
    assert "Экран" in пропущены and "Сенсор" not in пропущены
    assert len(пропущены) == len(phonetest.КЛЮЧИ) - 1
    # «не проверили» по всем тестам — тоже не пройденный тест
    assert not phonetest.плохие(_всё(phonetest.ПРОПУСК))
    assert len(phonetest.пропущенные(_всё(phonetest.ПРОПУСК))) == len(phonetest.КЛЮЧИ)


def test_the_result_reads_as_one_line_for_the_appraiser():
    """Оценщик видит не «проверено», а по пунктам: что не прошло и что не проверяли."""
    res = {**_всё(), "speaker": phonetest.ПЛОХО, "mic": phonetest.ПРОПУСК,
           "заметка": "микрофон проверен на слух"}
    строка = phonetest.словами(res)
    assert "НЕ ПРОШЛИ: Динамик" in строка and "не проверили: Микрофон" in строка
    assert "микрофон проверен на слух" in строка
    assert phonetest.словами({}) == ""                      # теста не было — молчим


def test_the_page_is_in_the_build_and_speaks_our_keys():
    """Страницу собирает PyInstaller из assets. Если она разойдётся со словарём ключей,
    результат придёт с полями, которых мы не понимаем, и тест молча станет пустым."""
    страница = open(phoneweb.СТРАНИЦА, encoding="utf-8").read()
    for ключ in phonetest.КЛЮЧИ:
        assert ключ in страница, ключ
    for ответ in (phonetest.ОК, phonetest.ПЛОХО, phonetest.ПРОПУСК):
        assert f'"{ответ}"' in страница
    assert "/api/phone/" in страница                        # куда отправлять результат
    assert "capture" in страница                            # камера без HTTPS — только так


def test_the_page_asks_only_after_the_test_and_lets_you_redo_it():
    """Порядок на странице: сначала проверка, потом вопрос — и всегда можно пройти заново.

    Человек не должен отвечать про то, чего ещё не видел: раньше вопрос «звук чистый?» висел
    на экране до того, как мелодия прозвучала, а ответить «переснять» было нечем."""
    страница = open(phoneweb.СТРАНИЦА, encoding="utf-8").read()
    assert "function вопрос(" in страница and "function ответить(" in страница
    assert "Пройти заново" in страница and "__again" in страница
    # обзор в конце: видно весь список и можно повторить любой тест по строке
    assert "function обзор(" in страница and "function повторить(" in страница
    # и с любого теста есть выход: иначе не зазвучавший динамик или не открывшаяся камера
    # останавливают сделку посреди зала
    assert 'id="skip"' in страница and "ответить('skip')" in страница


def test_the_page_plays_sound_through_audio_with_a_type():
    """Звук на iPhone: только <audio> и только с явным типом у Blob — без типа Safari не
    играет вовсе, и кнопка «проиграть» молчала. И отказ play() обязан быть виден словами,
    а не оставлять человека перед вопросом, на который нечего ответить."""
    страница = open(phoneweb.СТРАНИЦА, encoding="utf-8").read()
    assert "function играть(" in страница
    assert 'new Blob(micChunks,{type:тип})' in страница, "запись без типа не проиграется"
    assert "micRec.mimeType" in страница                    # тип берём у самого рекордера
    assert страница.count(".catch(") >= 2                   # и у мелодии, и у записи
    assert "не дал" in страница                             # что сказать, если не вышло


def _поднять():
    phoneweb.остановить()                                   # вдруг остался от прошлого теста
    сервер = phoneweb.запустить(0)                          # 0 — свободный порт выберет система
    assert сервер is not None
    return сервер, сервер.server_address[1]


def _запрос(порт, путь, тело=None):
    url = f"http://127.0.0.1:{порт}{путь}"
    данные = json.dumps(тело).encode() if тело is not None else None
    req = urllib.request.Request(url, data=данные,
                                 headers={"Content-Type": "application/json"} if данные else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def test_the_one_time_link_only_works_for_this_deal():
    """Токен одноразовый, на одну сделку: в той же сети стоят другие телефоны, и подбросить
    результат в чужую сделку они не должны. Закрыли сделку — ссылка больше не открывается."""
    сервер, порт = _поднять()
    try:
        приехало = []
        phoneweb.открыть("KOD111", приехало.append)
        код, тело = _запрос(порт, "/t/KOD111")
        assert код == 200 and "Тест телефона" in тело
        assert _запрос(порт, "/t/OTHER1")[0] == 410          # чужой токен страницу не получает
        assert _запрос(порт, "/api/phone/OTHER1", _всё())[0] == 410
        assert not приехало
        код, _ = _запрос(порт, "/api/phone/KOD111", _всё())
        assert код == 200 and phonetest.готов(phonetest.разобрать(приехало[0]))
        phoneweb.закрыть()
        assert _запрос(порт, "/t/KOD111")[0] == 410          # сделка закрыта
        assert _запрос(порт, "/api/phone/KOD111", _всё())[0] == 410
        assert _запрос(порт, "/ping")[0] == 200              # а живость проверить можно
        assert _запрос(порт, "/etc/passwd")[0] == 404        # больше сервер ничего не отдаёт
    finally:
        phoneweb.остановить()


def test_a_broken_phone_does_not_break_the_kiosk():
    """С телефона может прийти что угодно, в том числе мусор и гигантское тело. Касса
    обязана остаться на ногах: это посреди сделки."""
    сервер, порт = _поднять()
    try:
        приехало = []
        phoneweb.открыть("KOD222", приехало.append)
        assert _запрос(порт, "/api/phone/KOD222", {"мусор": "да"})[0] == 200
        assert phonetest.разобрать(приехало[-1]) == {}        # ничего не поняли — и ничего не взяли
        огромное = {"заметка": "я" * (phoneweb.ПРЕДЕЛ_ТЕЛА + 10)}
        assert _запрос(порт, "/api/phone/KOD222", огромное)[0] == 413
        # приёмник упал — это не повод падать серверу: касса ответит сама
        phoneweb.открыть("KOD333", lambda d: (_ for _ in ()).throw(RuntimeError("окно закрылось")))
        assert _запрос(порт, "/api/phone/KOD333", _всё())[0] == 500
    finally:
        phoneweb.остановить()
