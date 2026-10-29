# -*- coding: utf-8 -*-
"""Реестр IMEI РФС РК: разбор ответа сайта, кэш на точке и слова для экрана.

Сайт отдаёт HTML, красит красным и «не верифицирован», сверяет 14 цифр из 15 и не терпит
параллельных запросов — всё это проверено на боевом объёме (2500+ IMEI) и закреплено здесь,
чтобы правка разбора не вернула старые ошибки.
"""
import pytest

from pintel_core.external import rfs


def _ок(imei, вердикт, срок=None):
    return {"imei": imei, "verdict": вердикт, "status_text": rfs.STATUS_TEXT[вердикт],
            "deadline": срок, "text": "…", "ok": True}


@pytest.mark.parametrize("html,ждём,срок", [
    ('<div class="alert alert-success">IMEI 35366585205961 верифицирован</div>', rfs.VERIFIED, None),
    # красный alert — и всё же НЕ блокировка: вердикт по тексту
    ('<div class="alert alert-danger">IMEI не верифицирован.<br>Временный доступ до 31.12.2026</div>',
     rfs.NOT_VERIFIED, "31.12.2026"),
    ('<div class="alert alert-danger">IMEI заблокирован</div>', rfs.BLOCKED, None),
    ('<div class="alert alert-success">Устройство зарегистрировано, не заблокировано</div>', rfs.VERIFIED, None),
    ('<div class="alert alert-info">Нет данных</div>', rfs.UNKNOWN, None),
])
def test_verdict_is_read_from_text_not_colour(html, ждём, срок):
    вердикт, текст, дедлайн = rfs.analyze({"raw": html})
    assert вердикт == ждём and дедлайн == срок
    assert "<" not in текст                          # экрану отдаём чистый текст


def test_json_answer_is_understood_too():
    """Запас на случай, если реестр однажды отдаст нормальный JSON."""
    assert rfs.analyze({"data": {"verified": False}})[0] == rfs.NOT_VERIFIED
    assert rfs.analyze({"result": {"status": "blocked"}})[0] == rfs.BLOCKED


@pytest.mark.parametrize("вход,ждём", [
    ("353665852059610", "35366585205961"), ("35366585205961", "35366585205961"),
    ("353 665 852 059 610", "35366585205961"), ("3536", ""), ("", ""), (None, ""),
])
def test_registry_checks_fourteen_digits(вход, ждём):
    """Реестр сверяет первые 14 цифр — 15-я контрольная. Обрезаем сами."""
    assert rfs.imei14(вход) == ждём


def test_short_imei_fails_without_touching_the_network():
    r = rfs.check_imei("123")
    assert r["ok"] is False and r["verdict"] == rfs.UNKNOWN and "14" in r["text"]


def test_check_is_sequential_dedups_and_caches(monkeypatch, tmp_path):
    """Сервер держит один запрос в секунду — проверяем по одному; пустые и повторы не
    считаем; удачный ответ лежит в кэше, неудача — нет (следующий раз спросим снова)."""
    вызовы = []

    def фейк(imei, timeout=rfs.HTTP_TIMEOUT, retries=rfs.RETRIES, proxy=None):
        вызовы.append(imei)
        if imei.endswith("1"):
            return _ок(imei, rfs.VERIFIED)
        return rfs._fail(imei, "HTTP 503")

    monkeypatch.setattr(rfs, "check_imei", фейк)
    monkeypatch.setattr(rfs.time, "sleep", lambda s: None)
    r1 = rfs.проверить(["350585886690251", "350585881725180", "", "350585886690251"], cache_dir=str(tmp_path))
    assert [x["imei"] for x in r1] == ["350585886690251", "350585881725180"]
    assert r1[0]["ok"] and r1[0]["из_кэша"] is False and not r1[1]["ok"]
    assert вызовы == ["350585886690251", "350585881725180", "350585881725180"]   # упавший — ещё один проход
    вызовы.clear()
    r2 = rfs.проверить(["350585886690251", "350585881725180"], cache_dir=str(tmp_path))
    assert r2[0]["из_кэша"] is True and r2[0]["verdict"] == rfs.VERIFIED
    assert вызовы == ["350585881725180", "350585881725180"]                      # удачный из кэша, упавший — снова


def test_stale_cache_is_asked_again(monkeypatch, tmp_path):
    import os, time
    monkeypatch.setattr(rfs, "check_imei", lambda imei, **kw: _ок(imei, rfs.VERIFIED))
    monkeypatch.setattr(rfs.time, "sleep", lambda s: None)
    rfs.проверить(["350585886690251"], cache_dir=str(tmp_path))
    файл = os.path.join(str(tmp_path), "35058588669025.json")
    os.utime(файл, (time.time() - 48 * 3600, time.time() - 48 * 3600))
    assert rfs.проверить(["350585886690251"], cache_dir=str(tmp_path))[0]["из_кэша"] is False


@pytest.mark.parametrize("r,ждём", [
    (_ок("1", rfs.VERIFIED), "верифицирован"),
    (_ок("1", rfs.NOT_VERIFIED, "31.12.2026"), "не верифицирован (временный доступ до 31.12.2026)"),
    (_ок("1", rfs.NOT_VERIFIED), "не верифицирован"),
    (_ок("1", rfs.BLOCKED), "ЗАБЛОКИРОВАН"),
    (rfs._fail("1", "HTTP 503"), "реестр не ответил"),
    ({}, "реестр не ответил"),
])
def test_words_for_the_screen(r, ждём):
    assert rfs.словами(r) == ждём


def test_summary_takes_the_worst_imei():
    """Два IMEI — один вердикт на аппарат: худший решает."""
    assert rfs.сводка([_ок("a", rfs.VERIFIED), _ок("b", rfs.BLOCKED)])["вердикт"] == rfs.BLOCKED
    св = rfs.сводка([_ок("a", rfs.VERIFIED), _ок("b", rfs.NOT_VERIFIED, "31.12.2026")])
    assert св["вердикт"] == rfs.NOT_VERIFIED and св["срок"] == "31.12.2026" and len(св["строки"]) == 2
    assert rfs.сводка([_ок("a", rfs.VERIFIED), rfs._fail("b", "x")])["вердикт"] == rfs.UNKNOWN
    assert rfs.сводка([_ок("a", rfs.VERIFIED)])["вердикт"] == rfs.VERIFIED
    assert rfs.сводка([])["вердикт"] is None


def test_report_lines_blocked_is_stop_unverified_is_warning_silence_is_unknown():
    """Заблокирован — стоп. Не верифицирован — предупреждение со сроком. Реестр молчит —
    отсутствие данных, а не вердикт: честного клиента за это не обвиняем."""
    стоп, внимание, нет = rfs.в_отчёт([_ок("350585886690250", rfs.BLOCKED),
                                      _ок("350585881725184", rfs.NOT_VERIFIED, "31.12.2026"),
                                      rfs._fail("350585881725185", "HTTP 503")])
    assert стоп == ["IMEI 350585886690250 заблокирован в реестре РФС РК"]
    assert внимание == ["IMEI 350585881725184 не верифицирован в реестре РФС РК — временный доступ до 31.12.2026"]
    assert нет and "350585881725185" in нет[0]
    assert rfs.в_отчёт([_ок("a", rfs.VERIFIED)]) == ([], [], [])
