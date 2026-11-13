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

    def begin(self):
        return self                       # `async with session.begin()` — тот же объект

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


def test_the_parcel_is_locked_read_and_only_then_cleared(бот_модуль, monkeypatch):
    """«Забрать себе» — запереть строку, прочитать посылку и очистить её в той же транзакции.

    Одним `UPDATE … RETURNING parcel` это не делается, хотя и просится: Postgres отдаёт в
    RETURNING **новое** значение, то есть уже очищенное. Ровно так и было написано
    сначала — на тестовом контуре посылки исчезали, сделки не появлялись, а в журнале
    было пусто. Поэтому здесь проверяется сам порядок: сначала чтение под замком, потом
    очистка.
    """
    журнал = []
    monkeypatch.setattr(бот_модуль, "async_session_factory",
                        lambda: Сессия(журнал, lambda т, п: ПОСЫЛКА if т.startswith("SELECT") else None))
    assert asyncio.run(бот_модуль._взять("ABCD12")) == ПОСЫЛКА
    читаем, чистим = журнал[0][0], журнал[1][0]
    assert читаем.startswith("SELECT parcel FROM kiosk_media") and читаем.endswith("FOR UPDATE")
    assert "parcel IS NOT NULL" in читаем and "device_id IS NULL" in читаем
    assert чистим.startswith("UPDATE kiosk_media SET parcel = NULL")
    assert "parcel_error = NULL" in чистим, "старая ошибка не должна пережить новую посылку"

    # посылки нет — и чистить нечего: лишний UPDATE затёр бы чужую ошибку
    журнал.clear()
    monkeypatch.setattr(бот_модуль, "async_session_factory",
                        lambda: Сессия(журнал, lambda т, п: None))
    assert asyncio.run(бот_модуль._взять("ABCD12")) is None
    assert len(журнал) == 1


# ---------------------------------------------------------------- порядок с 12.11.2026:
# привязка в начале, цена до сделки, медиа — после «Отправить на оценку»

ПОЛНАЯ = {
    "версия": 1, "код": "ABCD12", "shop_id": 14, "точка": "16/38 Pintel",
    "клиент": {"имя": "Арман", "телефон": "+77051234567"}, "imei": ["356789012345678"],
    "сделка": {"model": "iPhone 13", "ddr": 128, "akb": "75-79", "akb_exact": 75,
               "akb_cycles": 1810, "sim": "Стандарт", "phone_status": "Не был в ремонте"},
    "ручная_диагностика": {"keys": True, "vibro": True, "sim": True, "glue": True,
                           "wifi": True, "charge": True, "apple": True, "body": True},
    "тест_телефона": {"sensor": "ok", "multitouch": "ok", "screen": "ok", "speaker": "ok",
                      "mic": "ok", "camera_back": "ok", "camera_front": "ok"},
}


def _полная(м, **замены):
    """Посылка, которой для сделки не хватает только медиа. Ключи ручной диагностики берём у
    самого обработчика: список пунктов живёт в kiosk_core и может меняться."""
    п = __import__("copy").deepcopy(ПОЛНАЯ)
    п["ручная_диагностика"] = {k: True for k in м.kiosk_core.КЛЮЧИ}
    п.update(замены)
    return п


def _без_медиа(м, monkeypatch, посылка, **строка_замены):
    """Строка обмена: сотрудник привязан, посылка лежит, фото и видео ещё не присылали."""
    import json as _json
    строка = {"code": "ABCD12", "chat_id": 777, "user_id": 5, "shop_id": 14, "device_id": None,
              "photos": None, "video": None, "checks": None, "media_asked": None, "quote": None,
              "parcel": _json.dumps(посылка, ensure_ascii=False)}
    строка.update(строка_замены)
    взяли, беды, созданы = [], [], []

    async def _строка(код):
        return dict(строка)

    async def _взять(код):
        взяли.append(код)
        return строка["parcel"]

    async def _беда(код, почему):
        беды.append(почему)

    async def _создать(bot, код, п, стр, нажал=None):
        созданы.append(код)
        return {"id": 7311, "цена": 185000, "оценщик": "Асылбек", "точка": "16/38"}, "карточка в личке"

    async def _магазины():
        return [{"id": 14, "shop_name": "16/38 Pintel"}]

    monkeypatch.setattr(м, "_строка", _строка)
    monkeypatch.setattr(м, "_взять", _взять)
    monkeypatch.setattr(м, "_сказать_о_беде", _беда)
    monkeypatch.setattr(м, "_создать", _создать)
    monkeypatch.setattr(м, "_магазины", _магазины)
    м._уже_просили.clear()
    м._пробовали.clear()
    return строка, взяли, беды, созданы


