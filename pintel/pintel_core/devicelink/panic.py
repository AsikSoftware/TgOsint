# -*- coding: utf-8 -*-
"""Panic full — отчёты о панике ядра, по которым на выкупе узнают проблему платы.

Смотрим туда же, куда смотрят глазами: «Настройки → Конфиденциальность и безопасность →
Аналитика и улучшения → Данные аналитики». Это каталог crash-логов, и по кабелю его
отдаёт сервис `com.apple.crashreportcopymobile`.

Берём ТОЛЬКО список имён. Файлы не скачиваем и ничего не удаляем: это телефон клиента,
логи — его, и после проверки они должны остаться на месте. `panic-full-*.ips` — полный
отчёт о панике ядра; `panic-base-*` и прочие считаем просто паниками.

«Проверено: нет» — не вердикт, а «список не прочитался». Пустой ответ у Оценки означает
«не знаем», и это честнее, чем выдать «ошибки нет» без проверки.
"""
import asyncio
import re

ПОЛНАЯ = re.compile(r"(?i)^panic-full")
ЛЮБАЯ = re.compile(r"(?i)panic")
ДАТА = re.compile(r"(\d{4}-\d{2}-\d{2})")
# каталог, куда iOS убирает старые отчёты — их тоже видно в «Аналитике»
ГЛУБИНА = 2


def разобрать(имена) -> dict:
    """Список файлов crash-логов → что из них следует. Отдельно от чтения, чтобы разбор
    проверялся тестами, а не живым телефоном."""
    файлы = [str(n).rsplit("/", 1)[-1] for n in (имена or []) if n]
    полные = [f for f in файлы if ПОЛНАЯ.match(f)]
    паники = [f for f in файлы if ЛЮБАЯ.search(f)]
    даты = sorted(d.group(1) for d in (ДАТА.search(f) for f in полные) if d)
    return {
        "проверено": True,
        "panic_full": bool(полные),
        "полных": len(полные),
        "паник_всего": len(паники),
        "последняя": даты[-1] if даты else None,
        "файлов": len(файлы),
    }


async def probe(ld, timeout=25) -> dict:
    """→ разобрать(список) либо {проверено: False, ошибка}. Исключений не бросает."""
    try:
        from pymobiledevice3.services.crash_reports import CrashReportsManager
    except Exception as e:                                   # noqa: BLE001
        return {"проверено": False, "panic_full": None,
                "ошибка": f"нет crash_reports в pymobiledevice3: {e}"}

    async def run():
        async with CrashReportsManager(ld) as crash:
            return await crash.ls("/", depth=ГЛУБИНА)        # только имена, ничего не трогаем

    try:
        return разобрать(await asyncio.wait_for(run(), timeout))
    except Exception as e:                                   # noqa: BLE001
        return {"проверено": False, "panic_full": None,
                "ошибка": f"{type(e).__name__}: {str(e)[:120]}"}


def словами(p: dict) -> str:
    """Строка для отчёта и комментария оценщика."""
    if not p or not p.get("проверено"):
        return "panic full: не проверено"
    if not p.get("panic_full"):
        прочее = f", других паник {p['паник_всего']}" if p.get("паник_всего") else ""
        return f"panic full: нет{прочее}"
    когда = f" (последняя {p['последняя']})" if p.get("последняя") else ""
    return f"panic full: ЕСТЬ, {p['полных']} шт.{когда}"
