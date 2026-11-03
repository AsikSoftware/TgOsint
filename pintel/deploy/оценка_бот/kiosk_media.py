# -*- coding: utf-8 -*-
"""Приём оценки с точки: фото и видео от сотрудника + сама сделка из программы.

Кладётся в `handlers/` бота Оценки и включается одной строкой в `main.py` — ПЕРЕД
`router_start`, иначе его обработчик `/start` заберёт нашу ссылку себе.

Зачем это боту. Программа на точке не может писать в базу Оценки: порт Postgres закрыт
наружу, а своего сервера мы не держим. Зато у бота база под рукой — значит сделку создаёт
он. Канал один, Telegram:

* **медиа.** Программа показывает QR со ссылкой `https://t.me/<бот>?start=p<КОД>`.
  Сотрудник открывает её своим телефоном — бот по chat_id сразу знает, кто пришёл, и это
  же становится оценщиком сделки. Дальше бот ведёт его по шагам — IMEI на экране, лицевая
  сторона, задняя, видео, — и только собрав всё, спрашивает точку. Медиа ложатся в строку
  с этим кодом как `file_id`.
* **сделка.** Программа отправляет её JSON-файлом в рабочую группу, с читаемой карточкой и
  кнопкой. Нажатие на кнопку — единственное, что приносит боту эту посылку: свои
  исходящие сообщения бот не видит, а в `callback_query` Telegram отдаёт сообщение
  целиком, вместе с файлом. Нажатие заодно и подтверждение: в карточке видно ровно то,
  что уйдёт в сделку.

Почему `file_id`, а не файлы: Оценка и так хранит медиа сделок именно так — хранение
получается бесплатным, и ничего своего поднимать не нужно. Видео обязательно: карточку
сделки Оценка открывает через `InputMediaVideo(device.video_phone)`, и без него открытие
падает.

Своего в базе Оценки заводится одна таблица `kiosk_media` (DDL рядом, kiosk_media.sql).
Код самой Оценки этот файл не трогает, разбор посылки и колонки — в kiosk_core.py рядом.
"""
import io
import logging
import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import text

from database.engine import async_session_factory

try:                                   # лежит рядом, в handlers/
    from handlers import kiosk_core
except ImportError:                    # если handlers не пакет — просто соседний модуль
    import kiosk_core

router_kiosk_media = Router()

# Ссылка приходит обычным сообщением «/start pКОД» — префикс «p» отделяет её от других
# переходов на бота. Фильтруем по тексту, а не параметрами CommandStart: так обработчик
# работает в любой версии aiogram 3 и наверняка не перехватит чужой /start.
СТАРТ = re.compile(r"^/start(?:@\w+)?\s+p([A-Z0-9]{4,12})\b")
# пункт ручной диагностики: префикс, код сделки, ключ пункта (ASCII, из kiosk_core.ПУНКТЫ)
ПУНКТ = re.compile(r"^kmchk_([A-Z0-9]{4,12})_([a-z]+)$")
ГОТОВО_ДИАГ = re.compile(r"^kmchkok_([A-Z0-9]{4,12})$")


class KioskMediaState(StatesGroup):
    приём = State()


def _вид_медиа(message: Message):
    """Что прислали: (ЖДЁМ_ВИДЕО|ЖДЁМ_ФОТО, file_id) или (None, None) — не медиа вовсе.

    Документом присылают, когда отправляют «без сжатия» — это те же фото и видео."""
    if message.video or message.video_note:
        return kiosk_core.ЖДЁМ_ВИДЕО, (message.video or message.video_note).file_id
    if message.photo:
        return kiosk_core.ЖДЁМ_ФОТО, message.photo[-1].file_id
    if message.document:
        mime = message.document.mime_type or ""
        if mime.startswith("video/"):
            return kiosk_core.ЖДЁМ_ВИДЕО, message.document.file_id
        if mime.startswith("image/"):
            return kiosk_core.ЖДЁМ_ФОТО, message.document.file_id
    return None, None