def test_a_parcel_sent_before_the_media_asks_the_linked_employee_and_waits(бот_модуль, monkeypatch):
    """Касса отправляет сделку ДО медиа. Бот сам пишет привязанному сотруднику и ждёт:
    посылку не трогает, отказа не пишет, второй раз не просит."""
    строка, взяли, беды, созданы = _без_медиа(бот_модуль, monkeypatch, _полная(бот_модуль))
    бот = ФейкБот()
    asyncio.run(бот_модуль._обработать_посылку(бот, "ABCD12"))
    asyncio.run(бот_модуль._обработать_посылку(бот, "ABCD12"))      # следующий круг опроса
    assert [ч for ч, _ in бот.письма] == [777], бот.письма
    текст = бот.письма[0][1]
    assert "iPhone 13 128 ГБ" in текст and "*#06#" in текст and "видео" in текст
    assert not взяли and not беды and not созданы


def test_the_price_already_named_to_the_point_is_repeated_in_the_media_request(бот_модуль, monkeypatch):
    """Цену сотрудник уже видел на кассе — в чате она та же, а не «без автоцены»."""
    _без_медиа(бот_модуль, monkeypatch, _полная(бот_модуль),
               quote='{"цена": 185000, "почему": "", "запрос": "q1"}')
    бот = ФейкБот()
    asyncio.run(бот_модуль._обработать_посылку(бот, "ABCD12"))
    assert "185 000 ₸" in бот.письма[0][1]


def test_the_deal_is_made_at_once_when_the_media_is_already_there(бот_модуль, monkeypatch):
    """Старый порядок жив: точка со старой сборкой шлёт посылку после медиа — ждать нечего."""
    строка, взяли, беды, созданы = _без_медиа(бот_модуль, monkeypatch, _полная(бот_модуль),
                                              photos="f1||f2||f3", video="v1")
    бот = ФейкБот()
    asyncio.run(бот_модуль._обработать_посылку(бот, "ABCD12"))
    assert взяли == ["ABCD12"] and созданы == ["ABCD12"] and not беды
    assert "Сделка № 7311" in бот.письма[-1][1]


def test_a_broken_parcel_is_refused_at_once_not_parked_behind_a_media_request(бот_модуль, monkeypatch):
    """Нет модели — это не «ждём фото»: сотрудник прислал бы медиа, а сделки всё равно бы
    не было. Такая посылка идёт обычным путём и получает отказ со словами."""
    плохая = _полная(бот_модуль)
    плохая["сделка"].pop("model")
    строка, взяли, беды, созданы = _без_медиа(бот_модуль, monkeypatch, плохая)
    бот = ФейкБот()
    asyncio.run(бот_модуль._обработать_посылку(бот, "ABCD12"))
    assert взяли == ["ABCD12"]                       # не оставлена ждать
    assert not any("Пришлите" in т for _, т in бот.письма)


def test_an_unreachable_employee_is_named_on_the_point_screen_and_asked_again_later(бот_модуль, monkeypatch):
    """Бот не смог написать (его заблокировали) — касса обязана это показать, а не молча
    ждать медиа, которых никто не попросил."""
    строка, взяли, беды, созданы = _без_медиа(бот_модуль, monkeypatch, _полная(бот_модуль))

    class Глухой(ФейкБот):
        async def send_message(self, **k):
            raise RuntimeError("Forbidden: bot was blocked by the user")

    asyncio.run(бот_модуль._обработать_посылку(Глухой(), "ABCD12"))
    assert беды and "не смог написать" in беды[0]
    assert "ABCD12" not in бот_модуль._уже_просили   # попробуем ещё раз, когда разблокируют


def _прайс(monkeypatch, цена):
    """Подменный utils.google_price: прайс Оценки сюда не привезти."""
    увидел = []

    async def get_price_for_device(устройство):
        увидел.append(устройство)
        return цена

    utils = types.ModuleType("utils")
    gp = types.ModuleType("utils.google_price")
    gp.get_price_for_device = get_price_for_device
    utils.google_price = gp
    monkeypatch.setitem(sys.modules, "utils", utils)
    monkeypatch.setitem(sys.modules, "utils.google_price", gp)
    return увидел


