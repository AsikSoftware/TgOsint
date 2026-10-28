# -*- coding: utf-8 -*-
"""Приём фото и видео для сделки из приложения на точке (Pintel Check).

Кладётся в `handlers/` бота Оценки и включается одной строкой в `main.py` — ПЕРЕД
`router_start`, иначе его обработчик `/start` заберёт нашу ссылку себе.

Как это работает: приложение на точке заводит короткий код и показывает QR со ссылкой
`https://t.me/<бот>?start=p<КОД>`. Сотрудник открывает её своим телефоном — бот по
chat_id сразу знает, кто пришёл, и это же становится оценщиком сделки. Дальше сотрудник
шлёт видео и фото, они ложатся в строку с этим кодом как `file_id`, а приложение их
забирает и создаёт сделку.

Почему `file_id`, а не файлы: Оценка и так хранит медиа сделок именно так — хранение
получается бесплатным, и ничего своего поднимать не нужно. Видео обязательно: карточку
сделки Оценка открывает через `InputMediaVideo(device.video_phone)`, и без него открытие
падает.

Своего в базе Оценки заводится одна таблица `kiosk_media` (DDL рядом, kiosk_media.sql).
Код самой Оценки этот файл не трогает.
"""
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import text

from database.engine import async_session_factory

router_kiosk_media = Router()

# Ссылка приходит обычным сообщением «/start pКОД» — префикс «p» отделяет её от других
# переходов на бота. Фильтруем по тексту, а не параметрами CommandStart: так обработчик
# работает в любой версии aiogram 3 и наверняка не перехватит чужой /start.
СТАРТ = re.compile(r"^/start(?:@\w+)?\s+p([A-Z0-9]{4,12})\b")


class KioskMediaState(StatesGroup):
    приём = State()


def _кнопка_готово(код: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово", callback_data=f"kmedia_done_{код}")
    return kb.as_markup()


async def _строка(код: str):
    async with async_session_factory() as session:
        res = await session.execute(
            text("SELECT id, video, photos, done FROM kiosk_media WHERE code = :c"), {"c": код})
        return res.mappings().first()


async def _привязать(код: str, user_id: int | None, chat_id: int) -> None:
    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE kiosk_media SET user_id = :u, chat_id = :ch WHERE code = :c"),
            {"u": user_id, "ch": chat_id, "c": код})
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


@router_kiosk_media.message(F.text.regexp(СТАРТ.pattern))
async def открыть_приём(message: Message, state: FSMContext):
    from database.database import AsyncOrm

    совпало = СТАРТ.match(message.text or "")
    if not совпало:                                   # сюда не попадём, но пусть будет явно
        return
    код = совпало.group(1)
    строка = await _строка(код)
    if строка is None:
        await message.answer("Код не найден. Заведите новый в программе на точке.")
        return
    if строка["done"]:
        await message.answer("По этому коду медиа уже приняты.")
        return

    user = await AsyncOrm.get_user_chat_id(chat_id=message.chat.id)
    await _привязать(код, user.id if user else None, message.chat.id)
    await state.set_state(KioskMediaState.приём)
    await state.update_data(kmedia_code=код)
    кто = f", {user.first_name}" if user and user.first_name else ""
    await message.answer(
        f"Принимаю медиа для сделки{кто}.\n\n"
        "Пришлите <b>видео телефона</b> — без него сделка не открывается, — и фото.\n"
        "Когда закончите, нажмите «Готово».",
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
async def завершить(call: CallbackQuery, state: FSMContext):
    код = call.data.removeprefix("kmedia_done_")
    строка = await _строка(код)
    if строка is None:
        await call.answer("Код не найден", show_alert=True)
        return
    if not строка["video"]:
        await call.answer("Нужно видео телефона — без него сделка не откроется", show_alert=True)
        return
    async with async_session_factory() as session:
        await session.execute(text("UPDATE kiosk_media SET done = true WHERE code = :c"), {"c": код})
        await session.commit()
    await state.clear()
    await call.answer()
    await call.message.answer("Готово. Вернитесь к программе на точке — медиа уже там.")