async def _сотрудник(chat_id: int):
    """Кто это. Не сотрудник Pintel — не оценщик, и медиа от него не принимаем."""
    from database.database import AsyncOrm
    user = await AsyncOrm.get_user_chat_id(chat_id=chat_id)
    return user if (user and user.staff_id in kiosk_core.ОЦЕНЩИКИ) else None


def _имя(user) -> str:
    if not user:
        return "—"
    return " ".join(x for x in (user.first_name, user.last_name) if x) or (user.phone or "—")


async def _строка(код: str):
    """Строка обмена по коду. Берём её целиком, а не перечисляем колонки.

    Почему: отметки ручной диагностики приезжают теперь в посылке из программы, и колонка
    `checks` нужна только точкам со старой сборкой. В базе её может не быть вовсе —
    запрос с несуществующей колонкой упал бы целиком, и приём медиа встал бы на всех точках
    из-за того, чего мы уже не спрашиваем."""
    async with async_session_factory() as session:
        res = await session.execute(text("SELECT * FROM kiosk_media WHERE code = :c"), {"c": код})
        return res.mappings().first()


async def _завести(код: str, user_id, chat_id: int, shop_id=None) -> None:
    """Строку обмена создаёт бот: с точки в базу хода нет. Код самодостаточен — проверять
    его не у кого, поэтому на первое открытие ссылки просто заводим строку."""
    async with async_session_factory() as session:
        await session.execute(text(
            "INSERT INTO kiosk_media (code, user_id, chat_id, shop_id) VALUES (:c, :u, :ch, :s) "
            # COALESCE: админ мог уже выбрать точку, а потом пересканировать QR —
            # повторное открытие ссылки не должно стирать его выбор
            "ON CONFLICT (code) DO UPDATE SET user_id = :u, chat_id = :ch, "
            "shop_id = COALESCE(:s, kiosk_media.shop_id)"),
            {"c": код, "u": user_id, "ch": chat_id, "s": shop_id})
        await session.commit()


async def _поставить_диагностику(код: str, отметки: dict) -> bool:
    """Отметки из кнопок бота — в строку обмена. → записали?

    Путь для точек со старой сборкой: новая присылает отметки в посылке, и колонки `checks`
    в базе может не быть. Тогда записывать некуда — говорим об этом прямо, а не молча
    теряем нажатия."""
    try:
        async with async_session_factory() as session:
            await session.execute(text("UPDATE kiosk_media SET checks = :v WHERE code = :c"),
                                  {"v": kiosk_core.диагностика_сохранить(отметки), "c": код})
            await session.commit()
        return True
    except Exception as exc:                                     # noqa: BLE001
        logging.getLogger(__name__).warning("kiosk: отметки не записались: %s", exc)
        return False


async def _магазины() -> list:
    async with async_session_factory() as session:
        res = await session.execute(text(
            "SELECT id, litera, shop_name FROM shops ORDER BY shop_name"))
        return [dict(r) for r in res.mappings()]


async def _поставить_точку(код: str, shop_id: int) -> None:
    async with async_session_factory() as session:
        await session.execute(text("UPDATE kiosk_media SET shop_id = :s WHERE code = :c"),
                              {"s": shop_id, "c": код})
        await session.commit()


async def _имя_точки(shop_id):
    if not shop_id:
        return ""
    async with async_session_factory() as session:
        return (await session.execute(text("SELECT shop_name FROM shops WHERE id = :i"),
                                      {"i": shop_id})).scalar() or ""


# ---------------------------------------------------------------- ручная диагностика

ЗНАЧКИ = {None: "⬜", True: "✅", False: "❌"}


