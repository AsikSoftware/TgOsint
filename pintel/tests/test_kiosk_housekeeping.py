# -*- coding: utf-8 -*-
"""Диск на точке: оценка весит около мегабайта, и без уборки его хватает на пару месяцев.

Кончившийся диск останавливает приём совсем — записать очередную оценку будет некуда,
поэтому уборка проверяется тестами, а не «потом посмотрим».
"""
import json
import os
import tempfile
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())

from pintel_kiosk import config as kconfig            # noqa: E402
from pintel_kiosk import worker                        # noqa: E402
from pintel_kiosk.client import Client                 # noqa: E402

ДАВНО = 100 * 86400


@pytest.fixture
def точка(tmp_path, monkeypatch):
    """Свой %LOCALAPPDATA% на тест: трогать настоящую папку киоска нельзя."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for модуль in (worker, kconfig):
        monkeypatch.setattr(модуль, "data_dir", kconfig.data_dir, raising=False)
    d = kconfig.data_dir()
    return d


def _состарить(путь, дней):
    старое = time.time() - дней * 86400
    os.utime(путь, (старое, старое))


def test_old_evaluations_go_but_fresh_ones_stay(точка):
    свежая = os.path.join(точка, "out", "20261028_143512_phone")
    старая = os.path.join(точка, "out", "20260101_101010_phone")
    for d in (свежая, старая):
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "snapshot.json"), "w").write("{}")
    _состарить(старая, 100)
    убрано = worker.убрать_старое(90)
    assert убрано == 1
    assert os.path.isdir(свежая) and not os.path.exists(старая)


def test_references_are_never_touched(точка):
    """Эталоны обезличены, весят 85 КБ и ограничены числом — у них своя жизнь."""
    эталон = os.path.join(точка, "эталоны", "эталон_iPhone-14-Pro_iOS26.5_20260101.zip")
    open(эталон, "wb").write(b"PK")
    _состарить(эталон, 400)
    worker.убрать_старое(90)
    assert os.path.isfile(эталон)


def test_leftover_queue_and_receipts_are_cleaned(точка):
    """Остатки очереди на сервер и старые чеки — такой же мусор, как оценки."""
    хвост = os.path.join(точка, "queue", "phone-abc123.json")
    чек = os.path.join(точка, "out", "чек_7KQ4M.html")
    for p in (хвост, чек):
        open(p, "w").write("x")
        _состарить(p, 120)
    assert worker.убрать_старое(90) == 2
    assert not os.path.exists(хвост) and not os.path.exists(чек)


def test_what_the_server_refused_is_cleaned_too(точка):
    """Отвергнутые сервером оценки лежат в queue/rejected, пока их не разберут. Вечно они
    там лежать не должны: каждая весит как оценка, а диск на точке один."""
    папка = os.path.join(точка, "queue", "rejected")
    os.makedirs(папка, exist_ok=True)
    старая, причина, свежая = (os.path.join(папка, n) for n in ("a-1.json", "a-1.txt", "b-2.json"))
    for p in (старая, причина, свежая):
        open(p, "w").write("x")
    _состарить(старая, 120)
    _состарить(причина, 120)
    assert worker.убрать_старое(90) == 2
    assert os.listdir(папка) == ["b-2.json"]


def test_cleanup_can_be_turned_off(точка):
    старая = os.path.join(точка, "out", "20260101_101010_phone")
    os.makedirs(старая, exist_ok=True)
    _состарить(старая, 999)
    assert worker.убрать_старое(0) == 0
    assert os.path.isdir(старая)


def test_without_a_server_nothing_is_queued(точка):
    """Сервера нет — досылать некуда (flush_queue работает только при настроенном
    сервере), а слепок и отчёт уже лежат в out. Копия по мегабайту на оценку росла бы
    вечно: ровно это и съедало диск."""
    клиент = Client({**kconfig.УМОЛЧАНИЯ, "server": "", "token": ""})
    assert клиент.upload({"client_id": "phone-1", "report": {}, "snapshot": {}}) is None
    assert клиент.queued() == 0

    настроенный = Client({**kconfig.УМОЛЧАНИЯ, "server": "https://x.kz", "token": "pk_1"})
    assert настроенный.upload({"client_id": "phone-2", "report": {}, "snapshot": {}}) is None
    assert настроенный.queued() == 1          # сервер есть, но молчит — копим на досылку


def test_log_does_not_grow_forever(точка, monkeypatch):
    """Лог на точке никто не чистит."""
    monkeypatch.setattr(worker, "ЛОГ_МАКС", 2000)
    for i in range(80):
        worker.log_line("строка " * 10)
    путь = os.path.join(точка, "logs", "kiosk.log")
    assert os.path.getsize(путь) <= 2000 + 200
    assert os.path.isfile(путь + ".1")        # предыдущий кусок рядом, не потерян


def test_a_network_blip_does_not_fill_the_log_with_a_traceback(tmp_path, monkeypatch, capsys):
    """Журнал точки — то, чем мы ищем беды; трассировка на обрыв связи его топит.

    За 10 дней на восьми точках таких трассировок 571, и в них тонуло всё остальное
    (24.11.2026). Обрыв связи — обычная жизнь точки, а не поломка программы: одна строка.
    А вот настоящая ошибка в коде обязана остаться с трассировкой — по ней её и чинят."""
    import os
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    pytest.importorskip("PySide6")
    from pintel_kiosk import app as kapp
    from pintel_kiosk.client import ServerError

    строки = []
    monkeypatch.setattr(kapp, "log_line", lambda s: строки.append(s))

    def прогнать(исключение):
        строки.clear()
        задача = kapp.Task(lambda: (_ for _ in ()).throw(исключение))
        задача.err.connect(lambda _т: None)
        задача.run()
        return "\n".join(строки)

    связь = прогнать(ServerError("нет связи с сервером: ConnectError"))
    assert "Traceback" not in связь and "связь" in связь, связь
    assert len(связь.splitlines()) == 1, связь

    поломка = прогнать(KeyError("опечатка в ключе"))
    assert "Traceback" in поломка, поломка


def test_the_kiosk_updates_itself_without_waiting_for_a_restart(tmp_path, monkeypatch):
    """Владелец, 25.11.2026: «при наличии обновления программа сама всё закрывает и сама
    обновляется — независимо от того, перезапускали софт или нажимали "проверить"».

    До этого спрашивали GitHub один раз, при запуске. Кассу на точке не перезапускают
    неделями, и всё это время она работала на старой сборке: именно так исправленная
    ошибка неделями жила на части точек. Но и посреди сделки программу менять нельзя —
    телефон клиента уже на кабеле, и подмена закрыла бы работу вместе с окном."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from pintel_kiosk import app as kapp
    from pintel_kiosk import config as kconfig

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(kapp.Poller, "run", lambda self: None)
    monkeypatch.setattr(kapp.NetThread, "run", lambda self: None)
    ставили = []
    monkeypatch.setattr(kapp.KioskWindow, "обновиться", lambda self: ставили.append(self.state))
    w = kapp.KioskWindow({**kconfig.УМОЛЧАНИЯ, "server": kconfig.СЕРВЕР, "token": "pk_тест",
                          "point": "16/38 Pintel", "update_repo": ""})
    try:
        assert w.обновление_опрос.isActive(), "про обновление спрашивают только при запуске"
        assert w.обновление_опрос.interval() >= 3 * 60_000

        # нашли сборку, а сотрудник в сделке — ставить нельзя, но и новую работу не начинаем
        w.state = "work"
        w._обновление_найдено({"есть": True, "тег": "doctor-110", "url": "u"})
        assert w.обновление_ставится and ставили == [], "подменили программу посреди сделки"
        w.начать_сделку()
        assert w.state == "work", "начали новую сделку на сборке, которая сейчас сменится"

        # сделка закончилась — ставим сами, никто ничего не нажимал
        w.state = "idle"
        w._ставить_обновление_когда_свободно()
        assert ставили == ["idle"], ставили
    finally:
        for поток in (w.poller, w.net):
            поток.stop()
            поток.wait(2000)
        w.close()
        w.deleteLater()


