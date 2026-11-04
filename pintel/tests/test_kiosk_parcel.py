# -*- coding: utf-8 -*-
"""Сделка из таблицы обмена: бот забирает посылку сам, без кнопки.

Зачем это проверять отдельно. Раньше сделку создавало нажатие кнопки под карточкой в
Telegram — за ним стоял человек, и он же видел отказ. Теперь её создаёт бот, по таблице,
молча: посылку туда кладёт наш сервер. Значит, ошибиться стало некому и некому заметить,
а цена ошибки прежняя — сделка на чужой телефон либо две сделки на один.

Обработчик лежит в `deploy/оценка_бот/` и ставится на сервер руками, рядом с кодом Оценки,
которого здесь нет. Поэтому `aiogram` и её базу подменяем: проверяется не Telegram, а
порядок работы с посылкой — взять ровно один раз, не потерять причину отказа, сказать
сотруднику номер сделки.
"""
import asyncio
import importlib.util
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ФАЙЛ = os.path.join(HERE, "..", "deploy", "оценка_бот", "kiosk_media.py")


class Пустышка:
    """Любой вызов и любое обращение возвращают её же: так выглядит `F` из aiogram."""

    def __call__(self, *a, **k):
        return self

    def __getattr__(self, _):
        return self

    def __or__(self, _):
        return self


def _фальшивый_aiogram(monkeypatch):
    """Ровно столько aiogram, сколько нужно, чтобы модуль обработчика импортировался."""
    пусто = Пустышка()

    class Router:
        def __init__(self, *a, **k):
            pass

        def message(self, *a, **k):
            return lambda f: f

        def callback_query(self, *a, **k):
            return lambda f: f

        def startup(self, *a, **k):
            return lambda f: f

    aiogram = types.ModuleType("aiogram")
    aiogram.Bot, aiogram.Router, aiogram.F = type("Bot", (), {}), Router, пусто
    for имя, модуль in {
        "aiogram": aiogram,
        "aiogram.fsm": types.ModuleType("aiogram.fsm"),
        "aiogram.fsm.context": types.ModuleType("aiogram.fsm.context"),
        "aiogram.fsm.state": types.ModuleType("aiogram.fsm.state"),
        "aiogram.types": types.ModuleType("aiogram.types"),
        "aiogram.utils": types.ModuleType("aiogram.utils"),
        "aiogram.utils.keyboard": types.ModuleType("aiogram.utils.keyboard"),
    }.items():
        monkeypatch.setitem(sys.modules, имя, модуль)
    sys.modules["aiogram.fsm.context"].FSMContext = type("FSMContext", (), {})
    sys.modules["aiogram.fsm.state"].State = lambda *a, **k: None
    sys.modules["aiogram.fsm.state"].StatesGroup = type("StatesGroup", (), {})
    for имя in ("CallbackQuery", "Message"):
        setattr(sys.modules["aiogram.types"], имя, type(имя, (), {}))
    sys.modules["aiogram.utils.keyboard"].InlineKeyboardBuilder = type(
        "InlineKeyboardBuilder", (), {})


class Сессия:
    """Подменная сессия: помнит запросы и отдаёт заготовленные ответы."""

    def __init__(self, журнал, ответы):
        self.журнал, self.ответы = журнал, ответы

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, запрос, параметры=None):
        текст = " ".join(str(запрос).split())
        self.журнал.append((текст, dict(параметры or {})))
        ответ = self.ответы(текст, параметры or {})
        return types.SimpleNamespace(scalar=lambda: ответ,
                                     mappings=lambda: types.SimpleNamespace(first=lambda: ответ))

    async def commit(self):
        pass