def _кнопки_диагностики(код: str, отметки):
    """Пункты по два в ряд: нажатие переключает ⬜ → ✅ → ❌ → ⬜.

    Одно сообщение на всю диагностику, а не вопрос за вопросом: сотрудник держит телефон
    клиента в руках, и двенадцать отдельных сообщений он просто не дочитает. Счётчик живёт
    на кнопке «Готово» — тогда на каждое нажатие правится только клавиатура, одним запросом.
    """
    d = kiosk_core.диагностика_разобрать(отметки)
    kb = InlineKeyboardBuilder()
    for ключ in kiosk_core.КЛЮЧИ:
        kb.button(text=f"{ЗНАЧКИ[d.get(ключ)]} {kiosk_core.КОРОТКО[ключ]}",
                  callback_data=f"kmchk_{код}_{ключ}")
    kb.button(text=("☑️ " if d.get(kiosk_core.ЗАПЕЧАТАН) else "📦 ") + "Запечатан — не вскрывали",
              callback_data=f"kmchk_{код}_{kiosk_core.ЗАПЕЧАТАН}")
    осталось = kiosk_core.не_отмечено(d)
    kb.button(text="Готово" if not осталось else f"Готово · осталось {len(осталось)}",
              callback_data=f"kmchkok_{код}")
    kb.adjust(*([2] * (len(kiosk_core.КЛЮЧИ) // 2 + len(kiosk_core.КЛЮЧИ) % 2) + [1, 1]))
    return kb.as_markup()


def _текст_диагностики() -> str:
    """Текст с кнопками — только для точек со старой сборкой программы.

    Новая спрашивает то же самое на своём экране и присылает отметки в посылке; здесь они
    остались, чтобы такая точка не встала совсем, пока её не обновили."""
    пункты = "\n".join(f"{n}. <b>{к}</b> — {п}" for n, (_, к, п) in enumerate(kiosk_core.ПУНКТЫ, 1))
    return ("<b>Проверки руками</b>.\n"
            "Кабель этого не видит: проверьте телефон руками и отметьте каждый пункт.\n\n"
            + пункты
            + "\n\n⬜ не отмечено · ✅ работает · ❌ не работает или не проверить\n"
              "Нечем проверить — ставьте ❌: сделка уйдёт на оценку человеку.\n"
              "Без всех отметок сделку не создам.")


async def _дальше(отправить, код: str, шапка: str = "") -> None:
    """Что сотруднику делать прямо сейчас: фото → видео → отправка из программы.

    Одно место на все входы (ссылка из QR, присланное медиа): порядок шагов не должен
    расходиться между ними.

    Ни точку, ни проверки руками здесь не спрашивают. Точка приходит готовой в посылке:
    программа на точке знает свой `shop_id` (это тот же магазин Оценки, с тем же id).
    Проверки руками отмечают на экране программы, пока телефон клиента лежат на столе, —
    кнопки в чате были лишним шагом, на котором ещё и ошибались.
    """
    строка = await _строка(код)
    if строка is None:
        return
    осталось = kiosk_core.чего_не_хватает(строка)
    if осталось:
        await отправить(f"{шапка}Сейчас: {осталось[0]}")
        return
    await отправить(f"{шапка}Медиа собраны. Отметьте проверки руками на экране программы "
                    "и отправьте оценку оттуда — сделку создам по этому коду.")


async def _добавить(код: str, file_id: str, видео: bool) -> None:
    """Видео одно — последнее присланное; фото копятся через «||», как в самой Оценке."""
    async with async_session_factory() as session:
        if видео:
            await session.execute(text("UPDATE kiosk_media SET video = :v WHERE code = :c"),
                                  {"v": file_id[:200], "c": код})
        else:
            await session.execute(text(
                "UPDATE kiosk_media SET photos = CASE WHEN photos IS NULL OR photos = '' "
                "THEN :p ELSE photos || '||' || :p END WHERE code = :c"),
                {"p": file_id, "c": код})
        await session.commit()


# ---------------------------------------------------------------- фото и видео

@router_kiosk_media.message(F.text.regexp(СТАРТ.pattern))
async def открыть_приём(message: Message, state: FSMContext):
    совпало = СТАРТ.match(message.text or "")
    if not совпало:                                   # сюда не попадём, но пусть будет явно
        return
    код = совпало.group(1)
    сотрудник = await _сотрудник(message.chat.id)
    if сотрудник is None:
        await message.answer("Этот код — для сотрудников Pintel. Если вы сотрудник, "
                             "зарегистрируйтесь в боте и откройте ссылку снова.")
        return
    строка = await _строка(код)
    if строка and строка["device_id"]:
        await message.answer(f"По этому коду сделка № {строка['device_id']} уже создана.")
        return

    shop_id = kiosk_core.точка_сотрудника(сотрудник.staff_id, сотрудник.shop_id)
    await _завести(код, сотрудник.id, message.chat.id, shop_id)
    await state.set_state(KioskMediaState.приём)
    await state.update_data(kmedia_code=код)
    # Точку не спрашиваем вовсе: её присылает программа (её `shop_id` — это тот же магазин
    # Оценки). Свою называем просто для спокойствия — видно, что бот понял, откуда сделка.
    точка = (f"Точка: <b>{await _имя_точки(shop_id)}</b> — ваша.\n" if shop_id
             else "Точку возьму из программы — выбирать её не нужно.\n")
    await message.answer(
        f"Принимаю оценку с точки, {сотрудник.first_name or 'коллега'}.\n"
        f"{точка}\n"
        f"{kiosk_core.шаги_списком()}\n\n"
        f"Медиа присылайте по одному, в этом порядке — приму только то, что нужно на шаге.\n"
        f"Проверки руками (кнопки, вибрация, SIM, герметик) отмечайте на экране программы: "
        f"телефон клиента у вас в руках, а не в чате."
    )
    # что именно сейчас, считает одно место: ссылку открывают и повторно, когда медиа уже
    # собраны, и тогда вместо «пришлите фото» нужна диагностика или отправка из программы
    await _дальше(message.answer, код)


@router_kiosk_media.message(KioskMediaState.приём, F.video | F.video_note | F.photo | F.document)
async def принять(message: Message, state: FSMContext):
    данные = await state.get_data()
    код = данные.get("kmedia_code")
    if not код:
        await state.clear()
        return

    что, file_id = _вид_медиа(message)
    if что is None:                        # не фото и не видео — не наше дело
        return
    строка = await _строка(код)
    if строка is None:
        return
    if строка["device_id"]:
        await message.answer(f"По этому коду сделка № {строка['device_id']} уже создана — "
                             "медиа к ней больше не принимаю.")
        return

    ждём = kiosk_core.что_ждём(строка)
    if ждём is not None and что != ждём:
        # Не своё не принимаем вовсе: иначе «Видео принято. Теперь фото задней стороны» —
        # и сотрудник думает, что видео уже учтено, хотя его шаг ещё впереди.
        await message.answer(kiosk_core.не_то_прислали(строка, что))
        return

    await _добавить(код, file_id, видео=(что == kiosk_core.ЖДЁМ_ВИДЕО))
    строка = await _строка(код)
    if строка is None:
        return
    if что == kiosk_core.ЖДЁМ_ВИДЕО:
        текст = "✅ Видео принято."
    else:
        n, надо = kiosk_core.сколько_фото(строка), len(kiosk_core.ЭТАПЫ_ФОТО)
        текст = (f"✅ Фото {n} из {надо} принято." if n <= надо
                 else f"✅ Ещё одно фото принято, всего {n}.")

    # что дальше — точка, ручная диагностика или отправка из программы — решает _дальше:
    # список точек и диагностику на каждое фото не шлём, только когда до них дошли
    await _дальше(message.answer, код, шапка=f"{текст}\n\n")


@router_kiosk_media.callback_query(F.data.startswith("kmedia_done_"))
async def что_принято(call: CallbackQuery):
    """Кнопки «Я всё отправил» больше нет: бот ведёт по шагам и сам знает, когда собрано.

    Обработчик оставлен для кнопок в прежних сообщениях — они остались в чатах, и
    нажатие не должно висеть без ответа."""
    код = call.data.removeprefix("kmedia_done_")
    строка = await _строка(код)
    if строка is None:
        await call.answer("Код не найден", show_alert=True)
        return
    await call.answer()
    await _дальше(call.message.answer, код)


@router_kiosk_media.callback_query(F.data.startswith("kmedia_shop_"))
async def выбрать_точку(call: CallbackQuery):
    """Точку больше не выбирают: она приходит в посылке из программы.

    Обработчик оставлен для кнопок в прежних сообщениях — они остались в чатах, и нажатие
    не должно висеть без ответа."""
    await call.answer("Точку больше не выбирают: её присылает программа с точки",
                      show_alert=True)


# ---------------------------------------------------------------- ручная диагностика: нажатия

@router_kiosk_media.callback_query(F.data.regexp(ПУНКТ.pattern))
async def отметить_пункт(call: CallbackQuery):
    """Нажали на пункт диагностики: переключаем ⬜ → ✅ → ❌ → ⬜ и правим клавиатуру."""
    совпало = ПУНКТ.match(call.data or "")
    if not совпало:
        await call.answer()
        return
    код, ключ = совпало.group(1), совпало.group(2)
    if await _сотрудник(call.from_user.id) is None:
        await call.answer("Диагностику отмечают сотрудники Pintel", show_alert=True)
        return
    строка = await _строка(код)
    if строка is None:
        await call.answer("Код не найден", show_alert=True)
        return
    if строка["device_id"]:
        await call.answer(f"Сделка № {строка['device_id']} уже создана — отметки не меняю",
                          show_alert=True)
        return
    отметки = kiosk_core.диагностика_переключить(строка.get("checks"), ключ)
    if not await _поставить_диагностику(код, отметки):
        await call.answer("Отметки некуда записать: отметьте проверки на экране программы "
                          "на точке (обновите её, если такой карточки нет)", show_alert=True)
        return
    знак = {None: "не отмечено", True: "работает", False: "НЕ работает"}
    if ключ == kiosk_core.ЗАПЕЧАТАН:
        await call.answer("Коробку не вскрывали" if отметки.get(kiosk_core.ЗАПЕЧАТАН)
                          else "Отметка снята")
    else:
        await call.answer(f"{kiosk_core.КОРОТКО.get(ключ, ключ)}: {знак[отметки.get(ключ)]}")
    try:
        await call.message.edit_reply_markup(reply_markup=_кнопки_диагностики(код, отметки))
    except Exception:                      # noqa: BLE001 — то же сообщение, Telegram иногда отказывает
        pass


@router_kiosk_media.callback_query(F.data.regexp(ГОТОВО_ДИАГ.pattern))
async def подтвердить_диагностику(call: CallbackQuery):
    """«Готово» под диагностикой: либо называем, чего не отметили, либо подтверждаем."""
    совпало = ГОТОВО_ДИАГ.match(call.data or "")
    if not совпало:
        await call.answer()
        return
    код = совпало.group(1)
    строка = await _строка(код)
    if строка is None:
        await call.answer("Код не найден", show_alert=True)
        return
    осталось = kiosk_core.не_отмечено(строка.get("checks"))
    if осталось:
        await call.answer("Не отмечено: " + ", ".join(осталось)[:170], show_alert=True)
        return
    плох = [имя for _, имя in kiosk_core.плохие(строка.get("checks"))]
    await call.answer("Диагностика принята")
    итог = ("НЕ работает: " + ", ".join(плох) + ".\nСделка уйдёт оценщику на ручную оценку."
            if плох else "Всё работает.")
    await call.message.answer(f"✅ Ручная диагностика принята. {итог}\n\n"
                              "Отправьте оценку из программы — сделку создам по этому коду.")


# ---------------------------------------------------------------- сама сделка

@router_kiosk_media.callback_query(F.data.startswith(kiosk_core.ПРЕФИКС_КНОПКИ))
async def создать_сделку(call: CallbackQuery, bot: Bot):
    """Нажали «Создать сделку» под карточкой из программы."""
    код = call.data.removeprefix(kiosk_core.ПРЕФИКС_КНОПКИ)
    нажал = await _сотрудник(call.from_user.id)
    if нажал is None:
        await call.answer("Создавать сделки могут только сотрудники Pintel", show_alert=True)
        return
    строка = await _строка(код)
    if строка is None:
        await call.answer(f"По коду {код} медиа не присылали — откройте ссылку из программы "
                          "и пришлите видео", show_alert=True)
        return
    if строка["device_id"]:
        await call.answer(f"По этому коду сделка № {строка['device_id']} уже создана",
                          show_alert=True)
        return
    док = call.message.document if call.message else None
    if док is None:
        await call.answer("К карточке не приложен файл сделки", show_alert=True)
        return

    try:
        буфер = io.BytesIO()
        файл = await bot.get_file(док.file_id)
        await bot.download_file(файл.file_path, буфер)
        посылка = kiosk_core.разобрать(буфер.getvalue())
        if посылка["код"] != код:
            raise kiosk_core.ОшибкаПосылки("код в файле не совпадает с кнопкой")
        # Точка сделки — та, где стоит программа: её `shop_id` приходит в посылке и это тот
        # же магазин Оценки, с тем же id. Она главнее магазина сотрудника: медиа мог сдать
        # администратор, закреплённый за другой точкой, а сделка случилась здесь.
        свой = kiosk_core.точка_из_посылки(посылка, await _магазины())
        if свой and свой != строка["shop_id"]:
            await _поставить_точку(код, свой)
            строка = await _строка(код)
        нет = kiosk_core.проверить(посылка, строка)
        if нет:
            await call.answer("Не хватает: " + "; ".join(нет)[:180], show_alert=True)
            # Отметок нет и программа их не присылала — значит на точке старая сборка, где
            # проверки руками спрашивал бот. Тогда шлём кнопки, как раньше: иначе такая
            # точка не создаст ни одной сделки, пока её не обновят. Записывать их некуда,
            # если в базе нет колонки `checks`, — тогда остаётся только обновить программу.
            старая_сборка = not kiosk_core.диагностика_из_посылки(посылка)
            if (старая_сборка and строка["chat_id"] and "checks" in строка
                    and not kiosk_core.диагностика_готова(строка.get("checks"))):
                try:
                    await bot.send_message(
                        chat_id=строка["chat_id"],
                        text=f"Сделку по коду {код} не создал: нет проверок руками.\n"
                             "На новой версии программы их отмечают на её экране — "
                             "а пока отметьте здесь.\n\n" + _текст_диагностики(),
                        reply_markup=_кнопки_диагностики(код, строка.get("checks")))
                except Exception as exc:                         # noqa: BLE001
                    logging.getLogger(__name__).warning("kiosk: диагностика не ушла: %s", exc)
            return
        сделка = await _вставить(посылка, строка, нажал=нажал)
    except kiosk_core.ОшибкаПосылки as exc:
        await call.answer(str(exc)[:190], show_alert=True)
        return
    except Exception as exc:                                     # noqa: BLE001
        await call.answer("Не получилось создать сделку, подробности в чате", show_alert=True)
        await call.message.answer(f"❌ Сделка по коду {код} не создалась: "
                                  f"<code>{type(exc).__name__}: {exc}</code>")
        return

    await call.answer(f"Сделка № {сделка['id']} создана")
    try:
        куда = await _позвать_дальше(bot, строка, сделка)
    except Exception as exc:                                     # noqa: BLE001
        # сделка уже создана, но без карточки её никто не увидит — говорим прямо
        куда = f"⚠️ передать дальше не вышло: {type(exc).__name__}: {exc}"
    шапка = (call.message.caption or "").split("\n\n")[0]
    цена = f" · {сделка['цена']:,} ₸".replace(",", " ") if сделка.get("цена") else " · без автоцены"
    итог = (f"✅ Сделка № {сделка['id']}{цена} · оценил {сделка['оценщик']}"
            + (f" · {сделка['точка']}" if сделка.get("точка") else ""))
    хвост = f"{итог}\n{куда}"
    try:
        await call.message.edit_caption(caption=f"{шапка}\n\n{хвост}")
    except Exception:                                            # noqa: BLE001 — подпись не главное
        await call.message.answer(хвост)


async def _вставить(посылка: dict, медиа, нажал=None) -> dict:
    """Клиент, сделка и IMEI — одной транзакцией, ровно теми колонками, что пишет бот."""
    from database.database import AsyncOrm
    клиент = посылка.get("клиент") or {}
    телефон = str(клиент.get("телефон") or "").strip()[:13]

    async with async_session_factory() as session:
        client_id = (await session.execute(
            text("SELECT id FROM users WHERE phone = :ph"), {"ph": телефон})).scalar()

    if client_id is None:                                # заводим клиента её же методом
        client_id = await AsyncOrm.add_client(
            first_name=str(клиент.get("имя") or "Клиент").strip()[:150], phone=телефон)
        if client_id is None:
            raise kiosk_core.ОшибкаПосылки("не удалось создать клиента — проверьте номер")

    # оценщик — тот, кто снимал видео; если строку завели без него, пусть будет нажавший
    оценщик_id = медиа["user_id"] or (нажал.id if нажал else None)
    shop_id = медиа["shop_id"]                 # у продавца своя точка, админ выбрал её в боте
    фото = [x for x in str(медиа["photos"] or "").split("||") if x]
    поля = kiosk_core.колонки(посылка)
    # Ручная диагностика сотрудника, тест с телефона клиента и неполнота проверки — в
    # состояние сделки и в комментарий оценщика. Найденная руками поломка снимает автоцену,
    # иначе диагностика осталась бы отчётом ни о чём.
    отметки = kiosk_core.отметки(посылка, медиа)
    поля = kiosk_core.применить_диагностику(поля, отметки, посылка)
    поля.update({
        # цену и статус ставим после вставки: автоцену считает сама Оценка по своему
        # прайсу (utils/google_price.py), ровно как в её собственном потоке
        "status_id": None,
        "price_grade_auto": None,
        "user_client": client_id,
        "user_grade": оценщик_id,
        "shop_id_grade": shop_id,
        "photo_phone": ("||".join(фото) or None),
        "video_phone": str(медиа["video"] or "")[:200],
        "active_user": 0,
    })
    sql = kiosk_core.sql_devices(поля)
    async with async_session_factory() as session:
        device_id = (await session.execute(text(sql), поля)).scalar()
        for imei, первый in kiosk_core.имейки(посылка):
            await session.execute(text(
                "INSERT INTO device_imeis (device_id, imei, verifi, first) "
                "VALUES (:d, :i, :v, :f)"),
                {"d": device_id, "i": imei, "v": bool(посылка.get("imei_проверен", True)),
                 "f": первый})
        await session.execute(text(
            "UPDATE kiosk_media SET done = true, device_id = :d WHERE code = :c"),
            {"d": device_id, "c": посылка["код"]})
        await session.commit()

    # Цену считаем ТОЛЬКО там, где автооценка вообще положена: б/у в нормальном состоянии,
    # не был в ремонте, и проверка полная. Остальным колонка остаётся пустой — иначе в
    # карточке запечатанного или ремонтного аппарата стояла бы цена из прайса, которой
    # клиенту никто не называл, и её легко принять за оценку.
    можно = kiosk_core.автоцена_положена({"phone_status": поля.get("phone_status")},
                                         отметки, посылка)
    цена = await _автоцена(device_id) if можно else None
    статус = kiosk_core.статус_id({"phone_status": поля.get("phone_status"),
                                   "price_grade_auto": цена}, отметки, посылка)
    async with async_session_factory() as session:
        await session.execute(text(
            "UPDATE devices SET price_grade_auto = :p, status_id = :s WHERE id = :i"),
            {"p": цена, "s": статус, "i": device_id})
        await session.commit()

    оценщик = None
    if оценщик_id:
        async with async_session_factory() as session:
            оценщик = (await session.execute(text(
                "SELECT first_name, last_name, phone, lang FROM users WHERE id = :i"),
                {"i": оценщик_id})).mappings().first()
    имя = " ".join(x for x in ((оценщик or {}).get("first_name"),
                               (оценщик or {}).get("last_name")) if x)
    return {"id": int(device_id), "статус": статус, "цена": цена,
            "оценщик": имя or _имя(нажал), "точка": await _имя_точки(shop_id),
            "lang": (оценщик or {}).get("lang") or "ru"}


async def _автоцена(device_id: int):
    """Цена по прайсу Оценки — её же методом. Прайс недоступен → None, и сделка уходит
    администратору на ручную оценку, как и у неё."""
    try:
        from database.database import AsyncOrm
        from utils.google_price import get_price_for_device
        устройство = await AsyncOrm.get_device(device_id)
        return await get_price_for_device(устройство) if устройство else None
    except Exception as exc:                                     # noqa: BLE001 — цена не повод терять сделку
        logging.getLogger(__name__).warning("kiosk: автоцена не посчиталась: %s", exc)
        return None


async def _позвать_дальше(bot: Bot, медиа, сделка: dict) -> str:
    """Сделку создали — теперь её должен кто-то увидеть. → куда она ушла, словами.

    У бота после создания есть продолжение, без которого сделка повисает:

    * статус «Оценен» (чистый аппарат с автоценой) — карточка с кнопками «Выкуп» и
      «Закрыть» уходит оценщику в личку. В списках такой сделки нет вовсе, и без карточки
      довести её до выкупа некому.
    * статус «Ожидает оценку» — админам «❗Ждут оценку❗», сделка видна в «💸 Новая оценка».

    Кнопки `vikup_buy_*` ловит post_grade.py без фильтра по состоянию FSM, поэтому слать
    их можно и отсюда.
    """
    # импорты внутри функции: в utils.utils круговой импорт с keyboards
    from aiogram.types import InputMediaPhoto, InputMediaVideo
    from database.database import AsyncOrm
    from keyboards import keyboards
    from utils.utils import create_tex, send_admins_any

    lang = сделка.get("lang") or "ru"
    if сделка["статус"] == kiosk_core.СТАТУС_АВТО and медиа["chat_id"]:
        группа = [InputMediaVideo(media=медиа["video"])]
        группа += [InputMediaPhoto(media=p)
                   for p in str(медиа["photos"] or "").split("||")[:9] if p]
        await bot.send_media_group(chat_id=медиа["chat_id"], media=группа)
        await bot.send_message(chat_id=медиа["chat_id"],
                               text=await create_tex(device_id=сделка["id"], lang=lang),
                               reply_markup=keyboards.user_vikup_kb(lang, сделка["id"]))
        return "карточка у оценщика в личке"
    await send_admins_any(text="❗Ждут оценку❗", bot=bot,
                          admins=await AsyncOrm.get_active_admin_chat_ids())
    return "ждёт админа в «💸 Новая оценка»"


# ---------------------------------------------------------------- наладка

@router_kiosk_media.message(F.text.regexp(r"^/kiosk_id(?:@\w+)?\b"))
async def номер_чата(message: Message):
    """Чтобы узнать chat_id рабочей группы для kiosk.toml — иначе его негде взять."""
    await message.answer(f"chat_id: <code>{message.chat.id}</code>\n"
                         "Впишите его в kiosk.toml как ocenka_chat_id.")