def test_the_kiosk_installs_the_update_once_and_never_locks_itself(tmp_path, monkeypatch):
    """Обновление ставится РОВНО один раз, а сорвалось — точка работает дальше.

    Скачивание и подмену папки запускают два разных места: опрос раз в 15 минут и кнопка
    «повторить» после неудачи. На пробе оба запускались одновременно: два потока писали в
    один архив и дважды подменяли папку программы. Второй случай страшнее первого: если
    после неудачи отметка «ставим» осталась бы висеть, касса больше не дала бы начать
    сделку — выкуп на точке встал бы из-за моргнувшего интернета."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from pintel_kiosk import app as kapp
    from pintel_kiosk import config as kconfig

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(kapp.Poller, "run", lambda self: None)
    monkeypatch.setattr(kapp.NetThread, "run", lambda self: None)
    качали = []
    monkeypatch.setattr(kapp.KioskWindow, "_run",
                        lambda self, fn, ok=None, err=None: качали.append(fn))
    w = kapp.KioskWindow({**kconfig.УМОЛЧАНИЯ, "server": kconfig.СЕРВЕР, "token": "pk_тест",
                          "point": "16/38 Pintel", "update_repo": "", "update_token": ""})
    try:
        w.state = "idle"
        w.обновление = {"есть": True, "тег": "doctor-999", "url": "u"}
        качали[:] = []                       # запуск программы сам ходит в сеть — не считаем

        # кнопка «повторить» и опрос раз в 15 минут сошлись в одну минуту
        w.обновиться()
        w._обновление_найдено({"есть": True, "тег": "doctor-999", "url": "u"})
        assert len(качали) == 1, "обновление скачивается дважды в один архив"
        w.обновиться()
        assert len(качали) == 1, "обновление скачивается дважды в один архив"

        # сорвалось: интернет моргнул — работаем на этой версии и сделку начать можно
        w._обновление_сорвалось("ConnectError: нет связи")
        assert not w.обновление_ставится and not w.обновление_идёт
        w.начать_сделку()
        assert w.state != "idle", "после неудачного обновления касса не даёт работать"

        # и следующий опрос пробует снова, а не молчит навсегда
        w.state, качали[:] = "idle", []
        w.cfg["update_repo"] = "AsikSoftware/TgOsint"
        w._проверить_обновление()
        assert len(качали) == 1, "после неудачи обновление больше не спрашивают"
    finally:
        for поток in (w.poller, w.net):
            поток.stop()
            поток.wait(2000)
        w.close()
        w.deleteLater()


def _крутить(мс):
    """Дать событиям Qt пройти: ожидание свободной минуты живёт на таймере, и проверять
    его прямым вызовом нельзя — именно так поломка и проскочила мимо тестов."""
    from PySide6.QtCore import QEventLoop, QTimer
    петля = QEventLoop()
    QTimer.singleShot(мс, петля.quit)
    петля.exec()


def _касса_с_обновлением(tmp_path, monkeypatch, ставили):
    """Касса, у которой подмена программы только отмечается, а не делается."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from pintel_kiosk import app as kapp
    from pintel_kiosk import config as kconfig

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(kapp.Poller, "run", lambda self: None)
    monkeypatch.setattr(kapp.NetThread, "run", lambda self: None)
    monkeypatch.setattr(kapp.KioskWindow, "обновиться", lambda self: ставили.append(self.state))
    w = kapp.KioskWindow({**kconfig.УМОЛЧАНИЯ, "server": kconfig.СЕРВЕР, "token": "pk_test",
                          "point": "16/38 Pintel", "update_repo": ""})
    w.обновление_опрос.stop()                    # проверки GitHub в этих тестах не нужны
    w.обновление_жду.setInterval(100)            # ждём свободную минуту быстро
    return w


