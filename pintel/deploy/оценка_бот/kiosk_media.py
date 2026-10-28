# -*- coding: utf-8 -*-
"""Приём оценки с точки: фото и видео от сотрудника + сама сделка из программы.

Кладётся в `handlers/` бота Оценки и включается одной строкой в `main.py` — ПЕРЕД
`router_start`, иначе его обработчик `/start` заберёт нашу ссылку себе.

Зачем это боту. Программа на точке не может писать в базу Оценки: порт Postgres закрыт
наружу, а своего сервера мы не держим. Зато у бота база под рукой — значит сделку создаёт
он. Канал один, Telegram:

* **медиа.** Программа показывает QR со ссылкой `https://t.me/<бот>?start=p<КОД>`.
  Сотрудник открывает её своим телефоном — бот по chat_id сразу знает, кто пришёл, и это
  же становится оценщиком сделки. Дальше сотрудник шлёт видео и фото, они ложатся в строку
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
ОЦЕНЩИКИ = (1, 2)                      # staff_id в Оценке: 1 — админ, 2 — продавец, 3 — клиент


class KioskMediaState(StatesGroup):
    приём = State()


def _кнопка_готово(код: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Я всё отправил", callback_data=f"kmedia_done_{код}")
    return kb.as_markup()


async def _сотрудник(chat_id: int):
    """Кто это. Не сотрудник Pintel — не оценщик, и медиа от него не принимаем."""
    from database.database import AsyncOrm
    user = await AsyncOrm.get_user_chat_id(chat_id=chat_id)
    return user if (user and user.staff_id in ОЦЕНЩИКИ) else None


def _имя(user) -> str:
    if not user:
        return "—"
    return " ".join(x for x in (user.first_name, user.last_name) if x) or (user.phone or "—")


async def _строка(код: str):
    async with async_session_factory() as session:
        res = await session.execute(text(
            "SELECT id, video, photos, done, device_id, user_id FROM kiosk_media WHERE code = :c"),
            {"c": код})
        return res.mappings().first()


async def _завести(код: str, user_id, chat_id: int) -> None:
    """Строку обмена создаёт бот: с точки в базу хода нет. Код самодостаточен — проверять
    его не у кого, поэтому на первое открытие ссылки просто заводим строку."""
    async with async_session_factory() as session:
        await session.execute(text(
            "INSERT INTO kiosk_media (code, user_id, chat_id) VALUES (:c, :u, :ch) "
            "ON CONFLICT (code) DO UPDATE SET user_id = :u, chat_id = :ch"),
            {"c": код, "u": user_id, "ch": chat_id})
        await session.commit()


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

    await _завести(код, сотрудник.id, message.chat.id)
    await state.set_state(KioskMediaState.приём)
    await state.update_data(kmedia_code=код)
    await message.answer(
        f"Принимаю медиа для сделки, {сотрудник.first_name or 'коллега'}.\n\n"
        "Пришлите <b>видео телефона</b> — без него сделка не открывается, — и фото.\n"
        "Потом вернитесь к программе и отправьте оценку.",
        reply_markup=_кнопка_готово(код),
    )


@router_kiosk_media.message(KioskMediaState.приём, F.video | F.video_note | F.photo | F.document)
async def принять(message: Message, state: FSMContext):
    данные = await state.get_data()
    код = данные.get("kmedia_code")
    if not код:
        await state.clear()
        return

    if message.video or message.video_note:
        file_id = (message.video or message.video_note).file_id
        await _добавить(код, file_id, видео=True)
        await message.answer("Видео принято.", reply_markup=_кнопка_готово(код))
        return
    if message.photo:
        await _добавить(код, message.photo[-1].file_id, видео=False)
        await message.answer("Фото принято.", reply_markup=_кнопка_готово(код))
        return
    # документом присылают, когда отправляют «без сжатия» — это те же фото и видео
    mime = (message.document.mime_type or "") if message.document else ""
    if mime.startswith(("image/", "video/")):
        await _добавить(код, message.document.file_id, видео=mime.startswith("video/"))
        await message.answer("Принято.", reply_markup=_кнопка_готово(код))


@router_kiosk_media.callback_query(F.data.startswith("kmedia_done_"))
async def что_принято(call: CallbackQuery):
    """Сотруднику важно знать, дошло ли видео: без него сделка не создастся."""
    код = call.data.removeprefix("kmedia_done_")
    строка = await _строка(код)
    if строка is None:
        await call.answer("Код не найден", show_alert=True)
        return
    фото = len([x for x in str(строка["photos"] or "").split("||") if x])
    if not строка["video"]:
        await call.answer("Видео телефона ещё не пришло — без него сделка не откроется",
                          show_alert=True)
        return
    await call.answer()
    await call.message.answer(f"Принято: видео есть, фото {фото}. "
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
        нет = kiosk_core.проверить(посылка, строка)
        if нет:
            await call.answer("Не хватает: " + "; ".join(нет)[:180], show_alert=True)
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
    шапка = (call.message.caption or "").split("\n\n")[0]
    хвост = (f"✅ Сделка № {сделка['id']} · оценил {сделка['оценщик']}"
             if сделка["статус"] == kiosk_core.СТАТУС_АВТО else
             f"✅ Сделка № {сделка['id']} · оценил {сделка['оценщик']}\n"
             "⚠️ Без автоцены — ушла администратору на ручную оценку, предупредите его")
    try:
        await call.message.edit_caption(caption=f"{шапка}\n\n{хвост}")
    except Exception:                                            # noqa: BLE001 — подпись не главное
        await call.message.answer(хвост)


async def _вставить(посылка: dict, медиа, нажал=None) -> dict:
    """Клиент, сделка и IMEI — одной транзакцией, ровно теми колонками, что пишет бот."""
    from database.database import AsyncOrm
    литера = str(посылка.get("литера") or "").strip()
    клиент = посылка.get("клиент") or {}
    телефон = str(клиент.get("телефон") or "").strip()[:13]

    async with async_session_factory() as session:
        shop_id = None
        if литера:
            shop_id = (await session.execute(
                text("SELECT id FROM shops WHERE litera = :l"), {"l": литера})).scalar()
            if shop_id is None:
                raise kiosk_core.ОшибкаПосылки(f"в Оценке нет магазина с литерой «{литера}»")
        client_id = (await session.execute(
            text("SELECT id FROM users WHERE phone = :ph"), {"ph": телефон})).scalar()

    if client_id is None:                                # заводим клиента её же методом
        client_id = await AsyncOrm.add_client(
            first_name=str(клиент.get("имя") or "Клиент").strip()[:150], phone=телефон)
        if client_id is None:
            raise kiosk_core.ОшибкаПосылки("не удалось создать клиента — проверьте номер")

    # оценщик — тот, кто снимал видео; если строку завели без него, пусть будет нажавший
    оценщик_id = медиа["user_id"] or (нажал.id if нажал else None)
    фото = [x for x in str(медиа["photos"] or "").split("||") if x]
    поля = kiosk_core.колонки(посылка)
    поля.update({
        "status_id": kiosk_core.статус_id(поля),
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

    оценщик = None
    if оценщик_id:
        async with async_session_factory() as session:
            оценщик = (await session.execute(text(
                "SELECT first_name, last_name, phone FROM users WHERE id = :i"),
                {"i": оценщик_id})).mappings().first()
    имя = " ".join(x for x in ((оценщик or {}).get("first_name"),
                               (оценщик or {}).get("last_name")) if x)
    return {"id": int(device_id), "статус": поля["status_id"],
            "оценщик": имя or _имя(нажал)}


# ---------------------------------------------------------------- наладка

@router_kiosk_media.message(F.text.regexp(r"^/kiosk_id(?:@\w+)?\b"))
async def номер_чата(message: Message):
    """Чтобы узнать chat_id рабочей группы для kiosk.toml — иначе его негде взять."""
    await message.answer(f"chat_id: <code>{message.chat.id}</code>\n"
                         "Впишите его в kiosk.toml как ocenka_chat_id.")
