# -*- coding: utf-8 -*-
"""Проверка подлинности Apple по кабелю: вердикт есть без экрана телефона.

24.11.2026, iPhone 14 на iOS 16.5.1: касса висела на «ждём историю Apple» без конца —
вердикт мы брали только из журнала, а журнал телефон печатает лишь после того, как человек
зайдёт в раздел на телефоне. Сам телефон читает ту же проверку из своего IORegistry
(`mobilerepaird: [Battery] … IOREG Auth Component Trusted`), и по кабелю она читается за
0,04 с. Поля ниже сняты с живого аппарата.
"""
from pintel_core.analysis import authcp, parts

# Узел AppleAuthCPRelay, как его отдал живой iPhone 14 (iOS 16.5.1) 24.11.2026.
ЖИВОЙ = {"AuthPassed": True, "AuthFullPass": True, "isTrusted": True, "isTrustedForUI": True,
         "authError": 0, "authErrorDescription": "AuthSuccess", "FdrValidationStatus": "Pass",
         "InternalComponent": True, "IOClass": "AppleAuthCPRelay", "flags": 65544}
# Узел шины аксессуаров того же аппарата: это разъём, а не аккумулятор.
АКСЕССУАР = {**ЖИВОЙ, "IOClass": "AppleAuthCPAID", "flags": 196608,
             "IOAccessoryIDBusTransportInternalAuth": True, "AuthCPPID": 1, "AuthCPVID": 4,
             "AccessoryCertificateSerialNumber": "0" * 32}

ЧИСТЫЕ_СИГНАЛЫ = {"Face ID ↔ плата": {"ок": True, "почему": "сошлась"},
                  "Экран: калибровка": {"ок": True, "почему": "сошлась"}}


def вердикт(узлы, battery=None):
    snap = {"nodes": dict(узлы)}
    бат = battery if battery is not None else {"есть_данные": True, "подделка": []}
    return parts.verdict(snap, ЧИСТЫЕ_СИГНАЛЫ, {}, бат, {}, {}, apple_supported=True)


def деталь(в, ключ):
    return next((d for d in в["детали"] if d["ключ"] == ключ), None)


def test_the_phone_confirms_its_battery_over_the_cable():
    """Аккумулятор подтверждает сама Apple, и для этого не нужен ни экран, ни человек."""
    итог = authcp.разобрать({"AppleAuthCPRelay": ЖИВОЙ})
    assert итог["аккумулятор"]["доверена"] is True and итог["прочитано"] == 1
    assert "подтвердила Apple" in authcp.словами(итог)

    в = вердикт({"AppleAuthCPRelay": ЖИВОЙ})
    бат = деталь(в, "Battery")
    assert бат["статус"] == "ok" and "проверка Apple" in бат["источник"]
    assert в["каналы"]["проверка_apple_кабель"] == 1


def test_a_battery_apple_does_not_trust_stops_the_deal():
    """isTrusted = 0 — это замена или неоригинал: СТОП, и сказано, что так решила Apple."""
    плохой = {**ЖИВОЙ, "isTrusted": False, "isTrustedForUI": False,
              "authError": 5, "authErrorDescription": "AuthFailed"}
    итог = authcp.разобрать({"AppleAuthCPRelay": плохой})
    assert итог["аккумулятор"]["доверена"] is False
    assert "AuthFailed" in итог["аккумулятор"]["почему"]

    в = вердикт({"AppleAuthCPRelay": плохой})
    assert в["итог"] == "замена"
    assert "Apple" in parts.причина_отказа(в) and "ккумулятор" in parts.причина_отказа(в)


def test_an_error_code_is_a_refusal_even_with_the_flags_set():
    """Ошибка подписи важнее флагов: телефон мог оставить isTrusted, но подпись не сошлась."""
    спорный = {**ЖИВОЙ, "authError": 3, "authErrorDescription": ""}
    assert authcp.разобрать({"AppleAuthCPRelay": спорный})["аккумулятор"]["доверена"] is False


def test_the_accessory_coprocessor_is_never_taken_for_the_battery():
    """У разъёма свой сопроцессор. Выдать его проверку за аккумулятор — врать клиенту."""
    итог = authcp.разобрать({"AppleAuthCPRelay": АКСЕССУАР, "AppleAuthCPAID": АКСЕССУАР})
    assert итог["аккумулятор"]["доверена"] is None
    assert "аксессуар" in итог["аккумулятор"]["почему"]
    assert деталь(вердикт({"AppleAuthCPRelay": АКСЕССУАР}), "Battery")["источник"] != "проверка Apple"
    # сам аксессуар при этом прочитан и сохранён — он поедет в эталон и в отчёт
    assert [а["узел"] for а in итог["аксессуары"]] == ["AppleAuthCPAID"]


def test_nothing_read_is_not_a_verdict():
    """Узла нет или в нём нет главных полей — это «не прочиталось», а не «всё хорошо»."""
    for узлы in ({}, {"AppleAuthCPRelay": None}, {"AppleAuthCPRelay": {}},
                 {"AppleAuthCPRelay": {"IOClass": "AppleAuthCPRelay", "flags": 1}}):
        итог = authcp.разобрать(узлы)
        assert итог["аккумулятор"]["доверена"] is None, узлы
        assert итог["прочитано"] == 0
        assert authcp.словами(итог) == ""
        assert деталь(вердикт(узлы), "Battery")["источник"] == "батарея (кабель)"


def test_the_screen_says_what_apple_already_confirmed():
    """Пока Apple не подтвердила аппарат целиком, сотрудник обязан видеть, что именно
    осталось сверить. Прежняя строка говорила «подлинность деталей не подтверждена» и
    отправляла сверять на телефоне то, что телефон уже подтвердил сам."""
    в = вердикт({"AppleAuthCPRelay": ЖИВОЙ})
    assert в["итог"] == "кабель" and в["apple_подтверждено"] is False
    assert "Apple по кабелю подтвердила: Аккумулятор" in в["почему"]


def test_one_battery_does_not_make_the_whole_phone_green():
    """Экран и камеры этот канал не проверяет: их сопроцессоры по кабелю не достать.
    Зелёный на весь аппарат по одному аккумулятору — ровно та ошибка, из-за которой
    пересаженный оригинальный экран прошёл бы как родной."""
    в = вердикт({"AppleAuthCPRelay": ЖИВОЙ})
    assert в["apple_подтверждено"] is False and в["итог"] != "родные"