def _закрыть(w):
    for поток in (w.poller, w.net):
        поток.stop()
        поток.wait(2000)
    w.close()
    w.deleteLater()


def test_the_kiosk_keeps_waiting_for_a_free_minute_and_does_not_freeze(tmp_path, monkeypatch):
    """Касса возвращается к обновлению столько раз, сколько нужно, и ставит его сразу, как
    точка освободилась.

    Эту поломку тест прямым вызовом не видел, а на пробе она вышла сразу: ожидание висело
    на одноразовом таймере, а Qt останавливает такой таймер уже ПОСЛЕ возврата из
    обработчика — перезапуск изнутри него отменяется. Касса один раз смотрела, занята ли
    точка, и больше не возвращалась. Отметка «ставим обновление» при этом оставалась: новую
    сделку начать нельзя, обновление не ставится — точка стоит мёртвой до перезапуска."""
    ставили = []
    w = _касса_с_обновлением(tmp_path, monkeypatch, ставили)
    try:
        w.state = "work"                         # сотрудник в сделке, телефон на кабеле
        w._обновление_найдено({"есть": True, "тег": "doctor-999", "url": "u"})
        _крутить(500)                            # несколько подходов
        assert ставили == [], "подменили программу посреди сделки"
        assert w.обновление_жду.isActive(), "касса больше не вернётся к обновлению"
        assert w.обновление_ставится

        w.state = "idle"                         # сделка закончилась
        _крутить(300)
        assert ставили == ["idle"], ставили
        assert not w.обновление_жду.isActive(), "таймер крутится после установки"
    finally:
        _закрыть(w)