def test_the_price_before_the_deal_is_counted_from_the_same_fields_as_the_deal(бот_модуль, monkeypatch):
    """Цена на экране кассы и в карточке сделки — одно число: прайсу уходят те же поля."""
    увидел = _прайс(monkeypatch, 185000)

    async def _магазины():
        return [{"id": 14}]
    monkeypatch.setattr(бот_модуль, "_магазины", _магазины)
    ответ = asyncio.run(бот_модуль._оценить(_полная(бот_модуль), {"shop_id": 3}))
    assert ответ == {"цена": 185000, "почему": ""}
    у = увидел[0]
    assert (у.producer, у.model, у.ddr, у.akb, у.akb_exact, у.shop_id_grade) == \
        ("Apple", "iPhone 13", 128, "75-79", 75, 14)       # точка — из посылки, а не сотрудника


def test_no_tray_is_priced_by_the_esim_row_before_the_deal_too(бот_модуль, monkeypatch):
    увидел = _прайс(monkeypatch, 170000)

    async def _магазины():
        return [{"id": 14}]
    monkeypatch.setattr(бот_модуль, "_магазины", _магазины)
    п = _полная(бот_модуль)
    п["сделка"]["sim"] = "E-sim"
    asyncio.run(бот_модуль._оценить(п, {"shop_id": 14}))
    assert увидел[0].model == "iPhone 13 (Esim)"


def test_no_auto_price_is_explained_in_words_and_the_price_list_is_not_even_asked(бот_модуль, monkeypatch):
    """Поломка, найденная руками, снимает автоцену — и касса должна знать почему."""
    увидел = _прайс(monkeypatch, 185000)

    async def _магазины():
        return [{"id": 14}]
    monkeypatch.setattr(бот_модуль, "_магазины", _магазины)
    п = _полная(бот_модуль)
    первый = бот_модуль.kiosk_core.КЛЮЧИ[0]
    п["ручная_диагностика"][первый] = False
    ответ = asyncio.run(бот_модуль._оценить(п, {"shop_id": 14}))
    assert ответ["цена"] is None and "проверка руками нашла" in ответ["почему"]
    assert not увидел

    ремонт = _полная(бот_модуль, переклассификация="кабель: экран меняли")
    ремонт["сделка"]["phone_status"] = "Ранее был в ремонте"
    ответ = asyncio.run(бот_модуль._оценить(ремонт, {"shop_id": 14}))
    assert ответ["цена"] is None and "был в ремонте" in ответ["почему"] and "экран меняли" in ответ["почему"]


def test_a_price_request_is_answered_where_the_point_reads_it(бот_модуль, monkeypatch):
    """Запрос цены забирается один раз, ответ ложится в `quote` вместе с меткой запроса."""
    import json as _json
    _прайс(monkeypatch, 185000)
    журнал = []
    запрос = _json.dumps(dict(_полная(бот_модуль), запрос_цены="q-42"), ensure_ascii=False)

    def ответы(текст, параметры):
        if текст.startswith("SELECT quote_request"):
            return запрос
        return None
    monkeypatch.setattr(бот_модуль, "async_session_factory", lambda: Сессия(журнал, ответы))

    async def _строка(код):
        return {"code": код, "shop_id": 14, "checks": None}

    async def _магазины():
        return [{"id": 14}]
    monkeypatch.setattr(бот_модуль, "_строка", _строка)
    monkeypatch.setattr(бот_модуль, "_магазины", _магазины)
    бот = ФейкБот()
    asyncio.run(бот_модуль._посчитать_цену(бот, "ABCD12"))
    тексты = [т for т, _ in журнал]
    assert any("FOR UPDATE" in т for т in тексты)
    assert any(т.startswith("UPDATE kiosk_media SET quote_request = NULL") for т in тексты)
    записано = [п for т, п in журнал if т.startswith("UPDATE kiosk_media SET quote = ")]
    assert записано and _json.loads(записано[0]["q"]) == {"цена": 185000, "почему": "", "запрос": "q-42"}
    assert бот.письма == [], "касса прежней сборки сумму не ждёт — сотрудника не спрашиваем"


