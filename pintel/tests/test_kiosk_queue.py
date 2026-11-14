# -*- coding: utf-8 -*-
"""Очередь досылки оценок на сервер.

Со 02.11 по 13.11.2026 касса точки 2 раз в минуту слала одну и ту же оценку и 630 раз получила
от сервера 500. Сервер был неправ (см. test_server.py), но и касса вела себя плохо:

* слала отвергнутое вечно, раз в минуту, и ни в журнале, ни на экране об этом не было ни слова;
* на первой же неудаче бросала очередь — оценка, которую не берут, запирала все, что за ней.
"""
import json
import os

import httpx
import pytest

from pintel_kiosk import client as kclient
from pintel_kiosk import config as kconfig


class Сервер:
    """Подменный httpx.Client: на оценку отвечает по её client_id."""
    ответы = {}          # client_id → (код, тело) | исключение
    запросы = []

    def __init__(self, base_url="", timeout=None, headers=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def request(self, method, path, **kw):
        cid = (kw.get("json") or {}).get("client_id")
        Сервер.запросы.append(cid)
        ответ = Сервер.ответы.get(cid, (200, {"id": 1}))
        if isinstance(ответ, Exception):
            raise ответ
        код, тело = ответ
        return httpx.Response(код, json=тело) if isinstance(тело, dict) else httpx.Response(код, text=тело)


@pytest.fixture
def касса(tmp_path, monkeypatch):
    for sub in ("queue", "cache"):
        os.makedirs(tmp_path / sub, exist_ok=True)
    monkeypatch.setattr(kclient, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(kclient.httpx, "Client", Сервер)
    Сервер.ответы, Сервер.запросы = {}, []
    c = kclient.Client({**kconfig.УМОЛЧАНИЯ, "server": kconfig.СЕРВЕР, "token": "pk_точка"})
    c.журнал = []
    c.log = c.журнал.append
    c.время = 1000.0
    c._часы = lambda: c.время
    return c


def положить(касса, *имена):
    for cid in имена:
        with open(os.path.join(касса.qdir, f"{cid}.json"), "w", encoding="utf-8") as f:
            json.dump({"client_id": cid, "report": {"паспорт": {}}, "snapshot": {}}, f)


def в_очереди(касса):
    return sorted(n[:-5] for n in os.listdir(касса.qdir) if n.endswith(".json"))


def отложено(касса):
    папка = os.path.join(касса.qdir, "rejected")
    return sorted(n[:-5] for n in os.listdir(папка) if n.endswith(".json")) if os.path.isdir(папка) else []


ОТКАЗ = (422, {"detail": "оценка не принята: поле не помещается в базу (value too long)"})


def test_what_the_server_refused_for_good_is_not_sent_again(касса):
    """Сервер разобрал оценку и отказал по содержимому (4xx) — второй раз он ответит то же.
    Оценку откладываем в сторону, целиком и с причиной: данные не теряются, но и в очереди
    она больше не стоит, а в журнале точки (он уходит на сервер) остаётся строка."""
    положить(касса, "aaa-000000000001")
    Сервер.ответы["aaa-000000000001"] = ОТКАЗ
    assert касса.flush_queue() == 0
    assert в_очереди(касса) == [] and отложено(касса) == ["aaa-000000000001"]
    assert касса.queued() == 0 and касса.rejected() == 1
    причина = open(os.path.join(касса.qdir, "rejected", "aaa-000000000001.txt"), encoding="utf-8").read()
    assert "422" in причина and "не помещается в базу" in причина
    assert len(касса.журнал) == 1 and "не принял" in касса.журнал[0] and "422" in касса.журнал[0]
    assert "aaa" not in касса.журнал[0]            # в имени файла серийник — в журнал только хвост
    # дальше — тишина: ни запросов, ни новых строк
    for _ in range(5):
        касса.время += 3600
        assert касса.flush_queue() == 0
    assert Сервер.запросы == ["aaa-000000000001"] and len(касса.журнал) == 1


def test_one_refused_evaluation_does_not_hold_the_rest(касса):
    """Раньше на первой неудаче очередь бросали: файлы идут по алфавиту, и оценка, которую
    сервер не берёт, навсегда запирала все, что стоят за ней."""
    положить(касса, "aaa-000000000001", "bbb-000000000002", "ccc-000000000003")
    Сервер.ответы["aaa-000000000001"] = ОТКАЗ
    Сервер.ответы["bbb-000000000002"] = (500, "Internal Server Error")
    assert касса.flush_queue() == 1
    assert Сервер.запросы == ["aaa-000000000001", "bbb-000000000002", "ccc-000000000003"]
    assert в_очереди(касса) == ["bbb-000000000002"] and отложено(касса) == ["aaa-000000000001"]


def test_a_broken_server_is_not_hammered_every_minute(касса):
    """500 — это сервер сломан, а не оценка плоха: её починят вместе с ним, поэтому из
    очереди она не уходит. Но и стучать раз в минуту незачем: пауза растёт вдвое, до часа.
    Так вместо 1400 запросов в сутки выходит около тридцати, и каждый — со строкой в журнале."""
    положить(касса, "bbb-000000000002")
    Сервер.ответы["bbb-000000000002"] = (500, "Internal Server Error")
    попытки = []
    for минута in range(24 * 60):
        if касса.flush_queue() or len(Сервер.запросы) > len(попытки):
            попытки.append(минута)
        касса.время += 60
    assert попытки[:6] == [0, 2, 6, 14, 30, 62]                   # 2, 4, 8, 16, 32 минуты…
    assert попытки[6] - попытки[5] == 60 and len(попытки) < 32    # …и дальше раз в час
    assert в_очереди(касса) == ["bbb-000000000002"] and отложено(касса) == []
    assert len(касса.журнал) == len(попытки) and "500" in касса.журнал[0]

    # сервер починили — оценка уходит со следующей попытки, паузы больше нет
    Сервер.ответы["bbb-000000000002"] = (200, {"id": 7})
    касса.время += 3600
    assert касса.flush_queue() == 1 and в_очереди(касса) == []
    assert касса._отложено == {}


def test_no_link_and_a_wrong_token_keep_everything_in_place(касса):
    """Нет связи или токен точки отозван — так будет с каждой оценкой, и ни одна из них в
    этом не виновата: очередь стоит как стояла, без пауз и без «отвергнуто»."""
    положить(касса, "aaa-000000000001", "bbb-000000000002")
    Сервер.ответы["aaa-000000000001"] = httpx.ConnectError("нет сети")
    assert касса.flush_queue() == 0
    Сервер.ответы["aaa-000000000001"] = (401, {"detail": "Точка отключена администратором"})
    assert касса.flush_queue() == 0
    assert Сервер.запросы == ["aaa-000000000001"] * 2              # до второй не доходили
    assert в_очереди(касса) == ["aaa-000000000001", "bbb-000000000002"] and отложено(касса) == []
    assert касса._отложено == {}
    Сервер.ответы.clear()
    assert касса.flush_queue() == 2 and в_очереди(касса) == []


def test_a_fresh_evaluation_the_server_refuses_never_enters_the_queue(касса):
    """Тот же отказ на первой отправке, прямо из проверки: в очередь такая оценка не
    ложится вовсе. Проверке при этом говорим, что случилось, — «отправим позже» было бы
    неправдой."""
    Сервер.ответы["ddd-000000000004"] = ОТКАЗ
    assert касса.upload({"client_id": "ddd-000000000004", "report": {}, "snapshot": {}}) is None
    assert в_очереди(касса) == [] and отложено(касса) == ["ddd-000000000004"]
    assert "422" in касса.отвергнуто

    # а сломанный сервер и обрыв связи — по-прежнему в очередь, и это не «отвергнуто»
    Сервер.ответы["eee-000000000005"] = (500, "Internal Server Error")
    Сервер.ответы["fff-000000000006"] = httpx.ConnectError("нет сети")
    for cid in ("eee-000000000005", "fff-000000000006"):
        assert касса.upload({"client_id": cid, "report": {}, "snapshot": {}}) is None
        assert касса.отвергнуто == ""
    assert в_очереди(касса) == ["eee-000000000005", "fff-000000000006"]
    Сервер.ответы["ggg-000000000007"] = (200, {"id": 9})
    assert касса.upload({"client_id": "ggg-000000000007", "report": {}, "snapshot": {}}) == {"id": 9}


def test_a_page_instead_of_an_answer_is_not_a_delivery(касса):
    """Гостевой Wi-Fi отвечает на всё своей страницей входа с кодом 200. Это не ответ
    сервера: оценку не считаем ни доставленной, ни битой — она ждёт в очереди."""
    положить(касса, "aaa-000000000001")
    Сервер.ответы["aaa-000000000001"] = (200, "<html>Войдите в сеть</html>")
    assert касса.flush_queue() == 0
    assert в_очереди(касса) == ["aaa-000000000001"]
    assert not [n for n in os.listdir(касса.qdir) if n.endswith(".bad")]
    # а вот файл, который не читается сам, по-прежнему убираем с дороги
    with open(os.path.join(касса.qdir, "000-битый.json"), "w", encoding="utf-8") as f:
        f.write("{не json")
    Сервер.ответы.clear()
    assert касса.flush_queue() == 1
    assert "000-битый.json.bad" in os.listdir(касса.qdir) and в_очереди(касса) == []