def test_a_late_answer_does_not_wipe_the_update_we_are_installing(tmp_path, monkeypatch):
    """Запоздавший ответ прошлой проверки не стирает найденную сборку.

    Проверок может идти две разом: одна при запуске, вторая кнопкой в меню. Если медленная
    вернётся «нет связи» после быстрой, она обнуляла найденное обновление, а отметка
    «ставим» оставалась — и точка замирала так же насмерть."""
    ставили = []
    w = _касса_с_обновлением(tmp_path, monkeypatch, ставили)
    try:
        w.state = "work"
        w._обновление_найдено({"есть": True, "тег": "doctor-999", "url": "u"})
        w._обновление_найдено({"есть": False, "почему": "нет связи: ConnectError"})
        assert w.обновление and w.обновление_ставится, "потеряли найденную сборку"
        w.state = "idle"
        _крутить(300)
        assert ставили == ["idle"], ставили
    finally:
        _закрыть(w)


def test_the_point_is_never_locked_with_nothing_to_install(tmp_path, monkeypatch):
    """Отметка «ставим обновление» без самого обновления снимается сама.

    Касса, которая не берёт работу и не обновляется, хуже кассы на старой сборке: выкуп
    на точке встанет совсем."""
    ставили = []
    w = _касса_с_обновлением(tmp_path, monkeypatch, ставили)
    try:
        w.обновление, w.обновление_ставится, w.state = None, True, "idle"
        w._ставить_обновление_когда_свободно()
        assert not w.обновление_ставится and not w.обновление_жду.isActive()
        w.начать_сделку()
        assert w.state != "idle", "касса не даёт работать, а обновления нет"
    finally:
        _закрыть(w)