def _запрос_цены(бот_модуль, monkeypatch, журнал, *, строка, цена=185000, **в_посылке):
    """Касса спросила цену: запрос лежит в таблице обмена, прайс отвечает `цена`."""
    import json as _json
    _прайс(monkeypatch, цена)
    запрос = _json.dumps(dict(_полная(бот_модуль), запрос_цены="q-42", **в_посылке),
                         ensure_ascii=False)
    monkeypatch.setattr(бот_модуль, "async_session_factory", lambda: Сессия(
        журнал, lambda текст, п: запрос if текст.startswith("SELECT quote_request") else None))

    async def _строка(код):
        return dict(строка, code=код)

    async def _магазины():
        return [{"id": 14}]
    monkeypatch.setattr(бот_модуль, "_строка", _строка)
    monkeypatch.setattr(бот_модуль, "_магазины", _магазины)

    def записано():
        return [_json.loads(п["q"]) for т, п in журнал if т.startswith("UPDATE kiosk_media SET quote = ")]
    return записано


def test_the_price_goes_to_the_employee_as_a_hint_and_the_point_waits_for_his_sum(бот_модуль, monkeypatch):
    """Новая касса цену из прайса клиенту не показывает. Бот шлёт её подсказкой привязанному
    сотруднику и спрашивает сумму; кассе отвечает «жду сумму» — и та просит подождать."""
    class Бот(ФейкБот):
        async def send_message(self, chat_id=None, text=None, **k):
            await super().send_message(chat_id=chat_id, text=text)
            return types.SimpleNamespace(message_id=5512)

    журнал, бот = [], Бот()
    записано = _запрос_цены(бот_модуль, monkeypatch, журнал, сумму_назовёт_сотрудник=True,
                            строка={"shop_id": 14, "checks": None, "chat_id": 777})
    asyncio.run(бот_модуль._посчитать_цену(бот, "ABCD12"))
    assert len(бот.письма) == 1 and бот.письма[0][0] == 777
    assert "185 000 ₸" in бот.письма[0][1] and "Какую сумму показать клиенту" in бот.письма[0][1]
    assert записано() == [{"цена": 185000, "почему": "", "запрос": "q-42", "ждём_сумму": True,
                           "вопрос": 5512}]

    # автоцены нет — спрашивать не о чем: сделку оценит человек
    журнал, бот = [], Бот()
    записано = _запрос_цены(бот_модуль, monkeypatch, журнал, цена=None, сумму_назовёт_сотрудник=True,
                            строка={"shop_id": 14, "checks": None, "chat_id": 777})
    asyncio.run(бот_модуль._посчитать_цену(бот, "ABCD12"))
    assert бот.письма == [] and записано()[0]["цена"] is None and "ждём_сумму" not in записано()[0]

    # бот не смог написать сотруднику — касса узнаёт причину, а не ждёт молча
    class Глухой(ФейкБот):
        async def send_message(self, **k):
            raise RuntimeError("Forbidden: bot was blocked by the user")

    журнал = []
    записано = _запрос_цены(бот_модуль, monkeypatch, журнал, сумму_назовёт_сотрудник=True,
                            строка={"shop_id": 14, "checks": None, "chat_id": 777})
    asyncio.run(бот_модуль._посчитать_цену(Глухой(), "ABCD12"))
    ответ = записано()[0]
    assert ответ["ждём_сумму"] is True and "не смог написать" in ответ["беда"]
    assert "blocked" not in ответ["беда"], "в ответ кассе — причина по-человечески, не текст Telegram"


class Письмо:
    """Сообщение сотрудника боту: текст, чат и то, на что он ответил."""

    def __init__(self, текст, chat_id=777, на=None):
        self.text, self.ответы = текст, []
        self.chat = types.SimpleNamespace(id=chat_id)
        self.reply_to_message = types.SimpleNamespace(message_id=на) if на else None

    async def answer(self, текст, **k):
        self.ответы.append(текст)


class Состояние:
    def __init__(self, имя=None):
        self.имя = имя

    async def get_state(self):
        return self.имя