@pytest.fixture
def бот_модуль(monkeypatch):
    """Модуль обработчика с подменёнными aiogram и базой."""
    _фальшивый_aiogram(monkeypatch)
    engine = types.ModuleType("database.engine")
    database = types.ModuleType("database")
    database.engine = engine
    monkeypatch.setitem(sys.modules, "database", database)
    monkeypatch.setitem(sys.modules, "database.engine", engine)
    engine.async_session_factory = lambda: Сессия([], lambda *a: None)

    # `kiosk_core` лежит рядом с обработчиком — на сервере они соседи в handlers/
    monkeypatch.syspath_prepend(os.path.dirname(ФАЙЛ))
    spec = importlib.util.spec_from_file_location("kiosk_media_под_тестом", ФАЙЛ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class ФейкБот:
    def __init__(self):
        self.письма = []

    async def send_message(self, chat_id=None, text=None, **k):
        self.письма.append((chat_id, text))


ПОСЫЛКА = '{"версия": 1, "код": "ABCD12", "сделка": {"model": "iPhone 14 Pro"}}'
СТРОКА = {"code": "ABCD12", "chat_id": 777, "user_id": 5, "shop_id": 14, "device_id": None,
          "photos": "f1||f2||f3", "video": "v1", "checks": None}


def _подменить(м, monkeypatch, *, взято=ПОСЫЛКА, сделка=None, падать=None):
    """Посылка лежит, строка обмена такая-то, а создание сделки — заготовлено."""
    беды, созданы = [], []

    async def взять(код):
        return взято

    async def строка(код):
        return dict(СТРОКА)

    async def беда(код, почему):
        беды.append((код, почему))

    async def создать(bot, код, посылка, стр, нажал=None):
        созданы.append(код)
        if падать is not None:
            raise падать
        return (сделка or {"id": 7311, "цена": 185000, "оценщик": "Асылбек",
                           "точка": "16/38 Pintel"}), "карточка у оценщика в личке"

    monkeypatch.setattr(м, "_взять", взять)
    monkeypatch.setattr(м, "_строка", строка)
    monkeypatch.setattr(м, "_сказать_о_беде", беда)
    monkeypatch.setattr(м, "_создать", создать)
    return беды, созданы


def test_the_parcel_becomes_a_deal_and_the_employee_is_told(бот_модуль, monkeypatch):
    """Посылка превращается в сделку, а сотрудник узнаёт её номер.

    Сообщение идёт в тот чат, из которого пришли фото и видео: сотрудник только что им
    пользовался, значит оно дойдёт. Рабочей группы у бота может не быть вовсе — именно на
    ней всё и встало в прошлый раз («bot was blocked by the user»)."""
    беды, созданы = _подменить(бот_модуль, monkeypatch)
    бот = ФейкБот()
    asyncio.run(бот_модуль._обработать_посылку(бот, "ABCD12"))
    assert созданы == ["ABCD12"] and беды == []
    чат, текст = бот.письма[0]
    assert чат == 777 and "7311" in текст and "185 000" in текст


def test_a_parcel_taken_by_someone_else_is_not_taken_twice(бот_модуль, monkeypatch):
    """Пустой ответ на «забрать» значит, что посылку уже взяли, — и сделки больше нет.

    Замок один и тот же UPDATE: второй заход по тому же коду ничего не находит. Две
    сделки на один телефон дороже, чем потерянная посылка: потерянную отправят заново."""
    беды, созданы = _подменить(бот_модуль, monkeypatch, взято=None)
    asyncio.run(бот_модуль._обработать_посылку(ФейкБот(), "ABCD12"))
    assert созданы == [] and беды == []


def test_why_the_deal_failed_is_written_down_where_the_point_can_see_it(бот_модуль, monkeypatch):
    """Сделка не создалась — причина ложится в строку обмена, и касса показывает её.

    Иначе на экране остаётся «отправлено», сотрудник ждёт номера, а номера не будет."""
    беды, _ = _подменить(бот_модуль, monkeypatch,
                         падать=бот_модуль.kiosk_core.ОшибкаПосылки("в посылке нет кода"))
    asyncio.run(бот_модуль._обработать_посылку(ФейкБот(), "ABCD12"))
    assert беды == [("ABCD12", "в посылке нет кода")]

    # и любая другая поломка тоже: молча терять сделку нельзя
    беды, _ = _подменить(бот_модуль, monkeypatch, падать=RuntimeError("база отвалилась"))
    asyncio.run(бот_модуль._обработать_посылку(ФейкБот(), "ABCD12"))
    assert беды and "база отвалилась" in беды[0][1]


def test_the_deal_is_still_made_when_the_employee_cannot_be_reached(бот_модуль, monkeypatch):
    """Сообщение сотруднику не ушло — сделка всё равно создана и остаётся в Оценке.

    Карточка оценщику уходит отдельно (`_позвать_дальше`), и падение на последнем шаге не
    должно выглядеть как несозданная сделка: иначе её отправят второй раз."""
    беды, созданы = _подменить(бот_модуль, monkeypatch)

    class Немой(ФейкБот):
        async def send_message(self, **k):
            raise RuntimeError("Forbidden: bot was blocked by the user")

    asyncio.run(бот_модуль._обработать_посылку(Немой(), "ABCD12"))
    assert созданы == ["ABCD12"] and беды == []


def test_the_claim_is_one_query_and_leaves_nothing_behind(бот_модуль, monkeypatch):
    """«Забрать себе» — один запрос: он же и замок, и очистка прошлой ошибки."""
    журнал = []
    monkeypatch.setattr(бот_модуль, "async_session_factory",
                        lambda: Сессия(журнал, lambda т, п: ПОСЫЛКА))
    assert asyncio.run(бот_модуль._взять("ABCD12")) == ПОСЫЛКА
    запрос = журнал[0][0]
    assert запрос.startswith("UPDATE kiosk_media SET parcel = NULL")
    assert "parcel_error = NULL" in запрос, "старая ошибка не должна пережить новую посылку"
    assert "parcel IS NOT NULL" in запрос and "device_id IS NULL" in запрос
    assert "RETURNING parcel" in запрос