def test_the_update_check_writes_one_line_per_reason_not_per_check(tmp_path, monkeypatch):
    """Проверка каждые 15 минут не засоряет журнал точки.

    Ответ GitHub почти всегда один и тот же — «уже последняя». С восьми касс это 768 строк
    в сутки, а журнал точки читают глазами: в таком шуме тонет настоящая беда. Поэтому в
    журнал идёт смена причины, а не каждая проверка."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from pintel_kiosk import app as kapp
    from pintel_kiosk import config as kconfig

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(kapp.Poller, "run", lambda self: None)
    monkeypatch.setattr(kapp.NetThread, "run", lambda self: None)
    w = kapp.KioskWindow({**kconfig.УМОЛЧАНИЯ, "server": kconfig.СЕРВЕР, "token": "pk_тест",
                          "point": "16/38 Pintel", "update_repo": ""})
    строки = []
    monkeypatch.setattr(kapp, "log_line", lambda s: строки.append(s))
    try:
        for _ in range(4):                   # час работы: четыре проверки, ответ один
            w._обновление_найдено({"есть": False, "почему": "уже последняя"})
        assert len(строки) == 1, строки

        w._обновление_найдено({"есть": False, "почему": "нет связи: ConnectError"})
        assert len(строки) == 2, "новую беду в журнал не написали"
        w._обновление_найдено({"есть": False, "почему": "нет связи: ConnectError"})
        assert len(строки) == 2, строки

        # а вот новую сборку пишем всегда
        w.state = "work"
        w._обновление_найдено({"есть": True, "тег": "doctor-999", "url": "u"})
        assert any("doctor-999" in s for s in строки), строки
    finally:
        for поток in (w.poller, w.net):
            поток.stop()
            поток.wait(2000)
        w.close()
        w.deleteLater()


def test_the_kiosk_obeys_a_command_from_the_server(tmp_path, monkeypatch):
    """«Обновись сейчас» из административной программы доходит до кассы пульсом.

    Пульс — единственное, что касса делает каждую минуту сама; отдельный канал пришлось бы
    держать живым на всех машинах, а этот и так стучится."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from pintel_kiosk import app as kapp
    from pintel_kiosk import config as kconfig

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(kapp.Poller, "run", lambda self: None)
    monkeypatch.setattr(kapp.NetThread, "run", lambda self: None)
    спросили = []
    monkeypatch.setattr(kapp.KioskWindow, "_проверить_обновление",
                        lambda self: спросили.append(True))
    w = kapp.KioskWindow({**kconfig.УМОЛЧАНИЯ, "server": kconfig.СЕРВЕР, "token": "pk_test",
                          "point": "16/38 Pintel", "update_repo": ""})
    try:
        спросили.clear()
        w._команда_с_сервера("обновиться")
        assert спросили, "команда администратора до кассы не дошла"
        w._команда_с_сервера("чего-то непонятного")
        assert len(спросили) == 1, "касса выполнила неизвестную команду"
    finally:
        for поток in (w.poller, w.net):
            поток.stop()
            поток.wait(2000)
        w.close()
        w.deleteLater()


def test_a_closed_kiosk_says_so_and_refuses_new_deals(tmp_path, monkeypatch):
    """Машину закрыли из административной программы — касса говорит об этом словами.

    «Отключён администратором» это не обрыв связи: иначе сотрудник будет перетыкать кабель
    и звонить в поддержку, пока точка стоит."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from pintel_kiosk import app as kapp
    from pintel_kiosk import config as kconfig

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(kapp.Poller, "run", lambda self: None)
    monkeypatch.setattr(kapp.NetThread, "run", lambda self: None)
    w = kapp.KioskWindow({**kconfig.УМОЛЧАНИЯ, "server": kconfig.СЕРВЕР, "token": "pk_test",
                          "point": "16/38 Pintel", "update_repo": ""})
    try:
        w.state = "idle"
        w.on_net(False, "Этот компьютер отключён администратором")
        assert w.закрыты
        w.начать_сделку()
        assert w.state == "idle", "на закрытой кассе начали сделку"

        w.on_net(True, "сервер на связи")
        assert not w.закрыты, "кассу открыли, а она всё ещё считает себя закрытой"
    finally:
        for поток in (w.poller, w.net):
            поток.stop()
            поток.wait(2000)
        w.close()
        w.deleteLater()


def test_the_phone_test_takes_the_next_port_when_its_own_is_busy():
    """Порт теста занят другой программой — берём следующий, а не отказываемся от теста.

    На одной машине у нас живёт не только касса: на маке 8765 держала другая наша
    программа, и тест на телефоне пропадал целиком. Номер порта уезжает в сам QR — телефону
    всё равно, какой он."""
    pytest.importorskip("PySide6")
    import socket

    from pintel_kiosk import phoneweb

    phoneweb.остановить()
    # Порт берём свободный у системы, а не 8765: на машине разработчика его как раз и
    # держит запущенная касса — проверка не должна зависеть от того, что сейчас открыто.
    занятый = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    занятый.bind(("0.0.0.0", 0))
    занятый.listen(1)
    порт = занятый.getsockname()[1]
    try:
        assert phoneweb.запустить(порт) is not None, "тест на телефоне отвалился совсем"
        взяли = phoneweb.текущий_порт()
        assert порт < взяли <= порт + 4, f"взяли порт {взяли}, ожидали следующий за {порт}"
        assert str(взяли) in phoneweb.ссылка("кодкод", взяли)
    finally:
        phoneweb.остановить()
        занятый.close()