def test_the_employee_answers_with_a_number_and_it_becomes_the_sum_for_the_client(бот_модуль, monkeypatch):
    """Ответ сотрудника — сообщение из одних цифр. Его ловим по базе, а не по памяти бота:
    есть сделка с вопросом о сумме — число наше. Посреди другого дела в боте (там тоже
    спрашивают цифры) — не наше, кроме ответа именно на сообщение с вопросом."""
    import json as _json
    ждёт = {"цена": 185000, "почему": "", "запрос": "q-42", "ждём_сумму": True, "вопрос": 5512}
    журнал, хранится = [], {"quote": _json.dumps(ждёт, ensure_ascii=False)}

    def ответы(текст, п):
        if текст.startswith("SELECT code, quote FROM kiosk_media WHERE chat_id"):
            return {"code": "ABCD12", "quote": хранится["quote"]} if п["ch"] == 777 else None
        if текст.startswith("SELECT quote FROM kiosk_media WHERE code"):
            return хранится["quote"]
        if текст.startswith("UPDATE kiosk_media SET quote = "):
            хранится["quote"] = п["q"]
        return None
    monkeypatch.setattr(бот_модуль, "async_session_factory", lambda: Сессия(журнал, ответы))
    фильтр, принять = бот_модуль._сумма_без_состояния, бот_модуль.принять_сумму

    def спросить(письмо, состояние=None):
        return asyncio.run(фильтр(письмо, Состояние(состояние)))

    # не цифры, чужой чат, другое дело в боте — мимо; запрос к базе на слова не тратим
    assert спросить(Письмо("привет")) is False and журнал == []
    assert спросить(Письмо("170000", chat_id=999)) is False
    assert спросить(Письмо("170000"), "VikupState:price_buy") is False
    # ответ на сам вопрос — наш, чем бы сотрудник ни был занят
    assert спросить(Письмо("170000", на=5512), "VikupState:price_buy")["ksum_code"] == "ABCD12"
    наше = спросить(Письмо("170 000"))
    assert наше == {"ksum_code": "ABCD12", "ksum_quote": ждёт}

    # опечатку не принимаем и снова называем подсказку
    мало = Письмо("170")
    asyncio.run(принять(мало, **наше))
    assert "слишком мало" in мало.ответы[0] and "185 000 ₸" in мало.ответы[0]
    assert _json.loads(хранится["quote"]) == ждёт, "в ответ кассе ничего не записано"

    да = Письмо("170 000 тг")
    asyncio.run(принять(да, **наше))
    assert "170 000 ₸" in да.ответы[0] and "ниже автоцены на 15 000 ₸" in да.ответы[0]
    стало = _json.loads(хранится["quote"])
    assert стало == {"цена": 185000, "почему": "", "запрос": "q-42", "вопрос": 5512, "сумма": 170000}

    # передумал до отправки — сумму можно назвать другую
    ещё = спросить(Письмо("165000"))
    assert ещё and ещё["ksum_quote"]["сумма"] == 170000
    asyncio.run(принять(Письмо("165000"), **ещё))
    assert _json.loads(хранится["quote"])["сумма"] == 165000

    # касса уже пересчитывает цену (ответ стёрт) — записать некуда, так и говорим
    хранится["quote"] = None
    поздно = Письмо("160000")
    asyncio.run(принять(поздно, **ещё))
    assert "записать некуда" in поздно.ответы[0]


def test_cycles_are_left_out_of_the_deal_until_the_column_exists(бот_модуль, monkeypatch):
    """Колонку devices.akb_cycles добавляют отдельно. Пока её нет, вставка сделки не должна
    падать на всех точках из-за поля, без которого сделка обходилась."""
    ядро = бот_модуль.kiosk_core
    поля = ядро.колонки(_полная(бот_модуль))
    assert поля["akb_cycles"] == 1810 and "akb_cycles" in ядро.sql_devices(поля)
    monkeypatch.setattr(бот_модуль, "async_session_factory",
                        lambda: Сессия([], lambda т, п: None))          # колонки нет
    бот_модуль._колонки.clear()
    assert asyncio.run(бот_модуль._есть_колонка("devices", "akb_cycles")) is False
    monkeypatch.setattr(бот_модуль, "async_session_factory",
                        lambda: Сессия([], lambda т, п: 1))             # добавили на ходу
    assert asyncio.run(бот_модуль._есть_колонка("devices", "akb_cycles")) is True
    мусор = _полная(бот_модуль)
    мусор["сделка"]["akb_cycles"] = -5
    assert ядро.колонки(мусор)["akb_cycles"] is None
